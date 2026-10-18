"""Emparejar un Wiimote (con la guitarra) con Windows sin escribir PIN: Windows 11 lo pide y no se puede teclear.

El PIN de un Wiimote emparejado con el botón rojo de sync es la dirección Bluetooth del PC, byte a byte
(6 bytes, no son letras): se le pasa a Windows por la API, como hacen Dolphin y WiitarThing. Si ya había un
"Nintendo RVL-CNT-01" a medias (pedía PIN), se borra y se empareja de nuevo.

Lo usan Ajustes → «Emparejar la guitarra de Wii» (en un hilo, con los avisos en el menú) y
tools/pair_wiimote.py.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

bt = ctypes.WinDLL("bthprops.cpl")  # BluetoothApis.dll no tiene BluetoothAuthenticateDevice


class BLUETOOTH_ADDRESS(ctypes.Union):
    _fields_ = [("ullLong", ctypes.c_ulonglong), ("rgBytes", ctypes.c_ubyte * 6)]


class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


class BLUETOOTH_RADIO_INFO(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("address", BLUETOOTH_ADDRESS), ("szName", wintypes.WCHAR * 248),
                ("ulClassofDevice", wintypes.ULONG), ("lmpSubversion", wintypes.USHORT),
                ("manufacturer", wintypes.USHORT)]


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute",
                                              "wSecond", "wMilliseconds")]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("Address", BLUETOOTH_ADDRESS), ("ulClassofDevice", wintypes.ULONG),
                ("fConnected", wintypes.BOOL), ("fRemembered", wintypes.BOOL), ("fAuthenticated", wintypes.BOOL),
                ("stLastSeen", SYSTEMTIME), ("stLastUsed", SYSTEMTIME), ("szName", wintypes.WCHAR * 248)]


class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("fReturnAuthenticated", wintypes.BOOL),
                ("fReturnRemembered", wintypes.BOOL), ("fReturnUnknown", wintypes.BOOL),
                ("fReturnConnected", wintypes.BOOL), ("fIssueInquiry", wintypes.BOOL),
                ("cTimeoutMultiplier", ctypes.c_ubyte), ("hRadio", wintypes.HANDLE)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


HID_SERVICE = GUID(0x00001124, 0x0000, 0x1000, (ctypes.c_ubyte * 8)(0x80, 0x00, 0x00, 0x80, 0x5F, 0x9B, 0x34, 0xFB))
BLUETOOTH_SERVICE_ENABLE = 1

bt.BluetoothFindFirstRadio.restype = wintypes.HANDLE
bt.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(BLUETOOTH_FIND_RADIO_PARAMS), ctypes.POINTER(wintypes.HANDLE)]
bt.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
bt.BluetoothGetRadioInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_RADIO_INFO)]
bt.BluetoothFindFirstDevice.restype = wintypes.HANDLE
bt.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(BLUETOOTH_DEVICE_SEARCH_PARAMS), ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
bt.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
bt.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
bt.BluetoothRemoveDevice.argtypes = [ctypes.POINTER(BLUETOOTH_ADDRESS)]
bt.BluetoothAuthenticateDevice.argtypes = [wintypes.HWND, wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO),
                                           wintypes.LPWSTR, wintypes.ULONG]
bt.BluetoothSetServiceState.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO), ctypes.POINTER(GUID),
                                        wintypes.DWORD]


def addr_str(a: BLUETOOTH_ADDRESS) -> str:
    return ":".join(f"{b:02X}" for b in reversed(a.rgBytes))


def find_radio() -> tuple[wintypes.HANDLE, BLUETOOTH_RADIO_INFO]:
    params = BLUETOOTH_FIND_RADIO_PARAMS(ctypes.sizeof(BLUETOOTH_FIND_RADIO_PARAMS))
    radio = wintypes.HANDLE()
    h = bt.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if not h:
        raise RuntimeError("No hay adaptador Bluetooth (o está apagado).")
    bt.BluetoothFindRadioClose(h)
    info = BLUETOOTH_RADIO_INFO()
    info.dwSize = ctypes.sizeof(BLUETOOTH_RADIO_INFO)
    if bt.BluetoothGetRadioInfo(radio, ctypes.byref(info)) != 0:
        raise RuntimeError("No se pudo leer el adaptador Bluetooth.")
    return radio, info


def devices(radio, inquiry: bool) -> list[BLUETOOTH_DEVICE_INFO]:
    sp = BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS), True, True, True, True,
                                        inquiry, 2 if inquiry else 0, radio)  # 2 x 1,28 s de búsqueda
    out = []
    info = BLUETOOTH_DEVICE_INFO()
    info.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)
    h = bt.BluetoothFindFirstDevice(ctypes.byref(sp), ctypes.byref(info))
    if not h:
        return out
    while True:
        out.append(info)
        info = BLUETOOTH_DEVICE_INFO()
        info.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)
        if not bt.BluetoothFindNextDevice(h, ctypes.byref(info)):
            break
    bt.BluetoothFindDeviceClose(h)
    return out


def is_wiimote(d: BLUETOOTH_DEVICE_INFO) -> bool:
    return d.szName.startswith("Nintendo RVL-")


def pair(say: Callable[[str], None], stop: threading.Event | None = None, timeout_s: float = 120) -> bool:
    """Busca el Wiimote (hay que pulsar su botón rojo de sync) y lo empareja. say(texto): cada aviso.
    stop: para cancelar. True si queda emparejado (o ya lo estaba)."""
    stop = stop or threading.Event()
    try:
        radio, info = find_radio()
    except RuntimeError as e:
        say(str(e))
        return False
    for d in devices(radio, inquiry=False):  # restos de intentos con PIN: impiden volver a encontrarlo
        if is_wiimote(d) and not d.fConnected:
            say(f"Borrando el emparejamiento anterior de {d.szName}")
            bt.BluetoothRemoveDevice(ctypes.byref(d.Address))

    # PIN = dirección del PC, cada byte en un WCHAR (orden de rgBytes, el byte menos significativo primero)
    pin = ctypes.create_unicode_buffer("".join(chr(b) for b in info.address.rgBytes), 7)
    say("Pulsa el botón rojo de sync del Wiimote (bajo la tapa de las pilas). Buscando…")
    t0 = time.time()
    while time.time() - t0 < timeout_s and not stop.is_set():
        for d in devices(radio, inquiry=True):
            if not is_wiimote(d):
                continue
            if d.fConnected and d.fAuthenticated:
                say(f"{d.szName} ya está emparejado y conectado.")
                return True
            if d.fRemembered:
                bt.BluetoothRemoveDevice(ctypes.byref(d.Address))
            say(f"Encontrado {d.szName}, emparejando…")
            r = bt.BluetoothAuthenticateDevice(None, radio, ctypes.byref(d), pin, 6)
            if r != 0:
                say(f"Falló la autenticación (error {r}): vuelve a pulsar el botón rojo")
                continue
            r = bt.BluetoothSetServiceState(radio, ctypes.byref(d), ctypes.byref(HID_SERVICE), BLUETOOTH_SERVICE_ENABLE)
            if r != 0:
                say(f"Emparejado, pero no se pudo activar como mando (error {r})")
                continue
            say("¡Emparejado! Windows tarda unos segundos en instalarlo; luego la guitarra se conecta sola.")
            return True
        if not stop.is_set():
            say(f"Buscando… {int(time.time() - t0)} s (si el Wiimote dejó de parpadear, pulsa otra vez el botón rojo)")
    say("Cancelado." if stop.is_set() else "No se encontró ningún Wiimote. ¿Bluetooth activado? ¿Pilas?")
    return False
