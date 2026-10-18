"""Traducción al inglés (i18n.py): texto en español tal cual sale en el código -> inglés, con los mismos campos
({name}, %1...). app/tests/test_i18n.py avisa de los que faltan o sobran."""

EN: dict[str, str] = {
    # ---------- QML ----------
    "Calibrar el retardo": "Calibrate latency",
    "Automático": "Auto",
    "¡Récord! (%1)": "High score! (%1)",
    "Récord %1": "Best %1",
    "¡Star power!": "Star power!",
    "Star power: levanta la guitarra": "Star power: tilt the guitar up",
    "%1 seguidas": "%1 in a row",
    "1 seguida": "1 in a row",
    "Strum: cambiar · Verde / + o Rojo / −: listo": "Strum: change · Green / + or Red / −: done",
    "Rasguea justo cuando cada nota amarilla llegue a la línea: suena un clic al pasar. Los 4 clics agudos del "
    "principio solo marcan el ritmo. No hace falta pulsar trastes.":
        "Strum right when each yellow note reaches the line: you'll hear a click as it passes. The 4 high clicks "
        "at the start only count you in. No need to hold any frets.",
    "Rojo / −: cancelar": "Red / −: cancel",
    "Notas:": "Notes:",

    # ---------- dificultades, posiciones ----------
    "Experto": "Expert",
    "Difícil": "Hard",
    "Medio": "Medium",
    "Fácil": "Easy",
    "Centro": "Center",
    "Izquierda": "Left",
    "Derecha": "Right",

    # ---------- motor ----------
    "no se puede lanzar el motor (falta uv, o no está instalado)":
        "can't start the engine (uv is missing, or it isn't installed)",
    "no se pudo lanzar el motor: {err}": "couldn't start the engine: {err}",
    "el motor se cerró (código {code}); detalles en {log}": "the engine stopped (code {code}); details in {log}",
    "Motor listo": "Engine ready",
    "Preparando el motor": "Preparing the engine",
    "driver NVIDIA: {drv}; variante: {variant}": "NVIDIA driver: {drv}; variant: {variant}",
    "Descargando el motor (Python, torch...)": "Downloading the engine (Python, torch...)",
    "Descargando los modelos": "Downloading the models",
    "Descargando {name} ({done} de {total} MB)": "Downloading {name} ({done} of {total} MB)",
    "{prog} terminó con error {code} (ver {log})": "{prog} failed with error {code} (see {log})",
    "Descargando": "Downloading",
    "Descargado": "Downloaded",
    "Instalado": "Installed",
    "Preparado": "Prepared",
    "Resuelto": "Resolved",

    # ---------- teclas y mando ----------
    "No se pudo usar {key} para «{name}»: la usa otra aplicación":
        "Couldn't use {key} for “{name}”: another application is using it",
    "Traste verde": "Green fret",
    "Traste rojo": "Red fret",
    "Traste amarillo": "Yellow fret",
    "Traste azul": "Blue fret",
    "Traste naranja": "Orange fret",
    "Strum arriba": "Strum up",
    "Strum abajo": "Strum down",
    "Menú (pausa)": "Menu (pause)",
    "Volver / pausa": "Back / pause",
    "Reiniciar la canción": "Restart the song",
    "Cambiar de dificultad": "Change difficulty",
    "Star power": "Star power",
    "Elegir": "Select",
    "Mostrar / ocultar": "Show / hide",
    "tecla no reconocida: {key!r}": "unknown key: {key!r}",
    "falta la tecla en {text!r}": "no key in {text!r}",
    "Flecha arriba": "Up arrow",
    "Flecha abajo": "Down arrow",
    "Flecha izquierda": "Left arrow",
    "Flecha derecha": "Right arrow",
    "Intro": "Enter",
    "Espacio": "Space",
    "Pausa": "Pause",
    "Retroceso": "Backspace",
    "Bloq Despl": "Scroll Lock",
    "Inicio": "Home",
    "Fin": "End",
    "Re Pág": "Page Up",
    "Av Pág": "Page Down",
    "Supr": "Delete",
    "Bloq Mayús": "Caps Lock",
    "Play/Pausa": "Play/Pause",
    "Pista siguiente": "Next track",
    "Pista anterior": "Previous track",
    "Silencio": "Mute",
    "Bajar volumen": "Volume down",
    "Subir volumen": "Volume up",
    "Mayús": "Shift",
    "no hay ningún Wiimote emparejado (tools/pair_wiimote.py)": "no Wiimote is paired (tools/pair_wiimote.py)",

    # ---------- emparejar ----------
    "Borrando el emparejamiento anterior de {name}": "Removing the old pairing of {name}",
    "Ya estaba emparejada: si pulsas cualquier botón del Wiimote se conecta sola. Para emparejarla de nuevo, "
    "pulsa el botón rojo de sync (bajo la tapa de las pilas). Buscando…":
        "Already paired: press any button on the Wiimote and it connects by itself. To pair it again, press the "
        "red sync button (under the battery cover). Searching…",
    "Pulsa el botón rojo de sync del Wiimote (bajo la tapa de las pilas). Buscando…":
        "Press the red sync button on the Wiimote (under the battery cover). Searching…",
    "{name} ya está emparejado y conectado.": "{name} is already paired and connected.",
    "Encontrado {name}, emparejando…": "Found {name}, pairing…",
    "Falló la autenticación (error {r}): vuelve a pulsar el botón rojo":
        "Authentication failed (error {r}): press the red button again",
    "Emparejado, pero no se pudo activar como mando (error {r})":
        "Paired, but it couldn't be enabled as a controller (error {r})",
    "¡Emparejado! Windows tarda unos segundos en instalarlo; luego la guitarra se conecta sola.":
        "Paired! Windows takes a few seconds to set it up; then the guitar connects by itself.",
    "Buscando… {s} s (si el Wiimote dejó de parpadear, pulsa otra vez el botón rojo)":
        "Searching… {s} s (if the Wiimote stopped blinking, press the red button again)",
    "Cancelado.": "Cancelled.",
    "No se encontró ningún Wiimote. ¿Bluetooth activado? ¿Pilas?": "No Wiimote found. Is Bluetooth on? Batteries?",
    "No hay adaptador Bluetooth (o está apagado).": "No Bluetooth adapter (or it's turned off).",
    "No se pudo leer el adaptador Bluetooth.": "Couldn't read the Bluetooth adapter.",
    "Emparejar la guitarra": "Pair the guitar",
    "Con la guitarra enchufada al Wiimote, pulsa el botón rojo de sync del Wiimote (bajo la tapa de las pilas).":
        "With the guitar plugged into the Wiimote, press the red sync button on the Wiimote (under the battery "
        "cover).",
    "Emparejar la guitarra de Wii": "Pair the Wii guitar",
    "conectada": "connected",
    "Guitarra conectada": "Guitar connected",
    "Sin guitarra: enciende el Wiimote y se conecta sola (o juega con el teclado)":
        "No guitar: turn on the Wiimote and it connects by itself (or play with the keyboard)",

    # ---------- biblioteca ----------
    "(sin álbum)": "(no album)",
    "(sin artista)": "(no artist)",
    "Biblioteca": "Library",
    "Biblioteca: {line}": "Library: {line}",
    "Añadir carpeta": "Add folder",
    "carpeta": "folder",
    "Generar en segundo plano": "Generate in the background",
    "Instalar el motor": "Install the engine",
    "Reintentar las que fallaron": "Retry the failed ones",
    "{dirs} carpetas · {total} canciones · {done} con chart": "{dirs} folders · {total} songs · {done} with a chart",
    "Añade la carpeta donde tienes tu música.": "Add the folder where your music is.",
    "Ahora: {line}": "Now: {line}",
    "{n} no se pudieron generar (detalles en {log})": "{n} couldn't be generated (details in {log})",
    "Sin tarjeta NVIDIA: cada canción tarda varios minutos": "No NVIDIA card: each song takes several minutes",
    "La instalación del motor falló: {err} (se puede repetir)": "Engine installation failed: {err} (you can retry)",
    "Quitar de la biblioteca": "Remove from the library",
    "Al quitarla no se borra nada: las charts hechas se quedan, pero deja de buscar canciones nuevas ahí.":
        "Removing it doesn't delete anything: the charts already made stay, but it stops looking for new songs "
        "there.",
    "Carpeta de tu música": "Your music folder",
    "Esa carpeta ya está en la biblioteca": "That folder is already in the library",
    "Buscando canciones en {folder}…": "Looking for songs in {folder}…",
    "Añadir la carpeta de tu música": "Add your music folder",
    "instalando el motor ({pct} %): {step}": "installing the engine ({pct} %): {step}",
    "falta instalar el motor de generación": "the generation engine isn't installed yet",
    "en pausa mientras juegas": "paused while you play",
    "generando «{name}» ({pct} %)": "generating “{name}” ({pct} %)",
    "{n} más en cola": "{n} more queued",
    "{n} en cola": "{n} queued",
    "{n} sin chart (generar en segundo plano: no)": "{n} without a chart (generate in the background: off)",
    "al día": "up to date",
    "sin carpetas de música (Ajustes → Biblioteca)": "no music folders (Settings → Library)",
    "generando": "generating",
    "falló": "failed",
    "en cola": "queued",
    "sin chart": "no chart",
    "generando {pct} %": "generating {pct} %",

    # ---------- generar charts ----------
    "Motor de generación instalado: empiezan las charts": "Generation engine installed: charts are starting",
    "No se pudo instalar el motor: {err}": "Couldn't install the engine: {err}",
    "Generando la chart de «{name}»: {pct} %": "Generating the chart for “{name}”: {pct} %",
    "No se puede generar la chart: no se encuentra el motor (¿falta uv?)":
        "Can't generate the chart: the engine wasn't found (is uv missing?)",
    "Generando la chart de «{title}»… (en torno a 1 min con GPU)":
        "Generating the chart for “{title}”… (about 1 min with a GPU)",
    "¡Ya hay canciones para jugar!": "Songs are ready to play!",
    "No se pudo generar la chart de «{name}»: {err}": "Couldn't generate the chart for “{name}”: {err}",
    "«{name}» no tiene chart: falló al generarla": "“{name}” has no chart: generating it failed",
    "Instalando el motor: {step}": "Installing the engine: {step}",
    "Instalando el motor de generación: puedes seguir jugando mientras":
        "Installing the generation engine: you can keep playing meanwhile",
    "Para hacer las charts, Music Hero necesita su motor de generación (separar instrumentos, ritmo, notas y "
    "letra). Se descarga una sola vez: unos {size} GB a %LOCALAPPDATA%\\MusicHero.":
        "To make charts, Music Hero needs its generation engine (instrument separation, rhythm, notes and "
        "lyrics). It's downloaded once: about {size} GB to %LOCALAPPDATA%\\MusicHero.",
    "Tienes una tarjeta NVIDIA: cada canción tardará un minuto más o menos.":
        "You have an NVIDIA card: each song will take about a minute.",
    "Sin tarjeta NVIDIA (o con el driver antiguo) cada canción tardará varios minutos.":
        "Without an NVIDIA card (or with an old driver) each song will take several minutes.",
    "Con el driver de NVIDIA al día iría mucho más rápido.": "With an up-to-date NVIDIA driver it would be much faster.",
    "Instalar ahora": "Install now",
    "Más tarde": "Later",
    "Generar la chart": "Generate the chart",

    # ---------- AIMP ----------
    "AIMP: canción al azar": "AIMP: random song",
    "AIMP: siguiente": "AIMP: next",
    "AIMP: anterior": "AIMP: previous",
    "AIMP no tiene ninguna canción puesta": "AIMP has no song loaded",
    "AIMP se ha cerrado: vuelve el reproductor propio": "AIMP was closed: back to the built-in player",
    "medida del retardo de AIMP: {err}": "AIMP latency measurement: {err}",
    "retardo de AIMP: {lag:+.0f} ms": "AIMP latency: {lag:+.0f} ms",
    "retardo de AIMP: no se pudo medir": "AIMP latency: couldn't be measured",
    "la posición está fuera de la canción": "the position is outside the song",
    "retardo {lag:+.0f} ms (correlación {q:.2f})": "latency {lag:+.0f} ms (correlation {q:.2f})",
    "chart de {file}: {err}": "chart for {file}: {err}",
    "«{title}» no tiene chart todavía (generándola…)": "“{title}” has no chart yet (generating it…)",
    "«{title}» no tiene chart todavía: + / Espacio para generarla": "“{title}” has no chart yet: + / Space to generate it",
    "Seguir a AIMP": "Follow AIMP",

    # ---------- menús ----------
    "página {page} de {pages}": "page {page} of {pages}",
    "Strum: letra · Verde / +: añadirla · Rojo / −: listo": "Strum: letter · Green / +: add it · Red / −: done",
    "Buscar:": "Search:",
    "Escribe con el teclado, o con la guitarra en «Escribir».": "Type on the keyboard, or with the guitar in “Type”.",
    "nada": "nothing",
    "1 canción": "1 song",
    "espacio": "space",
    "Escribir": "Type",
    "Borrar letra": "Delete letter",
    "Strum: mover · Verde / +: elegir · Rojo / −: volver": "Strum: move · Green / +: select · Red / −: back",
    "Strum: mover · Verde / +: elegir · Rojo / −: volver · Amarillo / Azul: pasar página":
        "Strum: move · Green / +: select · Red / −: back · Yellow / Blue: change page",
    "Para jugar, Music Hero necesita tu música: elige la carpeta donde la tienes y hará las charts (notas y letra) "
    "en segundo plano, primero la canción que elijas.":
        "To play, Music Hero needs your music: choose the folder where it is and it will make the charts (notes "
        "and lyrics) in the background, starting with the song you pick.",
    "Elegir canción": "Choose a song",
    "Dificultad": "Difficulty",
    "Dificultad: {name}": "Difficulty: {name}",
    "Modo automático": "Autoplay",
    "Sí": "On",
    "No": "Off",
    "Todavía no hay canciones: añade la carpeta de tu música": "No songs yet: add your music folder",
    "Buscando canciones…": "Looking for songs…",
    "{n} canciones de {artists} artistas": "{n} songs by {artists} artists",
    "({n} aún sin chart: elige una y se hace la primera)": "({n} without a chart yet: pick one and it goes first)",
    "Canciones": "Songs",
    "Buscar": "Search",
    "Al azar": "Random",
    "{n} álbumes": "{n} albums",
    "{n} canciones": "{n} songs",
    "Cargando {title}…": "Loading {title}…",
    "No se pudo abrir {title}: {err}": "Couldn't open {title}: {err}",
    "Continuar": "Resume",
    "Cambiar canción": "Change song",
    "Reiniciar": "Restart",
    "Salir": "Quit",
    "Ocultar": "Hide",
    "Todavía no hay canciones. Biblioteca: {line}": "No songs yet. Library: {line}",
    "Fin de la canción": "Song complete",
    "Otra vez": "Play again",
    "Otra canción": "Another song",
    "Canción al azar": "Random song",
    "Buscar canción": "Search for a song",
    "Ajustes": "Settings",
    "Guitarra y teclas": "Guitar and keys",
    "Juego": "Gameplay",
    "Pantalla": "Display",
    "Sonido y retardo": "Sound and latency",
    "Idioma": "Language",
    "Abrir al iniciar Windows": "Open when Windows starts",
    "Elige una opción para cambiarla con el strum; se guarda sola.":
        "Select an option to change it with the strum bar; it saves automatically.",
    "Dificultad por defecto": "Default difficulty",
    "Velocidad de las notas": "Note speed",
    "Letra": "Lyrics",
    "Opacidad del fondo": "Background opacity",
    "Ancho de la autopista": "Highway width",
    "Posición": "Position",
    "Marcador": "Scoreboard",
    "Volumen": "Volume",
    "Retardo del audio": "Audio latency",
    "Retardo de AIMP": "AIMP latency",
    "Retardo de la imagen": "Video latency",
    "Audio: lo que tardan en sonar tus altavoces (lo mide «Calibrar el retardo»).<br>AIMP: lo que tarda AIMP en "
    "hacer sonar su posición (se mide solo al seguirlo).<br>Imagen: lo que tarda la pantalla en enseñar las notas.":
        "Audio: how long your speakers take to play sound (measured by “Calibrate latency”).<br>AIMP: how long "
        "AIMP takes to play its position (measured automatically while following it).<br>Video: how long the "
        "screen takes to show the notes.",
    "Teclas": "Keys",
    "Teclas de siempre": "Default keys",
    "Restablecer las de siempre": "Reset to defaults",
    "Pulsa la tecla (con Ctrl, Alt o Win) para <b>{name}</b>.": "Press the key (with Ctrl, Alt or Win) for <b>{name}</b>.",
    "Pulsa la tecla para <b>{name}</b>.": "Press the key for <b>{name}</b>.",
    "Esc o rojo: cancelar": "Esc or red: cancel",
    "Elige una acción y pulsa la tecla nueva; si otra la usaba, se intercambian.<br>Mostrar / ocultar y Salir "
    "funcionan siempre, también con el juego oculto.":
        "Select an action and press the new key; if another action used it, they swap.<br>Show / hide and Quit "
        "always work, even with the game hidden.",
    "«{name}» funciona en todas partes: usa Ctrl, Alt o Win con la tecla (si no, esa tecla dejaría de escribir en "
    "las demás aplicaciones)":
        "“{name}” works everywhere: use Ctrl, Alt or Win with the key (otherwise that key would stop typing in "
        "other applications)",

    # ---------- calibración ----------
    "Calibración": "Calibration",
    "Repetir": "Try again",
    "Volver": "Back",
    "Pocos rasgueos a tiempo con los clics (hacen falta {n}). Prueba otra vez.":
        "Too few strums in time with the clicks ({n} needed). Try again.",
    "Rasgueas de media {ms:.0f} ms tarde ({n} rasgueos, ±{spread:.0f} ms).":
        "On average you strum {ms:.0f} ms late ({n} strums, ±{spread:.0f} ms).",
    "Rasgueas de media {ms:.0f} ms pronto ({n} rasgueos, ±{spread:.0f} ms).":
        "On average you strum {ms:.0f} ms early ({n} strums, ±{spread:.0f} ms).",
    "Retardo del audio: {old:+.0f} → <b>{new:+.0f} ms</b>": "Audio latency: {old:+.0f} → <b>{new:+.0f} ms</b>",
    "Ha salido bastante irregular: mejor repetirlo.": "That was quite uneven: better try again.",
    "Retardo del audio: {new:+.0f} ms": "Audio latency: {new:+.0f} ms",
    "Guardar": "Save",
    "Descartar": "Discard",

    # ---------- partida y récords ----------
    "Star power listo: levanta la guitarra (o {key})": "Star power ready: tilt the guitar up (or {key})",
    "No cuenta para récords (modo automático o empezada a mitad)":
        "Doesn't count for high scores (autoplay or started midway)",
    "Primera partida en {name}": "First game on {name}",
    "¡Primer récord!": "First high score!",
    "¡Nuevo récord!": "New high score!",
    "(+{diff}; antes {old})": "(+{diff}; was {old})",
    "{name}: {hits}/{total} notas ({acc:.0%})": "{name}: {hits}/{total} notes ({acc:.0%})",
    "¡sin fallos!": "full combo!",
    "Puntos: {score}": "Score: {score}",
    "Mejor racha: {streak} · Strums de más: {over}": "Best streak: {streak} · Overstrums: {over}",
    "Star power: {n}/{total} frases": "Star power: {n}/{total} phrases",
    "Tus strums van justo a tiempo": "Your strums are right on time",
    "Tus strums van de media {ms:.0f} ms tarde": "On average your strums are {ms:.0f} ms late",
    "Tus strums van de media {ms:.0f} ms pronto": "On average your strums are {ms:.0f} ms early",
    "(si te pasa siempre, calibra el retardo)": "(if it always happens, calibrate the latency)",
    "Sin récord en {name} todavía": "No high score on {name} yet",
    "Récord en {name}: <b>{score}</b> · {acc:.0%} · racha {streak}":
        "High score on {name}: <b>{score}</b> · {acc:.0%} · streak {streak}",
    "sin fallos": "full combo",
    "{n} partidas · el {date}": "{n} games · on {date}",

    # ---------- icono de la bandeja ----------
    "Music Hero sigue aquí": "Music Hero is still here",
    "{key} o un clic en este icono para volver; para salir, clic derecho en el icono.":
        "{key} or click this icon to come back; to quit, right-click the icon.",
    "Ocultar ({key})": "Hide ({key})",
    "Mostrar ({key})": "Show ({key})",

    # ---------- consola ----------
    "No hay chart para {name}; genérala con: uv run --project generator generate \"{path}\"":
        "No chart for {name}; generate it with: uv run --project generator generate \"{path}\"",
    "No encuentro el audio de la chart: {file}": "Can't find the chart's audio: {file}",
    "motor instalado": "engine installed",
    "error: {err}": "error: {err}",
    "audio (busca su chart en out/charts) o carpeta de chart; sin ella, el selector":
        "audio file (its chart is looked up in out/charts) or chart folder; without it, the song picker",
    "por defecto, la última elegida en esa canción o, si no, la de por defecto (Ajustes)":
        "by default, the last one chosen for that song or, failing that, the default one (Settings)",
    "velocidad de las notas (1 = normal); el menú la guarda": "note speed (1 = normal); the menu saves it",
    "guarda una captura a los N s (--screenshot-at) y sale": "saves a screenshot after N s (--screenshot-at) and quits",
    "con --screenshot: abre el menú antes": "with --screenshot: open the menu first",
    "modo automático: el juego toca solo": "autoplay: the game plays by itself",
    "empezar oculto (Ctrl+Alt+H lo muestra)": "start hidden (Ctrl+Alt+H shows it)",
    "(app instalada) instalar el motor de generación sin abrir el juego, y salir":
        "(installed app) install the generation engine without opening the game, then quit",
    "Music Hero ya está abierto": "Music Hero is already open",
    "aviso: {msg}": "warning: {msg}",
    "sin canciones todavía": "no songs yet",
    "+ / {pause}: menú, − / {diff}: dificultad, {toggle} muestra/oculta, {quit} sale (o el icono junto al reloj).":
        "+ / {pause}: menu, − / {diff}: difficulty, {toggle} shows/hides, {quit} quits (or the icon by the clock).",
    "Music Hero: juega con la guitarra sobre la canción que suena.\n\n"
    "    play                      el selector de canciones\n"
    "    play \"<canción o carpeta de chart>\" [--difficulty hard]\n"
    "    play --hidden             oculto: Ctrl+Alt+H lo muestra; si suena AIMP, lo sigue":
        "Music Hero: play along with the guitar over the song that's playing.\n\n"
        "    play                      the song picker\n"
        "    play \"<song or chart folder>\" [--difficulty hard]\n"
        "    play --hidden             hidden: Ctrl+Alt+H shows it; if AIMP is playing, it follows it",
}
