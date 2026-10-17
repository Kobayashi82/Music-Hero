"""Vista previa HTML autocontenida: piano roll de las pistas + chart, sincronizada con el audio.

Se abre con doble clic (file://). Atajos: espacio play/pausa, flechas ±5 s,
V cambia de vista (línea temporal / autopista), C activa clics en cada nota.
`preview.html#t=60` empieza en el segundo 60.
"""

import json
from pathlib import Path

from .model import ChartNote, Section, SongInfo, SourceNote
from .rhythm import TempoMap

STEM_ORDER = ["guitar", "piano", "other", "vocals", "bass"]


def write_preview(path: Path, song: SongInfo, tempo: TempoMap, notes: list[ChartNote], sections: list[Section],
                  source: list[SourceNote], generator_version: str,
                  difficulties: dict[str, list[ChartNote]] | None = None) -> None:
    difficulties = difficulties or {"expert": notes}

    def pack(ns: list[ChartNote]) -> list:
        return [[n.time_ms, n.frets, n.sustain_ms, int(n.hopo), STEM_ORDER.index(n.stem) if n.stem in STEM_ORDER else 0,
                 n.pitch] for n in ns]

    data = {
        "title": song.title,
        "artist": song.artist,
        "duration": song.duration_ms,
        "version": generator_version,
        "stems": STEM_ORDER,
        "diffs": {d: pack(ns) for d, ns in difficulties.items()},
        "src": sorted([[s.start_ms, s.end_ms, s.pitch, round(s.amp, 2), STEM_ORDER.index(s.stem),
                        int(s.origin == "onset")] for s in source if s.stem in STEM_ORDER]),
        "beats": tempo.beats_ms,
        "downbeats": tempo.downbeats_ms,
        "sections": [[tempo.beat_to_ms(s.start_beat), tempo.beat_to_ms(s.end_beat),
                      STEM_ORDER.index(s.stem) if s.stem in STEM_ORDER else -1, round(s.energy, 2)]
                     for s in sections],
    }
    html = (TEMPLATE.replace("__TITLE__", f"{song.artist} - {song.title}".replace("<", ""))
            .replace("__AUDIO__", Path(song.audio_path).resolve().as_uri())
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    path.write_text(html, encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#111318; --panel:#1b1e26; --fg:#e8e8ee; --dim:#8a8fa0; --line:#2a2e3a; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px system-ui, sans-serif; overflow:hidden; }
  header { display:flex; flex-wrap:wrap; gap:8px 18px; align-items:center; padding:10px 16px; background:var(--panel); }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  .stats { color:var(--dim); font-size:12px; }
  .stats b { color:var(--fg); font-weight:600; }
  .ctrl { display:flex; gap:8px; align-items:center; margin-left:auto; }
  button { background:#2b3040; color:var(--fg); border:1px solid #3a4054; border-radius:6px; padding:5px 10px; cursor:pointer; font:inherit; }
  button.on { background:#3d6df2; border-color:#3d6df2; }
  select { background:#2b3040; color:var(--fg); border:1px solid #3a4054; border-radius:6px; padding:5px 8px; font:inherit; }
  input[type=range] { width:110px; }
  #time { font-variant-numeric: tabular-nums; min-width:110px; text-align:right; }
  canvas { display:block; width:100vw; }
  #legend { position:absolute; left:16px; bottom:10px; font-size:12px; color:var(--dim); display:flex; gap:12px; flex-wrap:wrap; }
  #legend span::before { content:""; display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; background:var(--c); vertical-align:-1px; }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="stats" id="stats"></div>
  <div class="ctrl">
    <select id="diff" title="dificultad"></select>
    <button id="play">▶ Play</button>
    <span id="time">0:00</span>
    <button id="view" title="V">Autopista</button>
    <button id="click" title="C">Clic en notas</button>
    <label title="segundos visibles">zoom <input id="zoom" type="range" min="2" max="30" value="8"></label>
  </div>
</header>
<canvas id="cv"></canvas>
<div id="legend"></div>
<audio id="au" src="__AUDIO__" preload="auto"></audio>
<script>
const D = __DATA__;
const LANE = ["#2ecc40","#ff4136","#ffdc00","#0074d9","#ff851b"];
const STEMC = {guitar:"#ff9f43", piano:"#48dbfb", other:"#a4b0be", vocals:"#ff6b9d", bass:"#a29bfe"};
const NAMES = {guitar:"guitarra", piano:"piano", other:"otros", vocals:"voz", bass:"bajo"};
const au = document.getElementById("au"), cv = document.getElementById("cv"), ctx = cv.getContext("2d");
let view = "timeline", clicks = false, span = 8, lastT = 0, actx = null, seekTo = 0;

const DIFF_NAMES = {expert:"Experto", hard:"Difícil", medium:"Medio", easy:"Fácil"};
D.notes = D.diffs.expert || Object.values(D.diffs)[0];
// ---------- estadísticas ----------
function stats(){
  const n = D.notes, dur = D.duration/1000;
  const chords = n.filter(x => x[1].length > 1).length, hopos = n.filter(x => x[3]).length, sus = n.filter(x => x[2] > 0).length;
  let maxNps = 0;
  for (let i = 0, j = 0; i < n.length; i++) { while (n[i][0] - n[j][0] > 1000) j++; maxNps = Math.max(maxNps, i - j + 1); }
  const by = {}; for (const s of D.sections) if (s[2] >= 0) by[D.stems[s[2]]] = (by[D.stems[s[2]]]||0) + (s[1]-s[0]);
  const tot = Object.values(by).reduce((a,b)=>a+b, 0) || 1;
  const src = Object.entries(by).sort((a,b)=>b[1]-a[1]).map(([k,v]) => `${NAMES[k]} ${Math.round(100*v/tot)}%`).join(", ");
  const pct = x => Math.round(100*x/Math.max(1,n.length)) + "%";
  const energy = D.sections.reduce((a, s) => a + s[3], 0) / Math.max(1, D.sections.length);
  document.getElementById("stats").innerHTML =
    `<b>${n.length}</b> notas · <b>${(n.length/dur).toFixed(1)}</b> nps (máx ${maxNps}) · acordes <b>${pct(chords)}</b> · HOPO <b>${pct(hopos)}</b> · sustains <b>${pct(sus)}</b> · energía <b>${energy.toFixed(2)}</b> · fuente: ${src} · v${D.version}`;
  document.getElementById("legend").innerHTML = D.stems.map(s => `<span style="--c:${STEMC[s]}">${NAMES[s]}</span>`).join("")
    + `<span style="--c:#fff">contorno elegido</span>`
    + ` · espacio play · ← → ±5 s · V vista · C clics · clic para saltar`;
}
stats();
(function diffSelect(){
  const sel = document.getElementById("diff");
  for (const d of ["expert","hard","medium","easy"]) if (D.diffs[d]) sel.add(new Option(DIFF_NAMES[d], d));
  sel.onchange = () => { D.notes = D.diffs[sel.value]; stats(); sel.blur(); };
})();

// ---------- utilidades ----------
function lowerBound(arr, t, key) { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo+hi)>>1; if (key(arr[m]) < t) lo = m+1; else hi = m; } return lo; }
function fmt(ms) { const s = Math.max(0, ms/1000); return `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,"0")}.${String(Math.floor(ms%1000/100))}`; }
function resize() { const h = window.innerHeight - document.querySelector("header").offsetHeight; cv.width = innerWidth * devicePixelRatio; cv.height = h * devicePixelRatio; cv.style.height = h + "px"; }
function click() {
  actx = actx || new AudioContext();
  const o = actx.createOscillator(), g = actx.createGain();
  o.frequency.value = 1800; g.gain.setValueAtTime(0.25, actx.currentTime); g.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + 0.04);
  o.connect(g).connect(actx.destination); o.start(); o.stop(actx.currentTime + 0.05);
}

// ---------- vista: línea temporal ----------
function drawTimeline(W, H, now) {
  const px = W / (span*1000), x0 = W * 0.25, X = t => x0 + (t - now) * px;
  const tA = now - x0/px, tB = now + (W - x0)/px;
  const rollH = H * 0.55, laneTop = rollH + 30, laneH = (H - laneTop - 30) / 5;
  // tramos por pista
  // tramos por pista; la altura de la barra es la energía del compás
  for (const s of D.sections) { if (s[1] < tA || s[0] > tB || s[2] < 0) continue;
    const h = 4 + 18 * s[3];
    ctx.fillStyle = STEMC[D.stems[s[2]]] + "70"; ctx.fillRect(X(s[0]) + 1, rollH + 26 - h, X(s[1]) - X(s[0]) - 2, h); }
  // pulsos
  const db = new Set(D.downbeats);
  for (let i = lowerBound(D.beats, tA, x => x); i < D.beats.length && D.beats[i] <= tB; i++) {
    const b = D.beats[i]; ctx.strokeStyle = db.has(b) ? "#3a4054" : "#23262f"; ctx.lineWidth = db.has(b) ? 2 : 1;
    ctx.beginPath(); ctx.moveTo(X(b), 0); ctx.lineTo(X(b), H); ctx.stroke(); }
  // piano roll: rango de alturas visible
  let pmin = 127, pmax = 0;
  const i0 = lowerBound(D.src, tA - 10000, s => s[0]);
  for (let i = i0; i < D.src.length && D.src[i][0] <= tB; i++) { const s = D.src[i]; if (s[1] < tA) continue; pmin = Math.min(pmin, s[2]); pmax = Math.max(pmax, s[2]); }
  if (pmin > pmax) { pmin = 40; pmax = 80; }
  pmin -= 2; pmax += 2;
  const rowH = rollH / (pmax - pmin + 1), Y = p => rollH - (p - pmin + 1) * rowH;
  const secAt = t => { const k = lowerBound(D.sections, t + 1, s => s[0]) - 1; return k >= 0 ? D.sections[k][2] : -1; };
  for (let i = i0; i < D.src.length && D.src[i][0] <= tB; i++) {
    const s = D.src[i]; if (s[1] < tA) continue;
    const chosen = secAt(s[0]) === s[4];
    ctx.globalAlpha = chosen ? 0.35 + 0.65*s[3] : 0.12;
    ctx.fillStyle = STEMC[D.stems[s[4]]];
    ctx.fillRect(X(s[0]), Y(s[2]), Math.max(2, (s[1]-s[0])*px), Math.max(2, rowH - 1));
    if (s[5] && chosen) { ctx.strokeStyle = "#fff"; ctx.strokeRect(X(s[0]), Y(s[2]), 3, Math.max(2, rowH-1)); }
  }
  ctx.globalAlpha = 1;
  // contorno elegido (altura representativa de cada nota del chart)
  ctx.strokeStyle = "#ffffffaa"; ctx.lineWidth = 1.5; ctx.beginPath();
  const n0 = lowerBound(D.notes, tA - 2000, n => n[0]);
  let first = true;
  for (let i = n0; i < D.notes.length && D.notes[i][0] <= tB + 2000; i++) { const n = D.notes[i];
    if (!n[5]) continue;  // charts humanas: sin altura
    const y = Y(n[5]) + rowH/2; if (first) { ctx.moveTo(X(n[0]), y); first = false; } else ctx.lineTo(X(n[0]), y); }
  ctx.stroke();
  // ritmo marcado a mano (ya corregido el retardo)
  ctx.fillStyle = "#ffffff";
  // carriles
  for (let l = 0; l < 5; l++) { ctx.fillStyle = l % 2 ? "#181b22" : "#1c1f28"; ctx.fillRect(0, laneTop + (4-l)*laneH, W, laneH); }
  for (let i = n0; i < D.notes.length && D.notes[i][0] <= tB; i++) {
    const [t, frets, sus, hopo] = D.notes[i];
    for (const f of frets) {
      const cy = laneTop + (4-f)*laneH + laneH/2, r = Math.min(laneH*0.36, 14*devicePixelRatio) * (hopo ? 0.75 : 1);
      if (sus) { ctx.fillStyle = LANE[f] + "aa"; ctx.fillRect(X(t), cy - r*0.3, sus*px, r*0.6); }
      ctx.fillStyle = LANE[f]; ctx.beginPath(); ctx.arc(X(t), cy, r, 0, 7); ctx.fill();
      if (hopo) { ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(X(t), cy, r*0.4, 0, 7); ctx.fill(); }
      if (frets.length > 1) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke(); }
    }
  }
  ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x0, 0); ctx.lineTo(x0, H); ctx.stroke();
}

