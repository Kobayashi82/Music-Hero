<div align="center">

# 🎸 Music Hero

**Guitar Hero en tu escritorio, con las canciones que ya tienes.**

Una autopista de notas transparente que flota sobre Windows, sincronizada con la canción que suena,<br>
para una guitarra de plástico de Wii (o el teclado). Las charts se hacen solas a partir de tu música.

[English](README.md) · **Español**

![Music Hero jugando sobre el escritorio](docs/images/gameplay.png)

</div>

## Qué hace

- **Sobre tu escritorio, no en un juego aparte.** Una ventana transparente, siempre encima, que deja pasar los clics del ratón. Se muestra y se oculta con un atajo global (`Ctrl+Alt+H`) y puedes seguir usando el PC por debajo.
- **Toca a la vez que AIMP.** Si suena una canción en AIMP, el juego la sigue: su posición, las pausas, los saltos y los cambios de canción. Mide solo el retardo del audio de AIMP. También tiene su propio reproductor, con selector de canciones y buscador.
- **Charts a partir de tus MP3.** Añade tu carpeta de música y las hace en segundo plano, de una en una, primero la que elijas. Cuatro dificultades, acordes, HOPO, notas largas y frases de star power.
- **Letra sincronizada** bajo la autopista, cuando la canción tiene.
- **Guitarra de Wii** a través del Wiimote, emparejada desde la propia app (sin teclear ningún PIN), o el teclado. Levanta la guitarra para el **star power**.
- **Récords** por canción y dificultad, calibración del retardo, teclas configurables, en español e inglés.

## Cómo se hacen las charts

Nada se hace a mano: lo hacen los modelos solos, así que vale para cualquier canción.

1. **Demucs** (`htdemucs_6s`) separa la canción en pistas: guitarra, bajo, batería, voz, piano y el resto.
2. **Beat This!** encuentra los pulsos y los compases.
3. **OnsetNet**, un modelo propio entrenado con miles de charts de la comunidad, decide dónde van las notas en cada dificultad y con qué botones.
4. El texto de la letra sale de **LRCLIB** y se sincroniza palabra a palabra con **stable-ts** (Whisper) sobre la pista de la voz.

Con una tarjeta gráfica NVIDIA, cada canción tarda un minuto más o menos. Sin ella va por el procesador y tarda varios minutos.

## Requisitos

