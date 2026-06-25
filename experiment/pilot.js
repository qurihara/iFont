// ===========================================================================
// iFont セルフパイロット
//   - Loads 84 base p100 PNGs once, holds each as a Float32 ink array.
//   - For target T and parameter r ∈ [0,100], render:
//        darkness(x,y) = min(1, r/100 · ink_T + (1-r/100)/83 · Σ ink_other)
//   - Inspect mode: target dropdown + r slider (any granularity).
//   - Trial mode: random target × random r, multiple-choice + RT logging.
// ===========================================================================

// VISUAL set = 78 字: keep small ゃゅょ / っ as distinct glyphs; drop only
// ぁぃぅぇぉゎ (foreign-word only). Mirrors ifont_common.VISUAL_ALL.
const CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."がぎぐげござじずぜぞだぢづでどばびぶべぼ",
  ..."ぱぴぷぺぽ",
  ..."っゃゅょ",
  ..."ゐゑ",
  ..."ゔ",
];

// Karuta mode subset: 清音 46 + 古語 ゐ ゑ = 48 chars.
// 競技かるたで読まれる仮名 (濁点 / 半濁点 / 小文字 / ゔ は除外).
const KARUTA_CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."ゐゑ",
];

// 50音 layout for the 84-choice grid. Empty strings render as spacers so the
// あ/か/さ... rows line up visually and finding a kana is fast.
const GRID_84 = [
  // 清音
  ["あ","い","う","え","お"],
  ["か","き","く","け","こ"],
  ["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],
  ["な","に","ぬ","ね","の"],
  ["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],
  ["や","",  "ゆ","",  "よ"],
  ["ら","り","る","れ","ろ"],
  ["わ","",  "",  "",  "を"],
  ["ん","",  "",  "",  ""  ],
  // 濁音
  ["が","ぎ","ぐ","げ","ご"],
  ["ざ","じ","ず","ぜ","ぞ"],
  ["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],
  // 半濁音
  ["ぱ","ぴ","ぷ","ぺ","ぽ"],
  // 小書き (ゃゅょ / っ のみ。ぁぃぅぇぉゎ は除外)
  ["ゃ","",  "ゅ","",  "ょ"],
  ["っ","",  "",  "",  ""  ],
  // 古語
  ["ゐ","",  "",  "",  "ゑ"],
  // その他 (合拗音)
  ["ゔ","",  "",  "",  ""  ],
];

// Karuta grid: subset of GRID_84 with dakuten / handakuten / small / ゔ rows
// dropped. Keeps ゐ ゑ row.
const GRID_KARUTA = [
  ...GRID_84.slice(0, 11),     // 清音 11 rows
  GRID_84[GRID_84.length - 2], // ゐ ゑ row
];

const SIZE = 256;
const N_PIXELS = SIZE * SIZE;

// State
let inkArrays = null;          // {char: Float32Array(N_PIXELS), values 0..1 (ink=1)}
let inkSumAll = null;           // sum of all 84 inks
let inkSumKaruta = null;        // sum of 48 karuta inks
let simAll = null, simKaruta = null;  // similarity rankings per mode
let canvas, ctx, imgData;
let mode = "inspect";

// Active char set + dependent caches. setActiveSet() updates these.
let activeChars = CHARS;
let activeGrid = GRID_84;
let activeInkSum = null;
let activeSim = null;

function activeSetName() {
  const sel = document.getElementById("qSet");
  return sel ? sel.value : "all";
}

function setActiveSet(name) {
  if (name === "karuta") {
    activeChars = KARUTA_CHARS;
    activeGrid = GRID_KARUTA;
    activeInkSum = inkSumKaruta;
    activeSim = simKaruta;
  } else {
    activeChars = CHARS;
    activeGrid = GRID_84;
    activeInkSum = inkSumAll;
    activeSim = simAll;
  }
}

// Trial state
let currentTrial = null;
let trialLog = [];
let lastCorrect = true;
let lastR = 50;
let pendingTimer = null;       // setTimeout handle for inter-trial blank
const ITI_MS = 1000;           // inter-trial blank duration (ms)

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// r ↔ k conversions
//   k = α_target / α_distractor = N·r / (100 - r)         (r in %, N = #distractors)
//   r = 100·k / (N + k)
// k = 1 means target equals each distractor in opacity (visually no advantage).
// k = ∞ means r = 100 (only target visible).
// N depends on the active char set: 83 for 全字, 47 for 競技かるた.
// ---------------------------------------------------------------------------
function nDistr() { return activeChars.length - 1; }
function rToK(r, n) {
  const N = (n == null) ? nDistr() : n;
  if (r >= 100) return Infinity;
  return N * r / (100 - r);
}
function kToR(k, n) {
  const N = (n == null) ? nDistr() : n;
  if (!isFinite(k)) return 100;
  return 100 * k / (N + k);
}
function fmtK(k) {
  if (!isFinite(k)) return "∞";
  if (k >= 100) return k.toFixed(0);
  if (k >= 10) return k.toFixed(1);
  return k.toFixed(2);
}

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
  inkSumAll    = computeInkSum(CHARS);
  inkSumKaruta = computeInkSum(KARUTA_CHARS);
  $("stageInfo").textContent = `${CHARS.length} 字 ロード完了。類似度を計算中…`;
  simAll    = computeSimilarity(CHARS);
  simKaruta = computeSimilarity(KARUTA_CHARS);
  setActiveSet(activeSetName());
  $("stageInfo").textContent = `${CHARS.length} 字 ロード完了`;
}

function computeInkSum(charSet) {
  const sum = new Float32Array(N_PIXELS);
  for (const c of charSet) {
    const a = inkArrays[c];
    for (let i = 0; i < N_PIXELS; i++) sum[i] += a[i];
  }
  return sum;
}

function computeSimilarity(charSet) {
  // Pixel overlap (dot product) → cosine sim. ranking[c] = [other chars
  // sorted by descending similarity], restricted to charSet.
  const norms = {};
  for (const c of charSet) {
    let s = 0; const a = inkArrays[c];
    for (let i = 0; i < N_PIXELS; i++) s += a[i] * a[i];
    norms[c] = Math.sqrt(s);
  }
  const ranking = {};
  for (const ct of charSet) {
    const at = inkArrays[ct];
    const sims = [];
    for (const co of charSet) {
      if (co === ct) continue;
      const ao = inkArrays[co];
      let dot = 0;
      for (let i = 0; i < N_PIXELS; i++) dot += at[i] * ao[i];
      sims.push([co, dot / (norms[ct] * norms[co] + 1e-9)]);
    }
    sims.sort((a, b) => b[1] - a[1]);
    ranking[ct] = sims.map(s => s[0]);
  }
  return ranking;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function blankCanvas() {
  const out = imgData.data;
  for (let i = 0; i < out.length; i += 4) {
    out[i] = 255; out[i + 1] = 255; out[i + 2] = 255; out[i + 3] = 255;
  }
  ctx.putImageData(imgData, 0, 0);
  $("stageInfo").textContent = "…";
}

function render(target, r) {
  const N = nDistr();
  const wTarget = r / 100;
  const wDistr = (1 - wTarget) / N;
  const tgt = inkArrays[target];
  const out = imgData.data;
  for (let i = 0, p = 0; i < N_PIXELS; i++, p += 4) {
    const distrSum = activeInkSum[i] - tgt[i];   // sum of N distractors
    let darkness = wTarget * tgt[i] + wDistr * distrSum;
    if (darkness > 1) darkness = 1;
    const v = Math.round(255 * (1 - darkness));
    out[p] = v; out[p + 1] = v; out[p + 2] = v; out[p + 3] = 255;
  }
  ctx.putImageData(imgData, 0, 0);
  const kVal = rToK(r);
  const setName = activeChars === KARUTA_CHARS ? "karuta 48" : "全 84";
  $("stageInfo").textContent =
    `target=${target}, r=${r.toFixed(2)}%, k=${fmtK(kVal)} (${setName}字 中)`;
}

// ---------------------------------------------------------------------------
// Inspect mode
// ---------------------------------------------------------------------------

function populateCharSelect() {
  const sel = $("charSelect");
  sel.innerHTML = "";
  for (const c of activeChars) {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    sel.appendChild(opt);
  }
  sel.value = activeChars.includes("あ") ? "あ" : activeChars[0];
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
  } else if (dist === "lowFine") {
    r = Math.random() * 10;
  } else if (dist === "lowVeryFine") {
    r = Math.random() * 5;
  } else if (dist === "logK") {
    // Log-uniform in k ∈ [0.5, 128] (8 octaves). Perceptual-spacing default.
    const logK = -1 + Math.random() * 8;  // log2(0.5)=-1, log2(128)=7
    r = kToR(Math.pow(2, logK));
  } else if (dist === "logKWide") {
    // Wider: k ∈ [0.25, 256]
    const logK = -2 + Math.random() * 10;
    r = kToR(Math.pow(2, logK));
  } else if (dist === "kGrid11") {
    // Discrete 11-level k grid (the proposed main-experiment levels)
    const grid = [0, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, Infinity];
    const k = grid[Math.floor(Math.random() * grid.length)];
    r = kToR(k);
  } else if (dist === "thresholdHunt") {
    r = 20 + Math.random() * 60;
  } else { // adaptive (in k space: ÷√2 on correct, ×√2 on wrong → ±0.5 log2 step)
    const cur = rToK(lastR);
    const next = lastCorrect ? cur / Math.SQRT2 : cur * Math.SQRT2;
    r = kToR(Math.min(1024, Math.max(0.1, next)));
  }
  // Quantize to step (only if step > 0)
  if (step > 0) r = Math.round(r / step) * step;
  return Math.max(0, Math.min(100, r));
}

function pickDistractors(target, n) {
  const dm = $("distractorMode").value;
  if (dm === "similar") {
    // Top-n most similar (within active char set)
    return activeSim[target].slice(0, n);
  }
  // Random within active char set
  const pool = activeChars.filter(c => c !== target);
  for (let i = 0; i < n; i++) {
    const j = i + Math.floor(Math.random() * (pool.length - i));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  return pool.slice(0, n);
}

function buildChoicesUI(choices, isFullGrid) {
  const div = $("choices");
  div.innerHTML = "";
  div.classList.toggle("grid84", isFullGrid);
  if (isFullGrid) {
    // Render the fixed 50音 grid (active set) so participants can find any kana fast.
    for (const row of activeGrid) {
      for (const ch of row) {
        if (ch === "") {
          const s = document.createElement("span");
          s.className = "spacer";
          div.appendChild(s);
        } else {
          const b = document.createElement("button");
          b.textContent = ch;
          b.onclick = () => answerTrial(ch);
          div.appendChild(b);
        }
      }
    }
  } else {
    for (const ch of choices) {
      const b = document.createElement("button");
      b.textContent = ch;
      b.onclick = () => answerTrial(ch);
      div.appendChild(b);
    }
  }
  // Optional "don't know" button (appended after grid/list)
  if ($("dontKnow").value === "on") {
    const b = document.createElement("button");
    b.textContent = "?";
    b.title = "わからない";
    b.style.color = "#777";
    b.onclick = () => answerTrial("__dontknow__");
    div.appendChild(b);
  }
}

function startTrial() {
  if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null; }
  const target = activeChars[Math.floor(Math.random() * activeChars.length)];
  const r = pickR();
  const k = parseInt($("choiceCount").value);
  const isFullGrid = (k >= activeChars.length);
  let choices;
  if (isFullGrid) {
    // Full grid: no shuffle; layout is the fixed 50音 grid restricted to the
    // active set. Record activeChars so γ (= 1/N) is correctly attributed.
    choices = activeChars.slice();
  } else {
    choices = [target, ...pickDistractors(target, k - 1)];
    for (let i = choices.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [choices[i], choices[j]] = [choices[j], choices[i]];
    }
  }
  currentTrial = { target, r, choices, t0: performance.now() };
  render(target, r);
  // Hide the diagnostic readout so the answer doesn't leak during trials.
  $("stageInfo").textContent = "回答してください";
  $("feedback").style.display = "none";
  buildChoicesUI(choices, isFullGrid);

  // Focus the kana input so a hardware keyboard / IME can answer too.
  const ki = $("kanaInput");
  if (ki) { ki.value = ""; ki.focus({preventScroll: true}); }
}

function answerTrial(response) {
  if (!currentTrial) return;
  const rt = performance.now() - currentTrial.t0;
  const isDontKnow = response === "__dontknow__";
  const correct = !isDontKnow && response === currentTrial.target;
  trialLog.push({
    target: currentTrial.target,
    r: currentTrial.r,
    k: rToK(currentTrial.r, currentTrial.choices.length - 1),
    response,
    correct,
    is_dontknow: isDontKnow,
    n_choices: currentTrial.choices.length,
    q_set: activeChars === KARUTA_CHARS ? "karuta" : "all",
    distractor_mode: $("distractorMode").value,
    rt_ms: Math.round(rt),
  });
  // Adaptive uses correctness only (don't-know counts as wrong: increase r)
  lastCorrect = correct;
  lastR = currentTrial.r;

  const fb = $("feedback");
  const kVal = rToK(currentTrial.r);
  const tail = `r=${currentTrial.r.toFixed(2)}%, k=${fmtK(kVal)}, ${Math.round(rt)} ms`;
  let cls, msg;
  if (isDontKnow) {
    cls = "wrong";
    msg = `— わからない → target was "${currentTrial.target}" (${tail})`;
  } else if (correct) {
    cls = "correct";
    msg = `✓ 正解 (target=${currentTrial.target}, ${tail})`;
  } else {
    cls = "wrong";
    msg = `✗ 不正解 → target was "${currentTrial.target}" (${tail})`;
  }
  fb.className = "feedback " + cls;
  fb.textContent = msg;
  fb.style.display = "inline-block";
  // Disable choice buttons and blank the stimulus immediately to avoid
  // retinal afterimage carrying over into the next trial.
  for (const b of $("choices").querySelectorAll("button")) b.disabled = true;
  blankCanvas();

  currentTrial = null;
  drawStats();

  // Auto-advance after ITI_MS, unless the user switched modes.
  pendingTimer = setTimeout(() => {
    pendingTimer = null;
    if (mode === "trial") startTrial();
  }, ITI_MS);
}

function resetTrials() {
  trialLog = [];
  drawStats();
}

function downloadTrials() {
  const header = "trial_idx,target,r,k,response,correct,is_dontknow,n_choices,q_set,distractor_mode,rt_ms";
  const rows = trialLog.map((t, i) =>
    [i + 1, t.target, t.r,
     (isFinite(t.k) ? t.k.toFixed(4) : "Inf"),
     t.response, t.correct, t.is_dontknow,
     t.n_choices, t.q_set || "all", t.distractor_mode, t.rt_ms].join(","));
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
  $("chartAxis").addEventListener("change", drawStats);
  $("rDist").addEventListener("change", drawStats);  // auto-axis follows rDist

  // Keyboard/IME input: any single hiragana that matches a current choice
  // is submitted as the response. Works on desktop with IME and on mobile
  // with a software kana keyboard.
  const ki = $("kanaInput");
  if (ki) {
    const submitFromInput = () => {
      if (mode !== "trial" || !currentTrial) return;
      const v = ki.value.trim();
      if (!v.length) return;
      const ch = v.slice(-1);   // last char (in case of multi-char input)
      // Accept any active-set kana; if outside the set, ignore and let user
      // re-type. Don't accept dakuten/small when in karuta mode.
      if (activeChars.includes(ch)) {
        ki.value = "";
        answerTrial(ch);
      }
    };
    ki.addEventListener("input", submitFromInput);
    ki.addEventListener("compositionend", submitFromInput);
  }
  document.addEventListener("keydown", (e) => {
    if (mode !== "trial") return;
    // Space starts a new trial only when no input has focus (so it doesn't
    // collide with typing a kana via IME).
    if (e.key === " " && document.activeElement?.id !== "kanaInput") {
      e.preventDefault();
      if (!currentTrial && !pendingTimer) startTrial();
    }
  });
}

// ---------------------------------------------------------------------------
// Stats / chart
// ---------------------------------------------------------------------------

function chartAxisMode() {
  const sel = $("chartAxis").value;
  if (sel !== "auto") return sel;
  // Auto: log-k for k-based r distributions, r% otherwise.
  const dist = $("rDist").value;
  return (dist === "logK" || dist === "logKWide" || dist === "kGrid11" || dist === "adaptive")
    ? "logK" : "r";
}

function drawStats() {
  const can = $("chartCanvas");
  const c = can.getContext("2d");
  const w = can.width, h = can.height;
  c.clearRect(0, 0, w, h);

  const axis = chartAxisMode();
  let bins, labels, axisLabel, binW;

  if (axis === "logK") {
    // Bin in half-octave log2 k steps, from log2(0.25)=-2 to log2(256)=8.
    const lo = -2, hi = 8;
    binW = 0.5;
    const nB = Math.round((hi - lo) / binW) + 1; // +1 for k=∞
    bins = Array.from({length: nB}, () => ({n: 0, correct: 0}));
    labels = [];
    for (let i = 0; i < nB - 1; i++) labels.push(Math.pow(2, lo + i * binW));
    labels.push(Infinity);
    for (const t of trialLog) {
      let bi;
      if (!isFinite(t.k)) bi = nB - 1;
      else if (t.k <= 0)  bi = 0;
      else {
        const l = Math.log2(t.k);
        bi = Math.max(0, Math.min(nB - 2, Math.floor((l - lo) / binW)));
      }
      bins[bi].n++;
      if (t.correct) bins[bi].correct++;
    }
    axisLabel = "k (½ octave bin)";
  } else {
    const maxR = trialLog.length ? Math.max(...trialLog.map(t => t.r)) : 100;
    binW = maxR <= 5 ? 0.5 : maxR <= 10 ? 1 : maxR <= 20 ? 2 : 10;
    const nB = Math.ceil(Math.max(maxR, 10) / binW) + 1;
    bins = Array.from({length: nB}, () => ({n: 0, correct: 0}));
    labels = [];
    for (let i = 0; i < nB; i++) labels.push(i * binW);
    for (const t of trialLog) {
      const bi = Math.min(nB - 1, Math.floor(t.r / binW));
      bins[bi].n++;
      if (t.correct) bins[bi].correct++;
    }
    axisLabel = `r% (bin=${binW})`;
  }

  // y-axis grid
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
  const nVisible = bins.length;
  const barW = (w - 50) / nVisible;
  const labelStep = Math.max(1, Math.round(nVisible / 12));
  for (let i = 0; i < nVisible; i++) {
    const b = bins[i];
    const x = 42 + i * barW;
    if (b.n > 0) {
      const acc = b.correct / b.n;
      const bh = acc * (h - 34);
      c.fillStyle = "#4a76d6";
      c.fillRect(x, h - 24 - bh, Math.max(1, barW - 2), bh);
      c.fillStyle = "#222";
      c.fillText(b.n, x + 2, h - 12);
    }
    if (i % labelStep === 0) {
      const lbl = labels[i];
      const lblStr = !isFinite(lbl) ? "∞"
        : (axis === "logK" ? fmtK(lbl) : lbl.toFixed(binW < 1 ? 1 : 0));
      c.fillStyle = "#666";
      c.fillText(lblStr, x + 2, h - 2);
    }
  }
  c.fillStyle = "#999";
  c.fillText(axisLabel, w - 130, h - 2);

  // ----- 2-parameter logistic fit overlay -----
  const fit = fitLogistic(trialLog, axis);
  if (fit) {
    // Map data x to canvas px. Bin i (0..nVisible-1) spans canvas
    // [42 + i*barW, 42 + (i+1)*barW] and represents data x covering
    // either r%∈[i*binW,(i+1)*binW] (r-axis) or k∈[2^(lo+i*binW), 2^(lo+(i+1)*binW)] (log-k).
    let xMin, xMax, dataToBinIdx;
    if (axis === "logK") {
      const lo = -2;
      xMin = lo; xMax = lo + (nVisible - 1) * binW;   // last bin is k=∞ sentinel
      dataToBinIdx = (x) => (x - lo) / binW;
    } else {
      xMin = 0; xMax = (nVisible - 1) * binW;
      dataToBinIdx = (x) => x / binW;
    }

    c.strokeStyle = "#d63a3a";
    c.lineWidth = 2;
    c.beginPath();
    const SAMPLES = 200;
    for (let i = 0; i <= SAMPLES; i++) {
      const x = xMin + (xMax - xMin) * i / SAMPLES;
      const p = logisticP(x, fit);
      const px = 42 + (dataToBinIdx(x) + 0.5) * barW;
      const py = (h - 24) - p * (h - 34);
      if (i === 0) c.moveTo(px, py); else c.lineTo(px, py);
    }
    c.stroke();

    // Mark α: the model threshold (p = (1+γ)/2 = chance/ceiling midpoint).
    // For 4-choice (γ=0.25) this corresponds to p≈0.625, NOT 0.75.
    const pAtAlpha = fit.gamma + (1 - fit.gamma) * 0.5;
    if (fit.alpha >= xMin && fit.alpha <= xMax) {
      const pxA = 42 + (dataToBinIdx(fit.alpha) + 0.5) * barW;
      const pyA = (h - 24) - pAtAlpha * (h - 34);
      c.fillStyle = "#d63a3a";
      c.beginPath(); c.arc(pxA, pyA, 5, 0, 2 * Math.PI); c.fill();
      c.strokeStyle = "#d63a3a"; c.setLineDash([2, 3]);
      c.beginPath(); c.moveTo(pxA, h - 24); c.lineTo(pxA, pyA); c.stroke();
      c.setLineDash([]);
    }

    // Caption: α as natural-unit threshold, plus interpretation.
    let alphaUnit;
    if (axis === "logK") {
      const kAtAlpha = Math.pow(2, fit.alpha);
      alphaUnit = `log₂k=${fit.alpha.toFixed(2)} (k≈${fmtK(kAtAlpha)}, r≈${kToR(kAtAlpha).toFixed(2)}%)`;
    } else {
      alphaUnit = `r=${fit.alpha.toFixed(2)}%`;
    }
    const info = `2P logistic fit:  α=${fit.alpha.toFixed(2)}  β=${fit.beta.toFixed(2)}  γ=${fit.gamma.toFixed(2)}  pseudoR²=${fit.pseudoR2.toFixed(2)}  (n=${fit.n})\n`
      + `⌀ 閾値 α (= chance/ceiling 中点, p=${pAtAlpha.toFixed(3)}): ${alphaUnit}`;
    $("fitInfo").textContent = info;
    $("fitInfo").style.whiteSpace = "pre";
  } else {
    $("fitInfo").textContent = trialLog.length >= 8
      ? "(全問同じ正誤またはデータ不足のため未フィット)"
      : `(フィットには 8 試行以上必要・現在 ${trialLog.length} 試行)`;
  }

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
// 2-parameter logistic regression with fixed chance level γ.
//   model:  p(correct) = γ + (1 - γ) · 1 / (1 + exp(-β · (x - α)))
//   params: α (threshold where target-only-corrected prob = 0.5), β (slope).
//   γ is per-trial, derived from n_choices on each row (4-choice → 0.25 etc.).
// Fit via coarse-to-fine grid search of the log-likelihood (robust, ~5 ms
// for ≤500 trials, no external libraries).
// ---------------------------------------------------------------------------
function logL(data, alpha, beta) {
  let ll = 0;
  for (const [x, y, gamma] of data) {
    const z = beta * (x - alpha);
    const sig = z >= 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z));
    let p = gamma + (1 - gamma) * sig;
    if (p < 1e-9) p = 1e-9; else if (p > 1 - 1e-9) p = 1 - 1e-9;
    ll += y * Math.log(p) + (1 - y) * Math.log(1 - p);
  }
  return ll;
}

function fitLogistic(trials, axis) {
  // Build (x, y, γ) tuples filtering "don't know" responses.
  const data = [];
  for (const t of trials) {
    if (t.is_dontknow) continue;
    let x;
    if (axis === "logK") {
      if (!isFinite(t.k)) x = 10;        // clip k=∞ at log2=10
      else if (t.k <= 1e-3) x = -10;
      else x = Math.log2(t.k);
    } else {
      x = t.r;
    }
    const gamma = 1 / Math.max(2, t.n_choices || 4);
    data.push([x, t.correct ? 1 : 0, gamma]);
  }
  if (data.length < 8) return null;
  // Sanity: need both correct and incorrect responses.
  const nc = data.filter(d => d[1] === 1).length;
  if (nc === 0 || nc === data.length) return null;

  // Initial coarse search bounds.
  let aLo, aHi, bLo, bHi;
  if (axis === "logK") { aLo = -3; aHi = 10; bLo = 0.05; bHi = 8; }
  else                 { aLo = 0;  aHi = 100; bLo = 0.005; bHi = 1.5; }

  let bestA = (aLo + aHi) / 2, bestB = (bLo + bHi) / 2, bestLL = -Infinity;
  const N = 30;
  for (let pass = 0; pass < 4; pass++) {
    let ca = bestA, cb = bestB, cll = bestLL;
    for (let i = 0; i <= N; i++) {
      const a = aLo + (aHi - aLo) * i / N;
      for (let j = 0; j <= N; j++) {
        const b = bLo + (bHi - bLo) * j / N;
        const ll = logL(data, a, b);
        if (ll > cll) { cll = ll; ca = a; cb = b; }
      }
    }
    bestA = ca; bestB = cb; bestLL = cll;
    // Zoom: window ±2 cells around best, on a finer grid.
    const aSpan = (aHi - aLo) / N * 2;
    const bSpan = (bHi - bLo) / N * 2;
    aLo = bestA - aSpan; aHi = bestA + aSpan;
    bLo = Math.max(1e-4, bestB - bSpan); bHi = bestB + bSpan;
  }

  // Pseudo R^2 (McFadden):  1 − ll_fit / ll_null, where null model is
  // constant p = mean accuracy (with γ-corrected sigmoid contribution = 0).
  const meanAcc = data.reduce((s, d) => s + d[1], 0) / data.length;
  let llNull = 0;
  for (const [, y] of data) {
    const p = Math.max(1e-9, Math.min(1 - 1e-9, meanAcc));
    llNull += y * Math.log(p) + (1 - y) * Math.log(1 - p);
  }
  const r2 = llNull < 0 ? 1 - bestLL / llNull : 0;

  // Average γ for the drawn curve (use mode of n_choices).
  const counts = {};
  for (const [, , g] of data) counts[g] = (counts[g] || 0) + 1;
  const modalGamma = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])[0][0] * 1;

  return {alpha: bestA, beta: bestB, gamma: modalGamma, n: data.length,
          logL: bestLL, pseudoR2: r2};
}

// p(x) curve evaluator (uses the modal γ for display).
function logisticP(x, fit) {
  const z = fit.beta * (x - fit.alpha);
  const sig = z >= 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z));
  return fit.gamma + (1 - fit.gamma) * sig;
}

// ---------------------------------------------------------------------------
// Mode switching
// ---------------------------------------------------------------------------

function setMode(m) {
  // Cancel any pending auto-advance when leaving trial mode.
  if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null; }
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
  $("qSet").addEventListener("change", () => {
    setActiveSet($("qSet").value);
    populateCharSelect();
    if (mode === "inspect") inspectRender();
  });

  await loadAll();
  setupInspect();
  setupTrial();
  drawStats();
  setMode("inspect");
}

boot().catch(e => {
  document.body.innerHTML = `<p style="padding:40px;color:#900">起動エラー: ${e.message}</p>`;
});
