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

## 2. SMTC — `poc_smtc.py`

```
uv run --project app python tools/poc_smtc.py          # sesión actual
uv run --project app python tools/poc_smtc.py --all    # todas
```

Pon música en el reproductor que uses de verdad. Prueba: pausa, salta adelante/atrás, cambia de canción.

Funciona si: salen título y artista correctos, `interp` avanza suave mientras suena y se para en pausa, y los saltos se reflejan en uno o dos segundos.

## 3. Overlay — `poc_overlay.py` y `poc_overlay_gpu.py`

```
uv run --project app python tools/poc_overlay.py              # QPainter (CPU)
uv run --project app python tools/poc_overlay_gpu.py          # Qt Quick (GPU, recomendado)
```

Opciones: `--fullscreen`, `--hotkey f9` (o `ctrl+alt+x`, `pause`...); la de GPU también acepta `--api d3d11|d3d12|opengl|vulkan`.

- `Ctrl+Alt+G` muestra/oculta, `Ctrl+Alt+Q` sale.
- Comprueba: se ve el escritorio detrás, los clics atraviesan, no roba el foco al escribir en otra app, sigue encima al cambiar de ventana, el atajo funciona con el foco en cualquier sitio.
- La consola imprime fps y % de CPU cada 5 s.

## 4. GPU — `poc_gpu.py`

```
uv run --project generator python tools/poc_gpu.py "D:/ruta/a/una canción.mp3"
```

Sin argumento genera un audio sintético. Deja los 6 stems y `guitar.mid` en `out/poc_gpu/<canción>/`. Escucha `guitar.wav` y abre el `.mid` en cualquier visor MIDI para ver si tiene sentido.

Funciona si: termina con `Demucs en CUDA OK, Basic Pitch en CUDA OK`.