// ---------- vista: autopista ----------
function drawHighway(W, H, now) {
  const hw = Math.min(W * 0.5, 600 * devicePixelRatio), x0 = (W - hw)/2, lw = hw/5;
  const strike = H - 80*devicePixelRatio, pxms = strike / (Math.max(1, span/4)*1000), Y = t => strike - (t - now)*pxms;
  ctx.fillStyle = "#0b0c10"; ctx.fillRect(x0, 0, hw, H);
  const db = new Set(D.downbeats);
  for (let i = lowerBound(D.beats, now - 500, x => x); i < D.beats.length && Y(D.beats[i]) > 0; i++) {
    const b = D.beats[i]; ctx.strokeStyle = db.has(b) ? "#555" : "#262626"; ctx.lineWidth = db.has(b) ? 3 : 1;
    ctx.beginPath(); ctx.moveTo(x0, Y(b)); ctx.lineTo(x0 + hw, Y(b)); ctx.stroke(); }
  for (let l = 1; l < 5; l++) { ctx.strokeStyle = "#222"; ctx.beginPath(); ctx.moveTo(x0 + l*lw, 0); ctx.lineTo(x0 + l*lw, H); ctx.stroke(); }
  for (let l = 0; l < 5; l++) { ctx.strokeStyle = LANE[l]; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(x0 + l*lw + lw/2, strike, lw*0.32, 0, 7); ctx.stroke(); }
  for (let i = lowerBound(D.notes, now - 3000, n => n[0]); i < D.notes.length && Y(D.notes[i][0]) > -50; i++) {
    const [t, frets, sus, hopo] = D.notes[i];
    if (t + sus < now - 150) continue;
    for (const f of frets) {
      const cx = x0 + f*lw + lw/2;
      if (sus) { ctx.fillStyle = LANE[f] + "99"; ctx.fillRect(cx - lw*0.08, Y(t + sus), lw*0.16, Y(t) - Y(t + sus)); }
      if (t < now - 150) continue;
      const w = lw * (hopo ? 0.5 : 0.62), h = lw * (hopo ? 0.12 : 0.16);
      ctx.fillStyle = LANE[f]; ctx.beginPath(); ctx.roundRect(cx - w/2, Y(t) - h/2, w, h, h/2); ctx.fill();
      if (hopo) { ctx.fillStyle = "#fff"; ctx.fillRect(cx - w/4, Y(t) - 2, w/2, 4); }
    }
  }
}

