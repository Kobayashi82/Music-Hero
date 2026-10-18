# Herramientas

[English](README.md) · **Español**

Utilidades de consola para diagnóstico, el dataset de entrenamiento y los exámenes de los modelos. El juego no necesita ninguna. Se lanzan desde la raíz del repositorio.

## Guitarra y AIMP (entorno de la app)

| Script | Qué hace |
| --- | --- |
| `pair_wiimote.py` | Empareja un Wiimote con Windows sin teclear el PIN que pide Windows 11 (el juego hace lo mismo desde *Ajustes → Guitarra y teclas*). |
| `wii_guitar_monitor.py` | Enseña cada cambio que manda la guitarra de Wii (trastes, strum, palanca, Start/Select) con los bytes en crudo. Para cuando un botón no responde. |
| `wii_tilt_monitor.py [segundos]` | Enseña el acelerómetro del Wiimote mientras levantas la guitarra, para comprobar o reajustar el umbral del star power. |
| `readme_image.py <juego.png> <salida.png> <artista> <título>` | Monta la imagen del README: una captura del juego con transparencia (`play --screenshot`) sobre un escritorio dibujado. Los pasos, en el script. |
| `measure_aimp_latency.py [segundos] [veces]` | Mide cuánto va por detrás lo que se oye de la posición que da AIMP (el juego lo mide solo mientras sigue a AIMP). |

```
uv run --project app python tools/<script>.py
```

Con el juego cerrado: usa el mismo mando.

## Dataset y modelos (entorno del generador, GPU NVIDIA)

| Script | Qué hace |
| --- | --- |
| `encore_dataset.py catalog \| download \| catalog-extra \| download-extra \| library \| library-download` | Monta el conjunto de entrenamiento con charts de la comunidad de Chorus Encore (`out/dataset/`). Solo para uso personal. |
| `night_v5.sh` | La tanda de la noche: prepara los datos, entrena el modelo v5 y lo examina frente al v4 (~6-7 h). |
| `eval_model.py <modelo.pt> <datos> [--per-song]` | Examina un modelo con las charts humanas de tu biblioteca (F1 del ritmo y botones). |
| `eval_frets.py <modelo.pt> <datos>` | Compara formas de elegir los botones (nota a nota o con Viterbi). |
| `eval_vs_human.py <chart.json humana> <dificultad> "nombre=otra/chart.json[:dificultad]" ...` | Compara charts generadas con una humana de la misma canción. |

```
uv run --project generator python tools/<script>.py
sh tools/night_v5.sh
```

Los mensajes salen en el idioma de Windows, o con `MUSICHERO_LANG=es` / `en`.
