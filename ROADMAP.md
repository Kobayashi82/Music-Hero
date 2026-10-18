# Hoja de ruta – Guitar overlay de escritorio

Oct 17, 2026 · @Drajana

## La idea en una frase

Una app propia para Windows 11 que, al pulsar un atajo mientras suena una canción, muestra una autopista de notas tipo Guitar Hero transparente sobre el escritorio, sincronizada con lo que suena, para tocar con una guitarra de plástico (PS3/Wii).

Decisión clave: **no se usa Clone Hero ni YARG como juego**, pero sí se aprovechan como referencia. YARG es de código abierto y sirve para copiar ventanas de acierto, HOPOs y sustains; el formato `.chart` está documentado y las charts hechas por la comunidad sirven para medir la calidad del generador.

Tres piezas independientes:

1. **Generador** (offline): MP3 → chart con 4 dificultades. Procesa una carpeta entera y cachea.
2. **Sincronizador**: sabe qué canción suena y en qué milisegundo está.
3. **Overlay**: ventana transparente, siempre encima, que pinta la autopista y lee el mando.

Prioridad: canciones de tu carpeta local (`D:\Programas\Multimedia\Musicas`) sonando en AIMP. Después el navegador (YouTube) y otros reproductores vía SMTC; las de streaming no tienen archivo, así que van al final (ver Riesgos).

## Arquitectura y stack

Todo en Python: el generador corre antes y deja las charts en disco; la app de escritorio solo lee charts, la posición de la canción y el mando.

&#91;embedded content: arquitectura · generador offline, sincronizador y overlay\]

La app nunca transcribe en directo: si la canción no tiene chart, la manda al generador en segundo plano.

| Pieza | Elección | Motivo |
| --- | --- | --- |
| Lenguaje | Python 3.12 + uv | Todo el audio con IA está en Python; un solo lenguaje simplifica Claude Code |
| Separación | Demucs `htdemucs_6s` | Tiene pista de guitarra propia |
| Notas | Basic Pitch (Spotify) | Polifónico, ligero, funciona en local |
| Ritmo | Beat This! (alternativa: madmom) | Beats y compases para cuantizar |
| Overlay | PySide6 + Qt Quick (GPU, Direct3D 11), ventana transparente, siempre encima, deja pasar clics | Maduro en Windows; medido en fase 0: 2,5 % de CPU frente a 12-18 % con QPainter a 3440×1440. Godot 4 como plan B |
| Mando | pygame-ce solo para leer el joystick (SDL) + teclado | Vale cualquier mando o guitarra que SDL reconozca, y el teclado. El teclado usa la técnica del Lander: con el juego activo, las teclas del juego se registran con `RegisterHotKey` (no llegan a otras apps) y la suelta se lee con `GetAsyncKeyState` |
| Posición de la canción | AIMP: su API remota (`AIMP2_RemoteInfo`). Resto: API SMTC de Windows (paquetes `winrt`) | AIMP no sale en SMTC, pero su API da la posición en ms y la ruta del archivo. SMTC cubre el navegador y cualquier reproductor del panel multimedia de Windows |
| Audio del sistema | PyAudioWPatch (WASAPI loopback) | Para el ajuste fino de sincronía |
| Atajo global | `RegisterHotKey` de Win32, configurable, por defecto Ctrl+Alt+H | Funciona con el overlay sin foco |
| Audio propio (fase 3) | sounddevice | Reloj de reproducción preciso |

## Fases

Cada fase termina en algo que se puede probar. No se pasa a la siguiente sin cumplir su criterio de terminado.

### Fase 0 – Pruebas de concepto (1-2 sesiones)

Objetivo: quitar las incertidumbres técnicas antes de escribir el proyecto en serio.

- [x] Guitarra: script que lista mandos con SDL (pygame-ce) e imprime cada botón, el strum y la palanca. Comprobar que se lee **sin que la ventana tenga el foco**. Guitarra de Wii.
- [x] Teclado: tocar con el teclado sin foco y sin que las teclas lleguen a la app de debajo.
- [x] SMTC: script que imprime título, artista, estado y posición de lo que suena (probar con el reproductor que uses de verdad).
- [x] Overlay: ventana transparente, sin bordes, siempre encima y que deja pasar los clics, con un rectángulo moviendo a 60+ fps. Se muestra/oculta con un atajo global.
- [x] GPU: Demucs y Basic Pitch funcionando con CUDA en una canción.

