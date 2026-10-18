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

    # ---------- vista previa (preview.html) ----------
    "notas": "notes",
    "acordes": "chords",
    "dificultad": "difficulty",
    "Autopista": "Highway",
    "Línea temporal": "Timeline",
    "Clic en notas": "Click on notes",
    "segundos visibles": "visible seconds",
    "guitarra": "guitar",
    "otros": "other",
    "voz": "vocals",
    "bajo": "bass",
    "Experto": "Expert",
    "Difícil": "Hard",
    "Medio": "Medium",
    "Fácil": "Easy",
    "máx": "max",
    "energía": "energy",
    "fuente:": "source:",
    "contorno elegido": "chosen contour",
    "espacio play · ← → ±5 s · V vista · C clics · clic para saltar":
        "space play · ← → ±5 s · V view · C clicks · click to jump",
    "Pausa": "Pause",

    # ---------- entrenamiento (learn/) ----------
    "fallo {name}: {err}": "failed {name}: {err}",
    "{done} preparadas ({failed} descartadas), {secs:.1f} s/canción":
        "{done} prepared ({failed} discarded), {secs:.1f} s/song",
    "Fin: {done} procesadas, {failed} descartadas": "Done: {done} processed, {failed} discarded",
    "{name} necesita la pista de guitarra (stems/guitar.flac)": "{name} needs the guitar stem (stems/guitar.flac)",
    "pocas notas con el umbral {old}, bajado a {new} ({n} notas)":
        "too few notes at threshold {old}, lowered to {new} ({n} notes)",
    "pesos iniciales de {name}": "initial weights from {name}",
    "aprender también los botones de cada nota": "also learn the frets of each note",
    "empezar desde los pesos de otro modelo (p. ej. models/onset_v3.pt)":
        "start from another model's weights (e.g. models/onset_v3.pt)",
    "entrada con la pista de guitarra y su CQT (datos de learn.data --guitar)":
        "input with the guitar stem and its CQT (data from learn.data --guitar)",
    "{train} canciones de entrenamiento ({harmonix:.0f} de Harmonix), {val} de validación ({excluded} de la "
    "biblioteca excluidas)":
        "{train} training songs ({harmonix:.0f} from Harmonix), {val} for validation ({excluded} from the library "
        "excluded)",
    "paso {step}: 50 lotes seguidos con NaN, se para (el mejor modelo ya está en {out})":
        "step {step}: 50 batches in a row with NaN, stopping (the best model is already in {out})",
    "{n} lotes saltados por NaN": "{n} batches skipped due to NaN",
    "paso {step}: pérdida {loss:.4f} ({secs:.2f} s/paso{extra})": "step {step}: loss {loss:.4f} ({secs:.2f} s/step{extra})",
    "validación:": "validation:",
    "umbral {th}": "threshold {th}",
    "botones:": "frets:",
    "exactos {exact:.0%} dirección {dir:.0%} acordes {pred:.0%}/{ref:.0%}":
        "exact {exact:.0%} direction {dir:.0%} chords {pred:.0%}/{ref:.0%}",
    "guardado (puntuación {score:.3f}) -> {out}": "saved (score {score:.3f}) -> {out}",

    # ---------- dataset y exámenes (tools/) ----------
    "página {page}, {got}/{quota} (total {total})": "page {page}, {got}/{quota} (total {total})",
    "Catálogo: {n} charts -> {dest}": "Catalog: {n} charts -> {dest}",
    "Tope de {gb:.0f} GB alcanzado.": "{gb:.0f} GB limit reached.",
    "{done} bajadas, {failed} fallos, {gb:.1f} GB ({rate:.1f} MB/s)":
        "{done} downloaded, {failed} failed, {gb:.1f} GB ({rate:.1f} MB/s)",
    "Fin: {done} bajadas, {failed} fallos, {gb:.1f} GB en {dest}":
        "Done: {done} downloaded, {failed} failed, {gb:.1f} GB in {dest}",
    "{n} con chart": "{n} with a chart",
    "{found}/{total} canciones de la biblioteca con chart humana -> {dest}":
        "{found}/{total} library songs with a human chart -> {dest}",
    "reintento en {s} s ({err})": "retrying in {s} s ({err})",
    "Encore no responde: {path}": "Encore isn't responding: {path}",
    "{n} canciones": "{n} songs",
    "nota a nota": "note by note",
    "exactos {ex:5.1%}  dirección {dir:5.1%}  sube/baja {mv:5.1%}  acordes {cp:5.1%} (humanas {cr:.1%})  repite "
    "{rp:5.1%} (humanas {rr:.1%})":
        "exact {ex:5.1%}  direction {dir:5.1%}  up/down {mv:5.1%}  chords {cp:5.1%} (human {cr:.1%})  repeats "
        "{rp:5.1%} (human {rr:.1%})",
    "{n} canciones; umbrales del modelo {th}": "{n} songs; model thresholds {th}",
    "comunidad": "community",
    "{name} ({n} canciones):": "{name} ({n} songs):",
    "botones: exactos {exact:.0%}, dirección {dir:.0%}, acordes {pred:.0%} (humanas {ref:.0%})":
        "frets: exact {exact:.0%}, direction {dir:.0%}, chords {pred:.0%} (human {ref:.0%})",
    "(precisión {p:.2f}, recall {r:.2f})": "(precision {p:.2f}, recall {r:.2f})",
    "Experto por canción (notas del modelo / humanas):": "Expert per song (model notes / human):",
    "mediana por canción: {m:.3f}": "median per song: {m:.3f}",
    "referencia humana ({diff}): {n} notas, {nps:.2f}/s, acordes {ch:.0%}":
        "human reference ({diff}): {n} notes, {nps:.2f}/s, chords {ch:.0%}",
    "candidata": "candidate",
    "precis.": "precis.",
    "dirección": "direction",
    "(desfase {ms} ms)": "(offset {ms} ms)",
}
