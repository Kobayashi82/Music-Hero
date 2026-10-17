# Hoja de ruta – Guitar overlay de escritorio

Oct 17, 2026 · @Drajana

## La idea en una frase

Una app propia para Windows 11 que, al pulsar un atajo mientras suena una canción, muestra una autopista de notas tipo Guitar Hero transparente sobre el escritorio, sincronizada con lo que suena, para tocar con una guitarra de plástico (PS3/Wii).

Decisión clave: **no se usa Clone Hero ni YARG como juego**, pero sí se aprovechan como referencia. YARG es de código abierto y sirve para copiar ventanas de acierto, HOPOs y sustains; el formato `.chart` está documentado y las charts hechas por la comunidad sirven para medir la calidad del generador.

Tres piezas independientes:

1. **Generador** (offline): MP3 → chart con 4 dificultades. Procesa una carpeta entera y cachea.
2. **Sincronizador**: sabe qué canción suena y en qué milisegundo está.
3. **Overlay**: ventana transparente, siempre encima, que pinta la autopista y lee el mando.

Prioridad: canciones de tu carpeta local. Las de Spotify/YouTube no tienen archivo, así que van al final (ver Riesgos).

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
| Mando | pygame-ce solo para leer el joystick (SDL) | Reconoce las guitarras como mando y funciona sin foco |
| Posición de la canción | API SMTC de Windows (paquetes `winrt`) | Funciona con cualquier reproductor que salga en el panel multimedia de Windows |
| Audio del sistema | PyAudioWPatch (WASAPI loopback) | Para el ajuste fino de sincronía |
| Atajo global | `RegisterHotKey` de Win32 | Funciona con el overlay sin foco |
| Audio propio (fase 3) | sounddevice | Reloj de reproducción preciso |

## Fases

Cada fase termina en algo que se puede probar. No se pasa a la siguiente sin cumplir su criterio de terminado.

### Fase 0 – Pruebas de concepto (1-2 sesiones)

Objetivo: quitar las incertidumbres técnicas antes de escribir el proyecto en serio.

- [ ] Guitarra: script que lista mandos con SDL (pygame-ce) e imprime cada botón, el strum y la palanca. Comprobar que se lee **sin que la ventana tenga el foco**.
- [ ] SMTC: script que imprime título, artista, estado y posición de lo que suena (probar con el reproductor que uses de verdad).
- [ ] Overlay: ventana transparente, sin bordes, siempre encima y que deja pasar los clics, con un rectángulo moviendo a 60+ fps. Se muestra/oculta con un atajo global.
- [ ] GPU: Demucs y Basic Pitch funcionando con CUDA en una canción.

**Terminado cuando:** los cuatro scripts funcionan en tu PC.

Estado (17-10-2026), scripts en `tools/`, cómo probarlos en `tools/README.md`:

| Prueba | Script | Resultado |
| --- | --- | --- |
| Guitarra | `poc_guitar.py` | Pendiente: falta probar con la guitarra conectada y la ventana sin foco |
| SMTC | `poc_smtc.py` | Pendiente: arranca bien; falta probar con tu reproductor sonando |
| Overlay | `poc_overlay.py` (QPainter) y `poc_overlay_gpu.py` (Qt Quick) | Transparente, click-through y siempre encima comprobados; 60 fps a 3440×1440. Falta probar el atajo a mano |
| GPU | `poc_gpu.py` | OK con audio sintético: Demucs 22× tiempo real (0,6 GB de VRAM), Basic Pitch por CUDA (ONNX). Falta una canción real |

Notas de instalación: Basic Pitch en Windows con Python 3.12 pediría TensorFlow, así que se usa su modelo ONNX con onnxruntime-gpu; torch se instala con CUDA 13 para compartir DLL con onnxruntime-gpu.

### Fase 1 – Generador mínimo (Experto)

- [ ] CLI `generate song.mp3` → separación (Demucs `htdemucs_6s`) → notas (Basic Pitch) → beats y tempo (Beat This! o madmom) → cuantización a la rejilla.
- [ ] Mapeo a 5 botones por contorno relativo: sube → derecha, baja → izquierda, repite → igual. Ventana deslizante para no quedarse pegado en un extremo.
- [ ] Acordes → combinaciones de 2-3 botones; notas largas → sustains; notas ligadas rápidas → HOPO.
- [ ] Si no hay guitarra en un tramo, seguir el bajo, el teclado o la voz.
- [ ] Salida: `chart.json` propio + exportador a `.chart` para probarlo en Moonscraper o YARG.
- [ ] Vista previa en HTML (piano roll + botones) para depurar sin jugar.

**Terminado cuando:** 3 canciones de estilos distintos dan una chart que "se siente" como la canción al verla en la vista previa.

### Fase 2 – Dificultades y lote

- [ ] Derivar Fácil (3 botones, tiempos fuertes, sin acordes), Medio (4 botones), Difícil (5 botones, pocos acordes) desde Experto.
- [ ] Densidad máxima de notas por segundo por dificultad, configurable.
- [ ] `generate carpeta/`: procesa todo, en paralelo controlado, y salta lo ya hecho.
- [ ] Caché por hash del audio + versión del generador (si cambias el algoritmo, se regenera solo lo necesario).
- [ ] Guardar los stems separados para no repetir Demucs al ajustar reglas.

**Terminado cuando:** una carpeta de 50 canciones se procesa sin intervención y tiene las 4 dificultades.

### Fase 3 – Juego en overlay con reproductor propio

Primero con audio reproducido por la propia app: así la sincronía es exacta y se aísla el problema del juego.

- [ ] Autopista en perspectiva, 5 carriles, notas, sustains, HOPOs, línea de golpeo.
- [ ] Detección de acierto: botón(es) correcto(s) + strum dentro de la ventana de tiempo; HOPO sin strum si la nota anterior fue acierto.
- [ ] Puntuación, racha, multiplicador, % de acierto al final.
- [ ] Pantalla de calibración de retardo (audio y vídeo), guardada en la config.
- [ ] Selector de dificultad rápido desde el propio overlay.
- [ ] Opacidad, tamaño y posición del overlay configurables.

**Terminado cuando:** se puede jugar una canción entera y la sensación de ritmo es buena tras calibrar.

### Fase 4 – Sincronizar con el reproductor externo

- [ ] Leer canción y posición vía SMTC; buscar la chart en la biblioteca por etiquetas (artista/título) y, si falla, por duración + nombre de archivo.
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
| Guitarra de Wii | Va conectada al Wiimote por Bluetooth y suele dar más guerra que la de PS3 con dongle USB | Probarla en la fase 0; si no va, usar guitarra de PS3/PS4 o adaptador |
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