**Terminado cuando:** los cuatro scripts funcionan en tu PC.

Estado (18-10-2026): ✅ terminada. Scripts en `tools/`, cómo probarlos en `tools/README.md`:

| Prueba | Script | Resultado |
| --- | --- | --- |
| Guitarra | `pair_wiimote.py`, `poc_wii_guitar.py` (`poc_guitar.py` para mandos SDL) | ✅ Guitarra de Wii: Windows 11 pide un PIN que no se puede teclear (la dirección Bluetooth del PC en bytes); `pair_wiimote.py` lo pasa por la API. SDL ve el Wiimote pero no la extensión de guitarra ("Unknown Extension"), así que se lee por HID (`app/src/app/wii_guitar.py`, protocolo del Wiimote): trastes, acordes, strum, palanca, Start/Select, ~96 informes/s (cada ~10 ms) y sin foco |
| Teclado | `poc_keyboard.py` | ✅ Probado con `autotest_input.py` (teclas inyectadas): trastes, acordes, strum y sueltas llegan sin foco, y las teclas del juego no llegan a la app con foco; al desactivar vuelven a escribir |
| AIMP | `poc_aimp.py` | ✅ Probado con `autotest_aimp.py`: la posición se actualiza cada ~32 ms (pasos de 30 ms) y se desvía del reloj entre -28 y +16 ms; seek reflejado en 3 ms, cambio de pista detectado en 12 ms |
| SMTC | `poc_smtc.py` | AIMP no publica en SMTC. No bloquea la fase 0 (AIMP va por su API); probar con YouTube cuando toque |
| Overlay | `poc_overlay.py` (QPainter) y `poc_overlay_gpu.py` (Qt Quick) | ✅ Transparente, click-through, no roba el foco y queda encima de un reproductor de vídeo (recupera el primer puesto cada 0,5 s, como el Lander); 60 fps a 3440×1440. Atajo Ctrl+Alt+H probado con `autotest_input.py` |
| GPU | `poc_gpu.py` | ✅ Queen - Hammer to Fall (3:50): Demucs 3,9 s (59× tiempo real, 0,6 GB de VRAM), Basic Pitch 1 s por CUDA (ONNX). Ojo: solo 171 notas con guitarra distorsionada, a ajustar en la fase 1 |

Notas de instalación: Basic Pitch en Windows con Python 3.12 pediría TensorFlow, así que se usa su modelo ONNX con onnxruntime-gpu; torch se instala con CUDA 13 para compartir DLL con onnxruntime-gpu.

### Fase 1 – Generador mínimo (Experto)

- [x] CLI `generate song.mp3` → separación (Demucs `htdemucs_6s`) → notas (Basic Pitch) → beats y tempo (Beat This!) → cuantización a la rejilla.
- [x] Mapeo a 5 botones por contorno relativo: sube → derecha, baja → izquierda, repite → igual. Ventana deslizante para no quedarse pegado en un extremo.
- [x] Acordes → combinaciones de 2-3 botones; notas largas → sustains; notas ligadas rápidas → HOPO.
- [x] Si no hay guitarra en un tramo, seguir el bajo, el teclado o la voz.
- [x] Salida: `chart.json` propio + exportador a `.chart` para probarlo en Moonscraper o YARG.
- [x] Vista previa en HTML (piano roll + botones) para depurar sin jugar.

**Terminado cuando:** 3 canciones de estilos distintos dan una chart que "se siente" como la canción al verla en la vista previa.

Estado (17-10-2026): implementado; **falta tu valoración** de las vistas previas (`out/charts/<canción>/preview.html`).

Primera valoración (v0.1): Queen escasa, Sk8er Boi bien, Graceland complicada, Apocalypse con demasiadas notas. En general: **la chart tiene que tocar la sensación de la canción, no todas sus notas**. La v0.2 cambia el enfoque:

