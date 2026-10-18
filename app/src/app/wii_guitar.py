"""Guitarra de Wii (extensión del Wiimote) leída directamente por HID.

SDL reconoce el Wiimote pero no la extensión de guitarra ("Unknown Extension"): solo da los botones del
propio Wiimote. Aquí se habla el protocolo del Wiimote (https://wiibrew.org/wiki/Wiimote):

1. Activar la extensión sin cifrado: 0x55 en el registro 0xA400F0 y 0x00 en 0xA400FB.
2. Leer su identificador (6 bytes en 0xA400FA): la guitarra es 00 00 A4 20 01 03.
3. Pedir informes continuos 0x32 (2 bytes de botones del Wiimote + 8 de la extensión) o, con accel=True,
   0x35: botones, 3 bytes del acelerómetro (para levantar la guitarra: star power) y 16 de la extensión. La calibración del acelerómetro (cero y 1 g por eje) está
   en la memoria del Wiimote, en 0x16.
4. Cuando se enchufa o desenchufa la extensión llega un informe de estado (0x20) y el Wiimote deja de
   mandar datos: se repite desde 1.

Los 6 bytes de la guitarra (botones a 0 cuando están pulsados):
    0: joystick X (bits 0-5)    1: joystick Y (bits 0-5)    2: barra táctil (WT)    3: palanca (bits 0-4)
    4: bit 6 strum abajo, bit 4 Select (-), bit 2 Start (+)
    5: bit 7 naranja, bit 6 rojo, bit 5 azul, bit 4 verde, bit 3 amarillo, bit 0 strum arriba

No necesita foco: se lee el dispositivo, no eventos de ventana.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import hid

from .i18n import t

NINTENDO = 0x057E
WIIMOTE_PIDS = (0x0306, 0x0330)  # RVL-CNT-01 y RVL-CNT-01-TR (Motion Plus integrado)
GUITAR_ID = bytes([0x00, 0x00, 0xA4, 0x20, 0x01, 0x03])
FRETS = ("verde", "rojo", "amarillo", "azul", "naranja")
_FRET_BITS = (4, 6, 3, 5, 7)  # bit del byte 5 de cada traste, en el orden de FRETS


@dataclass
class GuitarState:
    frets: tuple[bool, ...] = (False,) * 5  # verde, rojo, amarillo, azul, naranja
    strum_up: bool = False
    strum_down: bool = False
    start: bool = False
    select: bool = False
    whammy: float = 0.0  # 0 suelta .. 1 a fondo
    stick: tuple[float, float] = (0.0, 0.0)  # -1..1
    wiimote: int = 0  # botones del propio Wiimote (2 bytes)
    accel: tuple[float, float, float] = (0.0, 0.0, 0.0)  # acelerómetro del Wiimote, en g (quieto: la gravedad)
    raw: bytes = field(default=b"", compare=False)


REPORT, REPORT_ACCEL = 0x32, 0x35  # botones + extensión; botones + acelerómetro + extensión


def decode(ext: bytes, core: int = 0, whammy_rest: int | None = None,
           accel: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> GuitarState:
    b4, b5 = ext[4], ext[5]
    wb = ext[3] & 0x1F
    rest = whammy_rest if whammy_rest is not None else 0x10
    return GuitarState(
        frets=tuple(not (b5 >> bit & 1) for bit in _FRET_BITS),
        strum_up=not (b5 & 0x01),
        strum_down=not (b4 >> 6 & 1),
        start=not (b4 >> 2 & 1),
        select=not (b4 >> 4 & 1),
        whammy=max(0.0, min(1.0, (wb - rest) / max(1, 0x1F - rest))),
        stick=((ext[0] & 0x3F) / 31.5 - 1.0, 1.0 - (ext[1] & 0x3F) / 31.5),
        wiimote=core,
        accel=accel,
        raw=bytes(ext[:6]),
    )


class WiiGuitar:
    """Uso: g = WiiGuitar.open(); while True: s = g.poll(timeout_ms) (None si no hay datos nuevos)."""

    def __init__(self, dev: hid.device, path: bytes, accel: bool = False):
        self.dev = dev
        self.report = REPORT_ACCEL if accel else REPORT
        self.path = path
        self.extension: bytes | None = None
        self._whammy_rest: int | None = None
        self._setup_at = 0.0
        self.calib = ((128, 128, 128), (154, 154, 154))  # (cero, 1 g) por eje; open() lee los del Wiimote

    @classmethod
    def find(cls) -> list[dict]:
        return [d for d in hid.enumerate(NINTENDO) if d["product_id"] in WIIMOTE_PIDS]

    @classmethod
    def open(cls, accel: bool = False) -> WiiGuitar:
        """accel: pedir también el acelerómetro (informes 0x35: el juego lo usa para el star power)."""
        found = cls.find()
        if not found:
            raise RuntimeError(t("no hay ningún Wiimote emparejado (tools/pair_wiimote.py)"))
        dev = hid.device()
        dev.open_path(found[0]["path"])
        g = cls(dev, found[0]["path"], accel)
        g._write(0x11, 0x10)  # LED 1 encendido: deja de parpadear
        g._write(0x12, 0x00, 0x30)  # sin informes continuos mientras se lee la calibración
        cal = g._read(0x00, 0x0016, 8)
        if cal and cal[4:7] != cal[0:3]:
            g.calib = (tuple(cal[0:3]), tuple(cal[4:7]))
        g.setup_extension()
        return g

    def close(self) -> None:
        self.dev.close()

    # ---------- protocolo ----------

    def _write(self, *data: int) -> None:
        self.dev.write(bytes(data))

    def _wait(self, report: int, ack_of: int | None = None, timeout_s: float = 0.5) -> list[int] | None:
        """Espera un informe concreto, por tiempo y no por número: los informes continuos no lo tapan."""
        end = time.monotonic() + timeout_s
        while (left := end - time.monotonic()) > 0:
            r = self.dev.read(22, max(1, int(left * 1000)))
            if r and r[0] == report and (ack_of is None or r[3] == ack_of):
                return r
        return None

    def _write_register(self, addr: int, value: int) -> bool:
        payload = [value] + [0] * 15
        self._write(0x16, 0x04, addr >> 16 & 0xFF, addr >> 8 & 0xFF, addr & 0xFF, 1, *payload)
        r = self._wait(0x22, ack_of=0x16)  # confirmación: botones (2), informe confirmado, error
        return r is not None and r[4] == 0

    def _read_register(self, addr: int, size: int) -> bytes | None:
        return self._read(0x04, addr, size)

    def _read(self, space: int, addr: int, size: int) -> bytes | None:
        """space: 0x04 registros (extensión...), 0x00 memoria del Wiimote (calibración...)."""
        self._write(0x17, space, addr >> 16 & 0xFF, addr >> 8 & 0xFF, addr & 0xFF, size >> 8 & 0xFF, size & 0xFF)
        r = self._wait(0x21)  # respuesta de lectura: botones (2), tamaño/error, dirección (2), 16 de datos
        if r is None or r[3] & 0x0F:
            return None
        return bytes(r[6:6 + size])

    def setup_extension(self, tries: int = 5) -> None:
        """Recién conectado (o con poca batería) la extensión tarda en responder: se reintenta."""
        self._write(0x12, 0x00, 0x30)  # sin informes continuos mientras se configura
        ext = None
        for i in range(tries):
            if i:
                time.sleep(0.2)
            if self._write_register(0xA400F0, 0x55) and self._write_register(0xA400FB, 0x00):
                ext = self._read_register(0xA400FA, 6)
                if ext and ext != b"\xff" * 6:
                    break
        self.extension = ext
        self._whammy_rest = None
        self._setup_at = time.monotonic()
        self._write(0x12, 0x04, self.report)  # informes continuos

    @property
    def is_guitar(self) -> bool:
        return self.extension == GUITAR_ID

    def poll(self, timeout_ms: int = 10) -> GuitarState | None:
        r = self.dev.read(22, timeout_ms)
        if not r:
            return None
        if r[0] == 0x20:  # estado: se enchufó o desenchufó la extensión
            if r[3] & 0x02:
                self.setup_extension()
            else:
                self.extension = None
                self._write(0x12, 0x04, self.report)  # tras un estado el Wiimote deja de mandar datos
            return None
        if r[0] not in (REPORT, REPORT_ACCEL):
            return None
        if self.extension is not None and not self.is_guitar and time.monotonic() - self._setup_at > 2:
            self.setup_extension(tries=1)  # enchufada pero sin responder bien: otra vez cada 2 s
            return None
        if r[0] == REPORT_ACCEL:
            ext = bytes(r[6:12])
            zero, one = self.calib
            accel = tuple((r[3 + i] - zero[i]) / max(1, one[i] - zero[i]) for i in range(3))
        else:
            ext, accel = bytes(r[3:9]), (0.0, 0.0, 0.0)
        if self._whammy_rest is None:  # la palanca en reposo no da 0: se toma la primera lectura
            self._whammy_rest = ext[3] & 0x1F
        core = (r[1] & 0x9F) << 8 | r[2] & 0x9F  # los bits 5 y 6 de los botones son del acelerómetro
        return decode(ext, core, self._whammy_rest, accel)