// ---------- bucle ----------
function frame() {
  const W = cv.width, H = cv.height, now = (au.readyState ? au.currentTime : seekTo) * 1000;
  ctx.fillStyle = "#111318"; ctx.fillRect(0, 0, W, H);
  (view === "timeline" ? drawTimeline : drawHighway)(W, H, now);
  if (clicks && !au.paused) {
    for (let i = lowerBound(D.notes, lastT + 0.001, n => n[0]); i < D.notes.length && D.notes[i][0] <= now; i++) { click(); break; }
  }
  lastT = now;
  document.getElementById("time").textContent = `${fmt(now)} / ${fmt(D.duration)}`;
  requestAnimationFrame(frame);
}

function toggle() { if (au.paused) au.play(); else au.pause(); }
au.onplay = () => document.getElementById("play").textContent = "❚❚ Pausa";
au.onpause = () => document.getElementById("play").textContent = "▶ Play";
document.getElementById("play").onclick = toggle;
document.getElementById("view").onclick = () => { view = view === "timeline" ? "highway" : "timeline";
  document.getElementById("view").textContent = view === "timeline" ? "Autopista" : "Línea temporal"; };
document.getElementById("click").onclick = e => { clicks = !clicks; e.target.classList.toggle("on", clicks); };
document.getElementById("zoom").oninput = e => span = +e.target.value;
cv.onclick = e => { if (view !== "timeline") return toggle();
  const W = cv.width, px = W/(span*1000), x = e.offsetX*devicePixelRatio;
  au.currentTime = Math.max(0, (au.currentTime*1000 + (x - W*0.25)/px) / 1000); };
addEventListener("keydown", e => {
  if (e.code === "Space") { e.preventDefault(); toggle(); }
  else if (e.code === "ArrowRight") au.currentTime += 5;
  else if (e.code === "ArrowLeft") au.currentTime = Math.max(0, au.currentTime - 5);
  else if (e.key === "v" || e.key === "V") document.getElementById("view").click();
  else if (e.key === "c" || e.key === "C") document.getElementById("click").click();
});
addEventListener("resize", resize);
resize();
const m = location.hash.match(/t=([\d.]+)/);
seekTo = m ? +m[1] : 0;
au.addEventListener("loadedmetadata", () => { if (seekTo) au.currentTime = seekTo; });
if (location.hash.includes("highway")) document.getElementById("view").click();
requestAnimationFrame(frame);
</script>
</body>
</html>
"""