| Canción | Estilo | Energía | nps v0.1 → v0.2 | Acordes | Sustains | Desfase con el ataque (mediana / p90) |
| --- | --- | --- | --- | --- | --- | --- |
| Queen – Hammer to Fall | rock | 0,82 | 2,6 → 3,4 | 3 % | 0 % | 12 / 39 ms |
| Avril Lavigne – Sk8er Boi | pop punk | 0,80 | 5,0 → 4,5 | 22 % | 1 % | 10 / 27 ms |
| Paul Simon – Graceland | pop, guitarra limpia | 0,80 | 4,8 → 3,7 | 22 % | 2 % | 5 / 17 ms |
| Cigarettes After Sex – Apocalypse | lento, ambiental | 0,23 | 4,4 → 1,6 | 12 % | 24 % | 6 / 20 ms |

Segunda valoración (v0.2): **ninguna sirve**. El ritmo que se siente (lo que se tamborilearía en una mesa) no lo dicta un instrumento: en Queen, al principio, es un "ta ta taaaa" por compás y la chart pone muchas notas. Decisión: hacer las dos cosas:

1. **Ritmo marcado a mano** (retirado el 18-10-2026): una grabadora (`tap`, Espacio = "ta", mantener = "taaaa" con AIMP sonando) para que los toques mandasen el cuándo y el cuánto. Se marcó a oído y no es una referencia precisa (además llegaba ~250 ms tarde); la referencia pasó a ser las charts humanas y el modelo propio (OnsetNet), así que se quitaron la grabadora, los toques y su uso en `generate`.
2. **Automático que siga el motivo** (pendiente): la melodía principal (voz o riff) con sus notas largas, en vez de los ataques de los instrumentos. Sustituido por el modelo propio entrenado con charts humanas.

Lo aprendido con 4 canciones marcadas a mano (herramienta ya retirada) y charts humanas (`tools/eval_vs_human.py`):
- Con batería, lo marcado coincide sobre todo con los golpes de la batería (F1 0,6-0,8); la voz es de lo que peor encaja. En Queen (cada 2 pulsos, largo-corto) y en canciones lentas de notas largas, ninguna fuente del audio lo explica bien.
- **Ni la chart oficial de Harmonix coincide mucho con lo marcado a mano** (F1 0,47; la dificultad Difícil tiene la misma densidad y da 0,45): no hay una única respuesta correcta. Pero su intro es justo el "ta ta taaaa" que describió el usuario: **el objetivo es parecerse a las charts humanas**.
- Modelos públicos entrenados con charts humanas (17-10-2026):
  - **Tab Hero** (MIT, ~6000 charts): funciona con la pista de guitarra separada y generando por trozos (su generación en streaming no avanza el tiempo). Contra Harmonix (Queen, Experto) da F1 0,39; nuestro generador v0.2, 0,62. En Give Up, contra lo marcado a mano, 0,48-0,54 (v0.2: 0,56). No mejora lo nuestro.
  - **CloneCharter** (MIT, 42 600 charts): solo pesos, sin código publicado.
  - **Fretformer / Autochart** (CC BY-NC-SA): piezas ONNX sin el código de la aplicación que las decodifica.
  - **chartgen.org**: mismo enfoque que nuestro v0.1 (Demucs + Basic Pitch).
- **Charts humanas de Chorus Encore**: ~30 % de una muestra de 30 canciones de la biblioteca tiene una (muchas de Harmonix). `generate canción.mp3 --human chart.sng` la sincroniza con el audio propio aunque sea otra versión (Queen: el MP3 va un 3,6 % más lento; 92 % de anclas afinadas). La búsqueda (`api.enchor.us`) funciona; las descargas (`files.enchor.us`, Cloudflare) a veces están bloqueadas desde España y hay que usar VPN.

