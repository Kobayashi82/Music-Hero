"""Fase 0 - SMTC: imprime título, artista, estado y posición de lo que suena.

Uso:
    uv run --project app python tools/poc_smtc.py            # sesión actual
    uv run --project app python tools/poc_smtc.py --all      # todas las sesiones

Lee el panel multimedia de Windows (System Media Transport Controls), así que
sirve con cualquier reproductor que aparezca ahí (Spotify, navegador,
foobar2000 con su plugin, Reproductor multimedia de Windows...).

Columnas de posición:
    smtc    lo que reporta el reproductor (se actualiza poco a menudo)
    interp  smtc + tiempo transcurrido desde last_updated si está sonando
    edad    hace cuánto se actualizó el dato del reproductor

Prueba: pon una canción, pausa, salta adelante/atrás y cambia de canción;
comprueba que interp avanza suave y que los saltos se reflejan.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)

STATUS = {
    PlaybackStatus.CLOSED: "cerrado",
    PlaybackStatus.OPENED: "abierto",
    PlaybackStatus.CHANGING: "cambiando",
    PlaybackStatus.STOPPED: "parado",
    PlaybackStatus.PLAYING: "sonando",
    PlaybackStatus.PAUSED: "pausa",
}


def fmt_ms(ms: int) -> str:
    sign = "-" if ms < 0 else ""
    ms = abs(ms)
    return f"{sign}{ms // 60000}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


async def snapshot(session) -> tuple[str, str]:
    """Devuelve (clave de la pista, línea de estado)."""
    props = await session.try_get_media_properties_async()
    timeline = session.get_timeline_properties()
    playback = session.get_playback_info()

    status = playback.playback_status
    rate = playback.playback_rate or 1.0
    pos_ms = int(timeline.position.total_seconds() * 1000)
    end_ms = int(timeline.end_time.total_seconds() * 1000)
    updated = timeline.last_updated_time
    now = datetime.now(timezone.utc)
    age_ms = int((now - updated).total_seconds() * 1000) if updated.year > 1601 else -1

    interp_ms = pos_ms
    if status == PlaybackStatus.PLAYING and age_ms >= 0:
        interp_ms = pos_ms + int(age_ms * rate)

    track = f"{props.artist} - {props.title}  [{props.album_title}]"
    line = (
        f"{STATUS.get(status, status):<9} smtc {fmt_ms(pos_ms)}  interp {fmt_ms(interp_ms)}"
        f" / {fmt_ms(end_ms)}  edad {age_ms:>6} ms"
    )
    return track, line


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="muestra todas las sesiones, no solo la actual")
    parser.add_argument("--interval", type=float, default=0.25, help="segundos entre lecturas")
    args = parser.parse_args()

    manager = await SessionManager.request_async()
    sessions = list(manager.get_sessions())
    print(f"Sesiones multimedia: {len(sessions)}")
    for s in sessions:
        print(f"  - {s.source_app_user_model_id}")
    print("Ctrl+C para salir.\n")

    last_track: dict[str, str] = {}
    while True:
        if args.all:
            targets = list(manager.get_sessions())
        else:
            current = manager.get_current_session()
            targets = [current] if current else []
        if not targets:
            print("\r(nada sonando)" + " " * 60, end="", flush=True)

        for session in targets:
            app_id = session.source_app_user_model_id
            try:
                track, line = await snapshot(session)
            except OSError as e:
                print(f"\n{app_id}: error leyendo la sesión: {e}")
                continue
            if last_track.get(app_id) != track:
                last_track[app_id] = track
                print(f"\n== {app_id}\n   {track}")
            prefix = f"   [{app_id[:20]}] " if args.all else "   "
            end = "\n" if args.all else ""
            print(f"\r{prefix}{line}", end=end, flush=True)
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print()
