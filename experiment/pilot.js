// ===========================================================================
// iFont セルフパイロット
//   - Loads 84 base p100 PNGs once, holds each as a Float32 ink array.
//   - For target T and parameter r ∈ [0,100], render:
//        darkness(x,y) = min(1, r/100 · ink_T + (1-r/100)/83 · Σ ink_other)
//   - Inspect mode: target dropdown + r slider (any granularity).
//   - Trial mode: random target × random r, multiple-choice + RT logging.
// ===========================================================================

const CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."がぎぐげござじずぜぞだぢづでどばびぶべぼ",
  ..."ぱぴぷぺぽ",
  ..."ぁぃぅぇぉっゃゅょゎ",
  ..."ゐゑ",
  ..."ゔ",
];

const SIZE = 256;
const N_PIXELS = SIZE * SIZE;

// State
let inkArrays = null;          // {char: Float32Array(N_PIXELS), values 0..1 (ink=1)}
let inkSum = null;             // Float32Array, sum of all 84 inks
let canvas, ctx, imgData;
let mode = "inspect";

// Trial state
let currentTrial = null;
let trialLog = [];
let lastCorrect = true;
let lastR = 50;

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Load base images
// ---------------------------------------------------------------------------

function loadImage(path) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("load failed: " + path));
    img.src = path;
  });
}

async function loadInkArray(char) {
  const img = await loadImage(`base/${encodeURIComponent(char)}.png`);
  const off = document.createElement("canvas");
  off.width = SIZE; off.height = SIZE;
  const octx = off.getContext("2d");
  octx.drawImage(img, 0, 0, SIZE, SIZE);
  const d = octx.getImageData(0, 0, SIZE, SIZE).data;
  // p100.png is white bg (255), black ink (0). ink density = (255 - R) / 255.
  const out = new Float32Array(N_PIXELS);
  for (let i = 0, p = 0; i < d.length; i += 4, p++) {
    out[p] = (255 - d[i]) / 255;
  }
  return out;
}