Cómo funciona (`generator/src/generator/`), lo que no es obvio leyendo el código:
- **Energía por compás** (`feel.py`): sobre todo lo presente que está la batería respecto a la mezcla (mediana por tramo: unos -26 dB en una balada, -10..-12 dB en rock/punk/pop), y algo del volumen del tramo dentro de la canción.
- **Presupuesto**: de 0,75 notas por pulso (energía 0) a 2,25 (energía 1). Semicorcheas solo con energía ≥ 0,75 y entre notas claras de Basic Pitch.
- **Qué notas entran**: las que más se sienten: tiempo fuerte (inicio de compás > pulso > corchea > semicorchea), acento del conjunto y de la batería, fuerza y duración de la nota.
- **Relleno de groove**: si un tramo enérgico se queda corto de notas transcritas (guitarra distorsionada, palm mute) y la guitarra suena, se añaden notas en tiempos y corcheas con acento claro, repitiendo la nota que suena.
- **Simplificar**: acordes del 8 % (tranquila) al 25 % (enérgica), en los golpes más acentuados; de 3 botones solo con energía ≥ 0,8; notas a menos de media corchea se mueven como mucho 1 botón.
- Basic Pitch se deja muchas notas con guitarra distorsionada: el ritmo se completa con un detector de ataques normalizado por ventanas de 6 s (con la normalización global de librosa un estribillo fuerte esconde los versos) y un mínimo global (si no, la reverb da ataques falsos).
- Botón = orden de la altura dentro de una ventana de ±8 pulsos (3 alturas distintas → 3 botones seguidos), corregido por el contorno: el paso crece con el intervalo (1 botón hasta 4 semitonos, 2 hasta 9, 3 más). La misma altura en la misma frase repite botón.
- HOPO con el mismo umbral que Clone Hero/YARG (65/192 de pulso), así el `.chart` no necesita forzar casi ninguno.
- Pulsos sin detectar (intros) se rellenan con el tempo de alrededor; un 2/4 detectado se trata como 4/4.

### Fase 2 – Dificultades y lote

- [x] Las 4 dificultades: las da el modelo propio (OnsetNet, aprendido de charts humanas) en vez de derivarlas de Experto con reglas.
- [x] Densidad máxima de notas por segundo por dificultad, configurable (`--max-nps`; por defecto 14 / 8 / 5 / 3,5 en 2 s, algo por encima del p90 de las charts humanas).
- [x] `generate carpeta/`: procesa todo (subcarpetas incluidas), `--jobs N` canciones a la vez, y salta lo ya hecho.
- [x] Caché por hash del audio + versión del generador y del modelo (si cambias el algoritmo o el modelo, se regenera solo lo necesario).
- [x] Guardar los stems separados para no repetir Demucs al ajustar reglas (~50 MB por canción; `--drop-stems` los borra).

**Terminado cuando:** una carpeta de 50 canciones se procesa sin intervención y tiene las 4 dificultades.

Estado (18-10-2026): ✅ toda la carpeta de música (676 canciones; se saltan 7 de más de 30 min) procesada sin intervención con `generate "D:/Programas/Multimedia/Musicas" --jobs 3 --max-minutes 30`: 676 de 676 con las 4 dificultades, 55 min sin Demucs (102 min la primera vez), 49 GB con stems. Modelo: OnsetNet v4 (ritmo + botones aprendidos de charts humanas). Lo que salió del primer lote y se arregló: MP3 dentro de un contenedor WAV, pistas sin pulsos, nombres que acaban en punto o espacio, títulos fuera de cp1252, carpetas pisadas al procesar en paralelo dos audios con el mismo nombre, y charts vacías en pistas ambientales (densidad mínima por dificultad).

### Fase 3 – Juego en overlay con reproductor propio

Primero con audio reproducido por la propia app: así la sincronía es exacta y se aísla el problema del juego.

