#!/bin/sh
# Noche del modelo v5 (entrada con la pista de guitarra y su CQT). Desde la raíz del repo, en Git Bash:
#     sh tools/night_v5.sh
# 1. Prepara los paquetes que traen pista de guitarra (4 procesos, ~2-3 h) -> out/dataset/feat5
# 2. Prepara el examen (charts humanas de la biblioteca) con la guitarra de Demucs, como al generar
#    (~10 min) -> out/dataset/feat5_library
# 3. Entrena v5 con botones (~4 h) -> models/onset_v5.pt
# 4. Examen de v5 y de v4 (el de ahora) para compararlos.
# Logs en out/dataset/night_v5_*.log. No toca out/charts ni models/best.pt.
set -e
cd "$(dirname "$0")/.."
LOG=out/dataset/night_v5
GEN="uv run --project generator python"
# idioma de los avisos: MUSICHERO_LANG o el de Windows; se pasa también a los scripts de Python
MUSICHERO_LANG=${MUSICHERO_LANG:-$(powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2>/dev/null | tr -d '\r')}
[ "$MUSICHERO_LANG" = es ] || MUSICHERO_LANG=en
export MUSICHERO_LANG
say() { if [ "$MUSICHERO_LANG" = es ]; then echo "$(date) $1"; else echo "$(date) $2"; fi >> "${LOG}.log"; }

say "preparar (4 procesos)" "prepare (4 processes)"
for k in 0 1 2 3; do
    $GEN -m generator.learn.data out/dataset/sng out/dataset/feat5 --guitar --shard $k/4 > "${LOG}_prep$k.log" 2>&1 &
done
wait

say "examen" "exam"
$GEN -m generator.learn.data out/encore out/dataset/feat5_library --guitar --demucs > "${LOG}_library.log" 2>&1

say "entrenar" "train"
$GEN -m generator.learn.train out/dataset/feat5 --guitar --frets --steps 25000 --eval-every 2500 \
    --out models/onset_v5.pt > "${LOG}_train.log" 2>&1

say "examen v5 / v4" "exam v5 / v4"
$GEN tools/eval_model.py models/onset_v5.pt out/dataset/feat5_library > "${LOG}_eval_v5.log" 2>&1
$GEN tools/eval_model.py models/onset_v4.pt out/dataset/feat_library > "${LOG}_eval_v4.log" 2>&1
say "fin" "done"