async function loadAll() {
  $("stageInfo").textContent = "ベース画像を読み込み中...";
  inkArrays = {};
  for (let i = 0; i < CHARS.length; i++) {
    inkArrays[CHARS[i]] = await loadInkArray(CHARS[i]);
  }
  // Pre-compute the sum once (for fast distractor composition).
  inkSum = new Float32Array(N_PIXELS);
  for (const c of CHARS) {
    const a = inkArrays[c];
    for (let i = 0; i < N_PIXELS; i++) inkSum[i] += a[i];
  }
  $("stageInfo").textContent = `${CHARS.length} 字 ロード完了`;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function render(target, r) {
  const wTarget = r / 100;
  const wDistr = (1 - wTarget) / 83;
  const tgt = inkArrays[target];
  const out = imgData.data;
  for (let i = 0, k = 0; i < N_PIXELS; i++, k += 4) {
    const distrSum = inkSum[i] - tgt[i];   // sum of 83 distractors
    let darkness = wTarget * tgt[i] + wDistr * distrSum;
    if (darkness > 1) darkness = 1;
    const v = Math.round(255 * (1 - darkness));
    out[k] = v; out[k + 1] = v; out[k + 2] = v; out[k + 3] = 255;
  }
  ctx.putImageData(imgData, 0, 0);
  $("stageInfo").textContent = `target=${target}, r=${r.toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Inspect mode
// ---------------------------------------------------------------------------

function populateCharSelect() {
  const sel = $("charSelect");
  for (const c of CHARS) {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    sel.appendChild(opt);
  }
  sel.value = "あ";
}

function inspectRender() {
  const ch = $("charSelect").value;
  const r = parseFloat($("rSlider").value);
  $("rValue").textContent = r.toFixed(1);
  render(ch, r);
}

function setupInspect() {
  populateCharSelect();
  $("charSelect").addEventListener("change", inspectRender);
  $("rSlider").addEventListener("input", inspectRender);
  $("stepSelect").addEventListener("change", () => {
    $("rSlider").step = $("stepSelect").value;
  });
  document.addEventListener("keydown", (e) => {
    if (mode !== "inspect") return;
    const step = parseFloat($("stepSelect").value);
    const slider = $("rSlider");
    if (e.key === "ArrowLeft") {
      slider.value = Math.max(0, parseFloat(slider.value) - step);
      inspectRender();
    } else if (e.key === "ArrowRight") {
      slider.value = Math.min(100, parseFloat(slider.value) + step);
      inspectRender();
    }
  });
  inspectRender();
}

// ---------------------------------------------------------------------------
// Trial mode
// ---------------------------------------------------------------------------

function pickR() {
  const dist = $("rDist").value;
  const step = parseFloat($("trialStep").value);
  let r;
  if (dist === "uniform") {
    r = Math.random() * 100;
  } else if (dist === "thresholdHunt") {
    r = 20 + Math.random() * 60;
  } else { // adaptive
    if (lastCorrect) r = Math.max(0, lastR - 5);
    else             r = Math.min(100, lastR + 5);
  }
  // Quantize to step
  r = Math.round(r / step) * step;
  return r;
}

function pickDistractors(target, n = 3) {
  const pool = CHARS.filter(c => c !== target);
  // Fisher-Yates shuffle of small sample
  for (let i = 0; i < n; i++) {
    const j = i + Math.floor(Math.random() * (pool.length - i));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  return pool.slice(0, n);
}

function startTrial() {
  const target = CHARS[Math.floor(Math.random() * CHARS.length)];
  const r = pickR();
  const choices = [target, ...pickDistractors(target, 3)];
  for (let i = choices.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [choices[i], choices[j]] = [choices[j], choices[i]];
  }
  currentTrial = { target, r, choices, t0: performance.now() };
  render(target, r);

  $("feedback").style.display = "none";
  const div = $("choices");
  div.innerHTML = "";
  for (const ch of choices) {
    const b = document.createElement("button");
    b.textContent = ch;
    b.onclick = () => answerTrial(ch);
    div.appendChild(b);
  }
}

function answerTrial(response) {
  if (!currentTrial) return;
  const rt = performance.now() - currentTrial.t0;
  const correct = response === currentTrial.target;
  trialLog.push({
    target: currentTrial.target,
    r: currentTrial.r,
    response,
    correct,
    rt_ms: Math.round(rt),
  });
  lastCorrect = correct;
  lastR = currentTrial.r;

  const fb = $("feedback");
  fb.className = "feedback " + (correct ? "correct" : "wrong");
  fb.textContent = correct
    ? `✓ 正解 (target=${currentTrial.target}, r=${currentTrial.r.toFixed(1)}%, ${Math.round(rt)} ms)`
    : `✗ 不正解 → target was "${currentTrial.target}" (r=${currentTrial.r.toFixed(1)}%, ${Math.round(rt)} ms)`;
  fb.style.display = "inline-block";
  // Disable choice buttons
  for (const b of $("choices").querySelectorAll("button")) b.disabled = true;

  currentTrial = null;
  drawStats();
}

function resetTrials() {
  trialLog = [];
  drawStats();
}

function downloadTrials() {
  const header = "trial_idx,target,r,response,correct,rt_ms";
  const rows = trialLog.map((t, i) =>
    [i + 1, t.target, t.r, t.response, t.correct, t.rt_ms].join(","));
  const blob = new Blob([header + "\n" + rows.join("\n")], {type: "text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `pilot_trials_${new Date().toISOString().slice(0,19).replace(/[:T]/g,"-")}.csv`;
  a.click();
}

function setupTrial() {
  $("startTrial").onclick = startTrial;
  $("resetTrials").onclick = resetTrials;
  $("downloadTrials").onclick = downloadTrials;
  document.addEventListener("keydown", (e) => {
    if (mode !== "trial") return;
    if (e.key === " ") {
      e.preventDefault();
      if (!currentTrial) startTrial();
    } else if (currentTrial && /^[1-4]$/.test(e.key)) {
      const idx = parseInt(e.key) - 1;
      const buttons = $("choices").querySelectorAll("button");
      if (buttons[idx] && !buttons[idx].disabled) buttons[idx].click();
    }
  });
}

// ---------------------------------------------------------------------------
// Stats / chart
// ---------------------------------------------------------------------------

function drawStats() {
  const can = $("chartCanvas");
  const c = can.getContext("2d");
  const w = can.width, h = can.height;
  c.clearRect(0, 0, w, h);

  // Bin trials by r in 10% bins. Show accuracy bars + raw counts.
  const bins = Array.from({length: 11}, () => ({n: 0, correct: 0}));
  for (const t of trialLog) {
    const b = Math.min(10, Math.floor(t.r / 10));
    bins[b].n++;
    if (t.correct) bins[b].correct++;
  }

  // Draw axes
  c.strokeStyle = "#ccc"; c.lineWidth = 1;
  c.beginPath(); c.moveTo(40, 10); c.lineTo(40, h - 24); c.lineTo(w - 10, h - 24); c.stroke();
  c.fillStyle = "#666"; c.font = "10px monospace";
  for (let y = 0; y <= 4; y++) {
    const py = 10 + (h - 34) * y / 4;
    c.fillText((100 - y * 25) + "%", 4, py + 4);
    c.strokeStyle = "#eee";
    c.beginPath(); c.moveTo(40, py); c.lineTo(w - 10, py); c.stroke();
  }
  // Bars
  const barW = (w - 50) / 11;
  for (let i = 0; i < 11; i++) {
    const b = bins[i];
    if (b.n === 0) continue;
    const acc = b.correct / b.n;
    const bh = acc * (h - 34);
    c.fillStyle = "#4a76d6";
    c.fillRect(42 + i * barW, h - 24 - bh, barW - 2, bh);
    c.fillStyle = "#222";
    c.fillText(b.n, 42 + i * barW + 2, h - 12);
    c.fillStyle = "#666";
    c.fillText((i * 10) + "", 42 + i * barW + 2, h - 2);
  }
  c.fillStyle = "#999";
  c.fillText("r% →", w - 36, h - 2);

  // Text table
  const total = trialLog.length;
  const totalCorrect = trialLog.filter(t => t.correct).length;
  let html = `<table>
    <tr><th>n</th><th>正答</th><th>正答率</th><th>中央RT</th></tr>`;
  const rtMed = total ? median(trialLog.map(t => t.rt_ms)) : 0;
  html += `<tr><td>${total}</td><td>${totalCorrect}</td>
    <td>${total ? (100 * totalCorrect / total).toFixed(1) : "—"}%</td>
    <td>${rtMed.toFixed(0)} ms</td></tr></table>`;
  $("statsTable").innerHTML = html;
}

function median(xs) {
  if (!xs.length) return 0;
  const s = xs.slice().sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// ---------------------------------------------------------------------------
// Mode switching
// ---------------------------------------------------------------------------

function setMode(m) {
  mode = m;
  $("modeInspect").classList.toggle("active", m === "inspect");
  $("modeTrial").classList.toggle("active", m === "trial");
  $("inspectPanel").style.display = m === "inspect" ? "" : "none";
  $("trialPanel").style.display = m === "trial" ? "" : "none";
  if (m === "inspect") inspectRender();
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  canvas = $("stage");
  ctx = canvas.getContext("2d");
  imgData = ctx.createImageData(SIZE, SIZE);

  $("modeInspect").onclick = () => setMode("inspect");
  $("modeTrial").onclick = () => setMode("trial");

  await loadAll();
  setupInspect();
  setupTrial();
  drawStats();
  setMode("inspect");
}

boot().catch(e => {
  document.body.innerHTML = `<p style="padding:40px;color:#900">起動エラー: ${e.message}</p>`;
});