- [x] Autopista en perspectiva, 5 carriles, notas, sustains, HOPOs, línea de golpeo.
- [x] Detección de acierto: botón(es) correcto(s) + strum dentro de la ventana de tiempo; HOPO sin strum si la nota anterior fue acierto.
- [x] Puntuación, racha, multiplicador, % de acierto al final.
- [x] Pantalla de calibración de retardo, guardada en la config: como en Band Hero, bajan notas que suenan (un clic) al pasar por la línea y se rasguea con ellas; la mediana del desfase va a `audio_offset_ms` (mueve sonido, imagen y aciertos a la vez). El desfase entre imagen y sonido, a mano en Ajustes.
- [x] Selector de dificultad rápido desde el propio overlay.
- [x] Opacidad, tamaño y posición del overlay configurables.
- [x] Menú con la guitarra: + abre la pausa (continuar, dificultad, reiniciar, ajustes, calibrar, salir), − cambia de dificultad sin parar la canción; strum mueve, verde elige, rojo vuelve. Lo mismo con teclado (Espacio, Tab, flechas, Intro, Retroceso).
- [x] La guitarra se reconecta sola si se apaga o se enciende con el juego abierto.
- [x] Récords y estadísticas por canción y dificultad (`%APPDATA%/MusicHero/stats.json`, por hash del audio): mejor puntuación con su precisión, racha y fecha, partidas jugadas, mejor precisión, mejor racha y las últimas 20 partidas. Se ven en la pausa, en el marcador (dorado al superarlo, con aviso) y al acabar. No cuentan las partidas con el modo automático ni las empezadas a mitad (cambio de dificultad jugando).
- [x] Dificultad guardada por canción; si una canción no tiene, la de por defecto (Ajustes).
- [ ] Selector de canciones en el overlay: artista → álbum → canción, con las etiquetas del audio (las que tienen chart).
- [ ] Letra debajo de la autopista. Se saca al generar: la de la chart humana si la trae; si no, la sincronizada de LRCLIB (artista, título y duración), y Whisper sobre la pista de voz para ajustar cada palabra. Whisper solo, sin letra conocida, como último recurso (con voces susurradas se inventa frases). Versión nueva del esquema de chart.

Estado (18-10-2026): primera versión jugable; el usuario la ha probado con la guitarra de Wii en 5 canciones (Difícil, velocidad de notas 0,8). Hecho el menú, la calibración y una autopista entre Rock Band y neón con sprites dibujados por QPainter al doble de resolución (`app/src/app/sprites.py`): notas con bisel metálico, tapa de color como cristal con luz por dentro y sombra de contacto; HOPO con tapa blanca encendida y aro del color del carril; botones con cristal ahumado que se enciende al pulsar; fuego suave con haz de luz y chispas al acertar (también mientras suena un sustain); raíles metálicos a los lados y sin línea de golpeo; colas de sustain como textura suave proyectada en perspectiva (homografía con Matrix4x4), más viva al mantener; al fallar, brillo rojo abajo y el botón tiembla; luz suave y corta en el carril pulsado. «Modo automático» en el menú de pausa. Falta calibrar en su PC, el selector de canciones y la letra. `play --autoplay` toca solo, para probar la vista.

**Terminado cuando:** se puede jugar una canción entera y la sensación de ritmo es buena tras calibrar.

### Fase 4 – Sincronizar con el reproductor externo

- [ ] AIMP: canción y posición por su API remota; la chart se busca por la ruta del archivo (hash del audio).
- [ ] Resto (navegador, otros reproductores): SMTC; buscar la chart por etiquetas (artista/título) y, si falla, por duración + nombre de archivo.
- [ ] Interpolar la posición entre actualizaciones con el reloj del sistema (SMTC actualiza poco a menudo).
- [ ] Ajuste fino: capturar el audio del sistema (WASAPI loopback) unos segundos y alinearlo con la canción procesada (correlación de onsets/croma). Repetir cada X segundos para corregir deriva.
- [ ] Reaccionar a pausa, salto, cambio de canción.
- [ ] Atajo global: si la canción no tiene chart, mensaje discreto y opción de generarla en segundo plano.

**Terminado cuando:** pulsas el atajo a mitad de canción en tu reproductor y en menos de 2 s las notas van sincronizadas.

### Fase 5 – Calidad

- [ ] Banco de pruebas: canciones con chart humana de la comunidad → comparar ritmo (notas a tiempo) y forma (movimiento de botones) con la generada.
- [ ] Ajustar reglas con esa métrica en vez de a ojo.
- [ ] Editor sencillo para corregir notas a mano (o exportar a Moonscraper y reimportar).
- [ ] Opcional y más adelante: entrenar un modelo propio con charts humanas como datos.

### Fase 6 – Extras

