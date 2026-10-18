# Music Hero
App para Windows 11: overlay transparente tipo Guitar Hero sobre el escritorio,
sincronizado con la canción que suena, para guitarra de plástico (PS3/Wii).
Ver ROADMAP.md para fases y criterios de terminado.

## Reglas
- Python 3.12, uv, un entorno en generator/ y otro en app/.
- El formato de chart está en shared/chart_schema.json; cualquier cambio, versión nueva.
- Tiempos siempre en milisegundos (int) desde el inicio del audio.
- Nada de dependencias en app/ que arrastren torch o tensorflow.
- Español e inglés: todo texto que vea el usuario (pantalla, consola, logs, errores) va con `t("texto en español", campo=...)` (o `N_()` en constantes, `bridge.tr()` en QML) y su traducción en `lang_en.py` (app/src/app/ y generator/src/generator/); los tests de i18n avisan si falta. El idioma: Ajustes → Idioma (auto = el de Windows); la app se lo pasa al motor con MUSICHERO_LANG. Las herramientas de entrenamiento (learn/, tools/) quedan en español.
- Cada fase acaba con su criterio de terminado comprobado; no adelantar fases.
- Probar en Windows real: overlay, SMTC y mando no se pueden simular.
- Git: push siempre a `main` (https://github.com/Kobayashi82/Music-Hero).

## Comandos
- Scripts de la app / fase 0: `uv run --project app python tools/<script>.py`
- Scripts del generador: `uv run --project generator python tools/<script>.py`
- Generar charts: `uv run --project generator generate "<canción.mp3 o carpeta>" [--jobs 2] [--clonehero]` → `out/charts/<canción>/` (chart.json, preview.html, stems/, clonehero/). Usa `models/best.pt` (copia del mejor modelo, fuera de git; `--no-model` = reglas); salta lo ya hecho con el mismo audio, versión y modelo (`--force` lo rehace).
- Charts humanas de la biblioteca: `generate` usa sola la de `data/encore_library.json` si está bajada en `out/encore/` y encaja con el audio (si no, el modelo; `--no-human` lo desactiva).
- Letra sincronizada (lyrics.json junto a chart.json, shared/lyrics_schema.json): la hace `generate` (salvo `--no-lyrics`), o aparte `uv run --project generator lyrics ["<carpeta de chart o canción>"] [--force]` (sin nada: todas las de out/charts). Texto de LRCLIB, tiempos de stable-ts sobre stems/vocals.flac.
- Usar una chart humana (Chorus Encore .sng o carpeta): `uv run --project generator generate "<canción.mp3>" --human <chart.sng>`
- Jugar (fase 3, reproductor propio): `uv run --project app play` (selector de canciones) o `play "<canción.mp3 o carpeta de chart>" [--difficulty hard]`. Star power: levantar la guitarra o E. Récords, dificultad por canción, índice y config en `%APPDATA%/MusicHero/`. Tests de la app: `uv run --project app --with pytest pytest app/tests`
- Jugar sobre AIMP (fase 4): `uv run --project app play --hidden` y, con una canción sonando en AIMP, Ctrl+Alt+H; también `play` sin canción si AIMP está sonando. Mide solo el retardo de AIMP por loopback (`tools/measure_aimp_latency.py` aparte).
- Tests (sin GPU): `uv run --project generator --with pytest --with jsonschema pytest tests`
- Motor (fase 7, lo lanza la app): `uv run --project generator engine --queue <cola.json> --out <charts>` (órdenes JSON por stdin, avisos JSON por stdout; ver generator/engine.py). Modelos del motor instalado: `python -m generator.fetch_models`.
- App instalable: `uv run --project app --with pyinstaller python packaging/build.py` → build/dist/Music Hero/ y, con Inno Setup, build/installer/MusicHero-Setup-*.exe (lleva models/best.pt como OnsetNet: reconstruir si cambia el modelo).
- Probar como instalación nueva sin tocar lo de verdad: `MUSICHERO_HOME=<carpeta> APPDATA=<carpeta> uv run --project app play` (charts, cola y log del motor en MUSICHERO_HOME; config en APPDATA/MusicHero).
- Modelo v5 (guitarra + CQT, para los botones): `sh tools/night_v5.sh` prepara, examina y entrena de noche (~6-7 h, GPU; solo cuando el usuario lo diga). Logs en `out/dataset/night_v5_*.log`; no toca out/charts ni models/best.pt. Copia de las charts v4 en `out/charts_backup_v4`. Al acabar: comparar los exámenes v5 y v4 y, si gana v5, copiarlo a models/best.pt y regenerar con `--force`.
- Música del usuario: `D:\Programas\Multimedia\Musicas` (reproductor: AIMP)
