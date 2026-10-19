#!/bin/sh
# Noche del modelo v5d: v5 afinado con la guitarra de Demucs (la que hay al generar) en vez de la pista real
# del paquete. Desde la raíz del repo, en Git Bash:
#     sh tools/night_v5d.sh
# 1. Prepara con Demucs los paquetes que traen pista de guitarra (los mismos ~4.800 que v5; 4 procesos,
#    ~3-4 h) -> out/dataset/feat5d
# 2. Prepara el examen (charts humanas de la biblioteca) con Demucs (~10 min) -> out/dataset/feat5d_library
# 3. Afina v5 con eso (10000 pasos, ~1 h) -> models/onset_v5d.pt
# 4. Examen de v5d, de v5 (los dos con la guitarra de Demucs) y de v4, para compararlos.
# Logs en out/dataset/night_v5d_*.log. No toca out/charts ni models/best.pt.
set -e
cd "$(dirname "$0")/.."
LOG=out/dataset/night_v5d
GEN="uv run --project generator python"
# idioma de los avisos: MUSICHERO_LANG o el de Windows; se pasa también a los scripts de Python
MUSICHERO_LANG=${MUSICHERO_LANG:-$(powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2>/dev/null | tr -d '\r')}
[ "$MUSICHERO_LANG" = es ] || MUSICHERO_LANG=en
export MUSICHERO_LANG
say() { if [ "$MUSICHERO_LANG" = es ]; then echo "$(date) $1"; else echo "$(date) $2"; fi >> "${LOG}.log"; }

say "preparar con Demucs (4 procesos)" "prepare with Demucs (4 processes)"
for k in 0 1 2 3; do
    $GEN -m generator.learn.data out/dataset/sng out/dataset/feat5d --guitar --demucs --with-track --shard $k/4 \
        > "${LOG}_prep$k.log" 2>&1 &
done
wait

say "examen" "exam"
$GEN -m generator.learn.data out/encore out/dataset/feat5d_library --guitar --demucs > "${LOG}_library.log" 2>&1

say "afinar v5" "fine-tune v5"
$GEN -m generator.learn.train out/dataset/feat5d --guitar --frets --init models/onset_v5.pt --lr 5e-4 \
    --steps 10000 --eval-every 2500 --out models/onset_v5d.pt > "${LOG}_train.log" 2>&1 \
    || say "afinar salió con código $? (el modelo guardado sirve; se examina igual)" \
           "fine-tune exited with code $? (the saved model is fine; examining it anyway)"

say "examen v5d / v5 / v4" "exam v5d / v5 / v4"
$GEN tools/eval_model.py models/onset_v5d.pt out/dataset/feat5d_library > "${LOG}_eval_v5d.log" 2>&1
$GEN tools/eval_model.py models/onset_v5.pt out/dataset/feat5d_library > "${LOG}_eval_v5.log" 2>&1
$GEN tools/eval_model.py models/onset_v4.pt out/dataset/feat_library > "${LOG}_eval_v4.log" 2>&1
say "fin" "done"
