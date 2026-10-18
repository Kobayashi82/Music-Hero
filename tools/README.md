# Pruebas de la fase 0

Primero, una vez, crear los dos entornos (desde la raíz del repo):

```
uv sync --project app
uv sync --project generator      # descarga torch con CUDA (~3 GB)
```

## 1. Guitarra — `poc_guitar.py`

```
uv run --project app python tools/poc_guitar.py
```

1. Conecta la guitarra antes o después de arrancar (detecta conexiones en caliente).
2. Pulsa cada traste, el strum arriba/abajo, la palanca, Start/Select. Apunta qué número sale para cada cosa.
3. **Prueba del foco:** con el script corriendo, haz clic en otra ventana (navegador, explorador) y sigue tocando. La línea `-- foco en:` muestra qué ventana tiene el foco; los eventos tienen que seguir saliendo.
4. Opcional: `--window` abre una ventana SDL para probar también ese caso.

Funciona si: aparecen trastes, strum y palanca, también con el foco en otra app.

**Guitarra de Wii** (va enchufada al Wiimote). SDL ve el Wiimote pero no la guitarra, así que se lee por HID:

1. Emparejar (una vez): `uv run --project app python tools/pair_wiimote.py` y pulsar el botón rojo de sync bajo la tapa de las pilas. Windows 11 pide un PIN que no se puede teclear; el script se lo pasa por la API (y borra antes los intentos a medias, que impiden volver a encontrarlo).
2. Probar: `uv run --project app python tools/poc_wii_guitar.py`. Sale cada cambio (trastes, strum, palanca, Start/Select) con los 6 bytes en crudo de la extensión; también con el foco en otra ventana.

## 1b. Teclado — `poc_keyboard.py`

```
uv run --project app python tools/poc_keyboard.py
```

`Ctrl+Alt+H` activa el modo juego: `A S D F G` trastes, flechas arriba/abajo o Intro strum. Abre el Bloc de notas, ponle el foco y toca: aquí deben salir pulsaciones y sueltas, y en el Bloc de notas no debe escribirse nada. Desactiva el modo juego y comprueba que esas teclas vuelven a escribir.

## 2a. AIMP — `poc_aimp.py`

```
uv run --project app python tools/poc_aimp.py
```

Pon una canción en AIMP; pausa, salta y cambia de canción. Solo lee, no manda órdenes a AIMP.

Funciona si: salen la canción y la ruta del archivo, y mientras suena `paso` ≈ `reloj` (la posición avanza fina, no a saltos de un segundo).

## 2b. SMTC — `poc_smtc.py` (navegador y otros reproductores)

```
uv run --project app python tools/poc_smtc.py          # sesión actual
uv run --project app python tools/poc_smtc.py --all    # todas
```

Pon un vídeo de YouTube en el navegador (AIMP no sale aquí; para AIMP usa poc_aimp.py). Prueba: pausa, salta adelante/atrás, cambia de canción.

Funciona si: salen título y artista correctos, `interp` avanza suave mientras suena y se para en pausa, y los saltos se reflejan en uno o dos segundos.

## 3. Overlay — `poc_overlay.py` y `poc_overlay_gpu.py`

```
uv run --project app python tools/poc_overlay.py              # QPainter (CPU)
uv run --project app python tools/poc_overlay_gpu.py          # Qt Quick (GPU, recomendado)
```

Opciones: `--fullscreen`, `--hotkey f9` (o `ctrl+alt+x`, `pause`...); la de GPU también acepta `--api d3d11|d3d12|opengl|vulkan`.

- `Ctrl+Alt+H` muestra/oculta, `Ctrl+Alt+Q` sale.
- Comprueba: se ve el escritorio detrás, los clics atraviesan, no roba el foco al escribir en otra app, sigue encima al cambiar de ventana, el atajo funciona con el foco en cualquier sitio.
- La consola imprime fps y % de CPU cada 5 s.

## 4. GPU — `poc_gpu.py`

```
uv run --project generator python tools/poc_gpu.py "D:/ruta/a/una canción.mp3"
```

Sin argumento genera un audio sintético. Deja los 6 stems y `guitar.mid` en `out/poc_gpu/<canción>/`. Escucha `guitar.wav` y abre el `.mid` en cualquier visor MIDI para ver si tiene sentido.

Funciona si: termina con `Demucs en CUDA OK, Basic Pitch en CUDA OK`.

## Pruebas automáticas

Sin tocar nada a mano (útiles para repetir tras un cambio):

```
uv run --project app python tools/autotest_aimp.py     # controla AIMP: suena unos segundos y lo deja como estaba
uv run --project app python tools/autotest_input.py    # inyecta teclas en una ventana de prueba propia
```

`autotest_input.py` toma el foco con su ventana de prueba: la app que lo tuviera (un vídeo a pantalla completa, por ejemplo) puede reaccionar al perderlo.
