"""Traducción al inglés de los avisos del generador (i18n.py): texto en español tal cual sale en el código ->
inglés, con los mismos campos. tests/test_i18n.py avisa de los que faltan o sobran."""

EN: dict[str, str] = {
    # ---------- generate (consola) ----------
    "ya hecha ({folder})": "already done ({folder})",
    "letra": "lyrics",
    "separando pistas": "separating stems",
    "pistas separadas (Demucs htdemucs_6s)": "stems separated (Demucs htdemucs_6s)",
    "sin pulsos claros: rejilla fija de 120 BPM": "no clear beats: fixed 120 BPM grid",
    "{beats} pulsos, {bars} compases, ~{bpm:.0f} BPM, {sig}/4": "{beats} beats, {bars} bars, ~{bpm:.0f} BPM, {sig}/4",
    "notas: {list}": "notes: {list}",
    "chart Experto: {n} notas, energía media {energy:.2f}": "Expert chart: {n} notes, mean energy {energy:.2f}",
    "modelo {name}: {list}": "model {name}: {list}",
    "{name} ({charter}), anclas afinadas {conf:.0%}, desfase {lo:+.2f}..{hi:+.2f} s":
        "{name} ({charter}), anchors refined {conf:.0%}, offset {lo:+.2f}..{hi:+.2f} s",
    "chart humana descartada, no encaja con el audio: {sync}":
        "human chart discarded, it doesn't match the audio: {sync}",
    "chart humana: {sync}: {list}": "human chart: {sync}: {list}",
    "del modelo: {list}": "from the model: {list}",
    "chart lista; letra": "chart ready; lyrics",
    "listo: {folder}": "done: {folder}",
    "letra: error {err}": "lyrics: error {err}",
    "letra: {source}, {n} líneas": "lyrics: {source}, {n} lines",
    "dificultad desconocida: {name}": "unknown difficulty: {name}",
    "generate: hace la chart (chart.json, preview.html, letra) de cada canción en out/charts/<canción>/.":
        "generate: makes the chart (chart.json, preview.html, lyrics) of each song in out/charts/<song>/.",
    "canciones o carpetas": "songs or folders",
    "carpeta de salida (por defecto {folder})": "output folder (default {folder})",
    "exporta también notes.chart + song.ini + audio": "also export notes.chart + song.ini + audio",
    "sin GPU": "no GPU",
    "chart hecha por personas (.sng o carpeta) para sincronizar y usar":
        "human-made chart (.sng or folder) to sync and use",
    "no usar las charts humanas de la biblioteca ({file}, bajadas en out/encore/)":
        "don't use the library's human charts ({file}, downloaded to out/encore/)",
    "modelo entrenado para las 4 dificultades (por defecto {name})":
        "trained model for the 4 difficulties (default {name})",
    "sin modelo: reglas, solo Experto": "no model: rules, Expert only",
    "rehacer aunque ya esté hecha": "redo even if already done",
    "canciones a la vez (cada una en un proceso; 2 va bien en 12 GB)":
        "songs at once (each in its own process; 2 works well with 12 GB)",
    "notas/s como mucho en 2 s, p. ej. 'expert=14,hard=8,medium=5,easy=3.5'":
        "max notes/s over 2 s, e.g. 'expert=14,hard=8,medium=5,easy=3.5'",
    "saltar las canciones que duren más de esto": "skip songs longer than this",
    "borrar los stems al terminar cada canción": "delete the stems after each song",
    "sin letra sincronizada (lyrics.json)": "no synced lyrics (lyrics.json)",
    "no existe el modelo {path}": "model {path} doesn't exist",
    "aviso: no hay {path}; se usan las reglas (solo Experto)": "warning: no {path}; using the rules (Expert only)",
    "se saltan {n} de más de {mins:g} min: {list}": "skipping {n} longer than {mins:g} min: {list}",
    "no hay archivos de audio": "no audio files",
    "{n} canciones, {jobs} a la vez, modelo: {model}": "{n} songs, {jobs} at once, model: {model}",
    "ninguno (reglas)": "none (rules)",
    "Fin en {mins:.1f} min: {done} hechas, {skipped} ya estaban, {errors} con error":
        "Finished in {mins:.1f} min: {done} done, {skipped} already there, {errors} with errors",
    "ruta vacía": "empty path",
    "no existe: {path}": "doesn't exist: {path}",
    "no es un archivo de audio: {path}": "not an audio file: {path}",

    # ---------- motor ----------
    "orden desconocida: {cmd}": "unknown command: {cmd}",
    "orden que no es JSON: {line}": "command isn't JSON: {line}",
    "engine: el motor de generación que lanza la app (órdenes JSON por stdin, avisos JSON por stdout).":
        "engine: the generation engine the app launches (JSON commands on stdin, JSON events on stdout).",
    "archivo de la cola (se crea si no existe)": "queue file (created if missing)",
    "carpeta de las charts": "charts folder",
    "modelo OnsetNet; sin él (o si no existe), las reglas": "OnsetNet model; without it (or if missing), the rules",
    "guardar las pistas de Demucs (~50 MB por canción)": "keep the Demucs stems (~50 MB per song)",
    "motor: fin tras {mins:.1f} min": "engine: stopped after {mins:.1f} min",
    "el motor se cerró varias veces con esta canción": "the engine crashed several times with this song",
    "{name}: el archivo bajado no es el que debería (hash); se bajará otra vez":
        "{name}: the downloaded file isn't the expected one (hash); it will be downloaded again",
    "solo decir qué falta": "only report what's missing",
    "no hay notes.chart ni notes.mid en {folder}": "no notes.chart or notes.mid in {folder}",
    "demasiados pocos pulsos detectados para un mapa de tempo": "too few beats detected for a tempo map",

    # ---------- lyrics (consola) ----------
    "lyrics: letra sincronizada (lyrics.json) de las charts; sin nada, todas las de out/charts.":
        "lyrics: synced lyrics (lyrics.json) for the charts; with no arguments, all of out/charts.",
    "canciones, carpetas de música o de chart": "songs, music folders or chart folders",
    "rehacer aunque ya esté": "redo even if already there",
    "solo LRCLIB (sin transcribir las que no tengan)": "LRCLIB only (don't transcribe the ones it lacks)",
    "No encuentro charts para eso.": "No charts found for that.",
    "ya estaba": "already there",
    "confianza {c:.2f}": "confidence {c:.2f}",
    "{lines} líneas, {words} palabras": "{lines} lines, {words} words",
    "Fin en {mins:.1f} min: {counts}": "Finished in {mins:.1f} min: {counts}",
}