- Windows 11 de 64 bits. Windows 10 debería funcionar, pero no se ha probado.
- Para que las charts salgan rápido: una tarjeta gráfica NVIDIA con el driver 580 o más nuevo. Si no, van por el procesador.
- Espacio en disco para el motor de generación, que se descarga la primera vez que hace falta: unos 5 GB con NVIDIA, 3 GB sin ella.
- Para jugar: una guitarra de Wii enchufada a un Wiimote y Bluetooth en el PC, o solo el teclado.
- Opcional: [AIMP](https://www.aimp.ru/), para tocar sobre tu reproductor de siempre.

## Instalar

Todavía no hay una versión publicada. Para compilar el instalador tú mismo, ver [Compilar](#compilar).

Una vez instalado:

1. Abre Music Hero. La bienvenida te pide tu **carpeta de música**.
2. La primera vez se ofrece a instalar el **motor de generación** y te dice cuánto va a descargar.
3. **Empareja la guitarra** desde la bienvenida o en *Ajustes → Guitarra y teclas*: pulsa el botón rojo de sync, bajo la tapa de las pilas del Wiimote.
4. Elige una canción en cuanto esté la primera chart, o pon algo en AIMP y pulsa `Ctrl+Alt+H`.

## Controles

| Teclado | Guitarra | Acción |
| --- | --- | --- |
| `A` `S` `D` `F` `G` | Trastes | Verde, rojo, amarillo, azul, naranja |
| `↑` `↓` | Barra de strum | Rasguear (en los menús: moverse) |
| `Espacio` · clic derecho en la autopista | `+` | Menú / pausa |
| `Tab` | `−` | Cambiar de dificultad sin parar |
| `E` | Levantar la guitarra | Star power |
| `Retroceso` | | Reiniciar la canción |
| `Ctrl+Alt+H` | `A` del Wiimote | Mostrar / ocultar (funciona en todas partes) |
| `Ctrl+Alt+Q` | | Salir |
| | `1` / `2` / `Home` del Wiimote | Canción siguiente / anterior / al azar |

Las teclas se cambian en *Ajustes → Guitarra y teclas*. Con el juego oculto, el teclado vuelve a ser tuyo (con el reproductor propio, la canción se pausa; AIMP sigue sonando). El icono junto al reloj enseña el estado de la biblioteca y sirve para salir.

## Ejecutar desde el código

Hace falta [uv](https://docs.astral.sh/uv/). El proyecto usa dos entornos separados: uno ligero para la app y uno pesado para el generador (PyTorch con CUDA).

```sh
uv sync --project app
uv sync --project generator                       # descarga PyTorch con CUDA (~3 GB)

uv run --project app play                         # el juego (selector de canciones)
uv run --project app play --hidden                # oculto; Ctrl+Alt+H lo muestra y sigue a AIMP
uv run --project generator generate "<canción.mp3 o carpeta>"   # charts en out/charts/
uv run --project generator lyrics                 # letra sincronizada de todas las charts
```

Tests (sin GPU):

```sh
uv run --project app --with pytest pytest app/tests
uv run --project generator --with pytest --with jsonschema pytest tests
```

> **Nota:** el modelo OnsetNet entrenado (`models/best.pt`) todavía no está publicado; irá a Hugging Face. Sin él, `generate` usa reglas y solo hace la dificultad Experto.

## Compilar

```sh
winget install JRSoftware.InnoSetup               # una vez
uv run --project app --with pyinstaller python packaging/build.py
```

Deja la app en `build/dist/Music Hero/` y el instalador en `build/installer/MusicHero-Setup-<versión>.exe`. El instalador no necesita permisos de administrador. Lleva dentro el modelo OnsetNet, así que para compilarlo hace falta `models/best.pt`. El motor de generación no va dentro: la app lo descarga la primera vez.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `app/` | El juego: overlay (PySide6 + Qt Quick), partida, guitarra de Wii por HID, AIMP, biblioteca, instalador del motor |
| `generator/` | El motor de generación: Demucs, pulsos, OnsetNet, letra, las órdenes `generate` / `lyrics` / `engine` |
| `shared/` | Esquemas JSON de `chart.json` y `lyrics.json` |
| `packaging/` | PyInstaller e Inno Setup |
| `tools/` | Diagnóstico, dataset de entrenamiento y exámenes de los modelos ([detalles](tools/README.es.md)) |
| `ROADMAP.md` | Fases y estado |

## Estado

Las fases 0 a 6 están terminadas: el juego, el generador de charts, la letra, la sincronía con AIMP, el star power y los récords. La fase 7, para que otros lo puedan instalar, está casi acabada. Falta probar el instalador en un Windows limpio, publicar el modelo y una versión para tarjetas gráficas que no sean NVIDIA (ONNX/DirectML). Todo el detalle en [ROADMAP.md](ROADMAP.md).

## Agradecimientos

- [Demucs](https://github.com/facebookresearch/demucs), por separar los instrumentos.
- [Beat This!](https://github.com/CPJKU/beat_this), por los pulsos y compases.
- [Basic Pitch](https://github.com/spotify/basic-pitch), por la transcripción de notas.
- [stable-ts](https://github.com/jianfch/stable-ts) y [Whisper](https://github.com/openai/whisper), por sincronizar la letra, y [LRCLIB](https://lrclib.net/), por el texto de la letra.
- [Chorus Encore](https://www.enchor.us/) y su comunidad de charters, con cuyas charts se entrenó OnsetNet. Aquí no se distribuye ninguna de sus charts.
- [YARG](https://github.com/YARC-Official/YARG) y Clone Hero, como referencia para las ventanas de acierto, los HOPO y el formato `.chart`.