- [ ] Canciones de streaming: grabar por loopback la primera vez que suenan, procesarlas, y la siguiente vez ya hay chart.
- [ ] Icono en la bandeja con ajustes, biblioteca y estado del procesado.
- [ ] Estadísticas por canción, temas visuales, star power.

## Riesgos y límites

| Riesgo | Por qué pasa | Plan |
| --- | --- | --- |
| Charts que no "se sienten" bien | Transcribir es fácil de medir; que el mapeo a botones sea divertido, no | Métrica contra charts humanas (fase 5) y editor para corregir |
| Guitarra distorsionada, dos guitarras, solos rápidos | La transcripción falla más ahí | En esos tramos priorizar ritmo sobre altura: a tiempo importa más que el botón exacto |
| Posición de SMTC imprecisa | Se actualiza poco y algunos reproductores la reportan mal | Interpolación + ajuste fino por loopback (fase 4); reproductor propio como alternativa |
| Retardo del audio (Bluetooth, drivers) | Lo que oyes llega tarde respecto a lo que la app cree | Calibración obligatoria la primera vez |
| Mando no detectado sin foco | El overlay deja pasar los clics y no tiene foco | Activar eventos de mando en segundo plano en SDL; verificarlo en la fase 0 |
| Guitarra de Wii | Va conectada al Wiimote por Bluetooth y suele dar más guerra que la de PS3 con dongle USB | Probarla en la fase 0 (SDL lee el Wiimote por HIDAPI); si no va, WiitarThing la expone como mando de Xbox 360, o guitarra de PS3/PS4 |
| Canciones de Spotify/YouTube | No hay archivo para procesar por delante | Grabar la primera reproducción por loopback (fase 6) |
| Overlay sobre juegos a pantalla completa | Las ventanas encima no se ven en pantalla completa exclusiva | Fuera de alcance: pensado para escritorio y reproductores de música |

## Arrancar con Claude Code

### Estructura del repositorio

```
guitar-overlay/
  CLAUDE.md
  ROADMAP.md            (esta hoja de ruta exportada)
  generator/            entorno pesado: torch, demucs, basic-pitch
    pyproject.toml
    src/generator/
      separate.py       Demucs -> stems
      transcribe.py     Basic Pitch -> notas
      rhythm.py         beats, tempo, cuantización
      mapping.py        notas -> 5 botones, acordes, HOPO, sustain
      difficulty.py     Experto -> Difícil/Medio/Fácil
      export_chart.py   chart.json y .chart
      batch.py          carpeta + caché
      preview.py        vista previa HTML
  app/                  entorno ligero: PySide6, pygame-ce, winrt
    pyproject.toml
    src/app/
      main.py           bandeja + atajo global
      overlay.py        ventana transparente y dibujo
      gameplay.py       aciertos, puntuación
      controller.py     lectura del mando (SDL)
      sync_smtc.py      canción y posición del sistema
      sync_loopback.py  ajuste fino por audio
      library.py        índice de canciones y charts
  shared/chart_schema.json
  tests/
  tools/                scripts de la fase 0
```

Dos entornos separados (con `uv`) porque las librerías de IA pesan varios GB y no hacen falta para jugar. Se comunican solo por archivos en la carpeta de la biblioteca.

### CLAUDE.md inicial

```markdown
# Guitar overlay
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
```

### Primeros prompts

1. *Fase 0:* "Lee ROADMAP.md. Crea en tools/ los cuatro scripts de la fase 0, cada uno ejecutable por separado, y dime cómo probarlos."
2. *Esquema:* "Propón shared/chart\_schema.json: metadatos, tempo y beats, y por dificultad una lista de notas (tiempo ms, botones, sustain ms, hopo). Incluye un ejemplo."
3. *Fase 1:* "Implementa el generador de la fase 1 para una canción, con la vista previa HTML. Empieza por separate.py y transcribe.py y para cuando funcionen."
4. A partir de ahí, una fase por sesión, pidiendo siempre que compruebe el criterio de terminado.

Consejo: la técnica de ventana transparente y siempre encima que ya usaste en el juego del lander sirve tal cual para el overlay; si reaprovechas ese código, díselo a Claude Code en la fase 0.
