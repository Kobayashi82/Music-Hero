# Music Hero
App para Windows 11: overlay transparente tipo Guitar Hero sobre el escritorio,
sincronizado con la canción que suena, para guitarra de plástico (PS3/Wii).
Ver ROADMAP.md para fases y criterios de terminado.

## Reglas
- Python 3.12, uv, un entorno en generator/ y otro en app/.
- El formato de chart está en shared/chart_schema.json; cualquier cambio, versión nueva.
- Tiempos siempre en milisegundos (int) desde el inicio del audio.
- Nada de dependencias en app/ que arrastren torch o tensorflow.
- Cada fase acaba con su criterio de terminado comprobado; no adelantar fases.
- Probar en Windows real: overlay, SMTC y mando no se pueden simular.
- Git: push siempre a `main` (https://github.com/Kobayashi82/Music-Hero).

## Comandos
- Scripts de la app / fase 0: `uv run --project app python tools/<script>.py`
- Scripts del generador: `uv run --project generator python tools/<script>.py`
- Generar charts: `uv run --project generator generate "<canción.mp3 o carpeta>" [--jobs 2] [--clonehero]` → `out/charts/<canción>/` (chart.json, preview.html, stems/, clonehero/). Usa `models/best.pt` (copia del mejor modelo, fuera de git; `--no-model` = reglas); salta lo ya hecho con el mismo audio, versión y modelo (`--force` lo rehace).
- Usar una chart humana (Chorus Encore .sng o carpeta): `uv run --project generator generate "<canción.mp3>" --human <chart.sng>`
- Tests (sin GPU): `uv run --project generator --with pytest --with jsonschema pytest tests`
- Música del usuario: `D:\Programas\Multimedia\Musicas` (reproductor: AIMP)
