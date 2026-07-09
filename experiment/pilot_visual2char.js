// ===========================================================================
// iFont 視覚2文字セルフパイロット — 時間変化提示 (2026-07-02 設計改訂版)
//   - 固定領域(256px)に C1→C2 を各 0.2 秒で提示。前の文字は一瞬で消去。
//   - 0.2 秒の中で認識度が上がる提示アルゴリズムを複数実装して比較する:
//       fade   透明度 0→1
//       stroke ストローク画素をランダム順に累積 (加算型マスクの動画化)
//       zoom   中心から拡大 0→1
//       blur   ぼかし 12px→0 (くっきり化)
//       moya   全78字の平均画像から目標字へクロスフェード (減算型の近似)
//   - C2 は frac% 時点で消去 = 聴覚 truncation の視覚アナログ。
//   - Trial: ランダムな C1,C2 (全78字から一様)、50音グリッド回答、2P logistic。
//   - 文字画像は experiment/base/<char>.png (256px, 白地に黒ストローク) を
//     クライアント側で合成する (pilot.js / pilot_audio.js と同じ方式)。
// ===========================================================================

// VISUAL 78字 (ぁぃぅぇぉゎ を除外。ゃゅょ・っ・ゐゑ・ゔ は維持)
const CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."がぎぐげござじずぜぞだぢづでどばびぶべぼ",
  ..."ぱぴぷぺぽ",
  ..."っゃゅょ",
  ..."ゐゑ",
  ..."ゔ",
];
const GRID_78 = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
  ["ゃ","","ゅ","","ょ"],["っ","","","",""],
  ["ゐ","","","","ゑ"],
  ["ゔ","","","",""],
];

const SIZE = 256;
const CHAR_MS = 200;          // 1文字の提示時間 (競技かるたの規定 0.2 秒)
const STROKE_THRESH = 128;    // これ以下の輝度をストローク画素とみなす (generate.py と同じ)
const BLUR_MAX_PX = 12;
const $ = (id) => document.getElementById(id);

// ---- state ----------------------------------------------------------------
let imgs = {};                // char -> HTMLImageElement
let strokeIdx = {};           // char -> Uint32Array (シャッフル済みストローク画素index)
let overlayCanvas = null;     // moya 用: 全78字の平均画像
let mode = "inspect";
let currentTrial = null, trialLog = [], lastCorrect = true, lastF = 50;
let pendingTimer = null, rafId = null;
const ITI_MS = 1000;

const stim = $("stimCanvas");
const sctx = stim.getContext("2d", { willReadFrequently: true });

// ---- 決定的シャッフル (mulberry32; 再現性のため文字コードを種にする) --------
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---- load -----------------------------------------------------------------
function loadImage(ch) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error(`base/${ch}.png の読み込みに失敗`));
    im.src = `base/${encodeURIComponent(ch)}.png`;
  });
}

async function loadAll() {
  const off = document.createElement("canvas");
  off.width = off.height = SIZE;
  const octx = off.getContext("2d", { willReadFrequently: true });
  const meanInk = new Float32Array(SIZE * SIZE);   // moya 用の平均インク量
  for (const ch of CHARS) {
    const im = await loadImage(ch);
    imgs[ch] = im;
    octx.clearRect(0, 0, SIZE, SIZE);
    octx.fillStyle = "#fff";
    octx.fillRect(0, 0, SIZE, SIZE);
    octx.drawImage(im, 0, 0, SIZE, SIZE);
    const d = octx.getImageData(0, 0, SIZE, SIZE).data;
    const idx = [];
    for (let i = 0; i < SIZE * SIZE; i++) {
      const lum = (d[i * 4] + d[i * 4 + 1] + d[i * 4 + 2]) / 3;
      if (lum <= STROKE_THRESH) idx.push(i);
      meanInk[i] += 255 - lum;
    }
    // 文字コードを種にした決定的シャッフル (毎回同じ順で画素が現れる = monotonic)
    const rnd = mulberry32(ch.codePointAt(0) * 2654435761 % 4294967296);
    for (let i = idx.length - 1; i > 0; i--) {
      const j = Math.floor(rnd() * (i + 1));
      [idx[i], idx[j]] = [idx[j], idx[i]];
    }
    strokeIdx[ch] = Uint32Array.from(idx);
  }
  // moya 用の平均画像を作る
  overlayCanvas = document.createElement("canvas");
  overlayCanvas.width = overlayCanvas.height = SIZE;
  const oc = overlayCanvas.getContext("2d");
  const od = oc.createImageData(SIZE, SIZE);
  for (let i = 0; i < SIZE * SIZE; i++) {
    const lum = Math.max(0, Math.min(255, 255 - meanInk[i] / CHARS.length));
    od.data[i * 4] = od.data[i * 4 + 1] = od.data[i * 4 + 2] = lum;
    od.data[i * 4 + 3] = 255;
  }
  oc.putImageData(od, 0, 0);
  $("loading").style.display = "none";
}

// ---- 提示アルゴリズム: render(ch, u) で u∈[0,1] の時点の見えを描く ----------
function clearStage() {
  sctx.filter = "none";
  sctx.globalAlpha = 1;
  sctx.fillStyle = "#fff";
  sctx.fillRect(0, 0, SIZE, SIZE);
}

const ALGOS = {
  fade(ch, u) {
    clearStage();
    sctx.globalAlpha = u;
    sctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    sctx.globalAlpha = 1;
  },
  stroke(ch, u) {
    clearStage();
    const idx = strokeIdx[ch];
    const k = Math.floor(idx.length * u);
    const img = sctx.getImageData(0, 0, SIZE, SIZE);
    const d = img.data;
    for (let i = 0; i < k; i++) {
      const p = idx[i] * 4;
      d[p] = d[p + 1] = d[p + 2] = 0;
    }
    sctx.putImageData(img, 0, 0);
  },
  zoom(ch, u) {
    clearStage();
    if (u <= 0) return;
    const s = SIZE * u;
    sctx.drawImage(imgs[ch], (SIZE - s) / 2, (SIZE - s) / 2, s, s);
  },
  blur(ch, u) {
    clearStage();
    sctx.filter = `blur(${(1 - u) * BLUR_MAX_PX}px)`;
    sctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    sctx.filter = "none";
  },
  moya(ch, u) {
    clearStage();
    sctx.globalAlpha = 1 - u;
    sctx.drawImage(overlayCanvas, 0, 0);
    sctx.globalAlpha = u;
    sctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    sctx.globalAlpha = 1;
  },
  // スライドイン: 領域(キャンバス)が窓になり、字が外から定位置へ滑り込む。
  // u=0 で完全に領域外、u=1 で定位置。領域外の部分は自然にクリップされる。
  slideB(ch, u) {          // 下から
    clearStage();
    sctx.drawImage(imgs[ch], 0, (1 - u) * SIZE, SIZE, SIZE);
  },
  slideR(ch, u) {          // 右から
    clearStage();
    sctx.drawImage(imgs[ch], (1 - u) * SIZE, 0, SIZE, SIZE);
  },
};

// ---- メッシュ(ワープ)モーフィング = 古典的な画像モーフィング ----------------
// 事前計算した対ごとのメッシュ頂点対応(morph_mesh.bin)を読み、規則格子 G_A(恒等)
// と変形先 G_B を線形補間して、テクスチャを貼った三角形メッシュをワープし重ねる。
let meshData = null;
async function loadMeshData() {
  try {
    const man = await (await fetch("morph_mesh_manifest.json")).json();
    const buf = new Uint8Array(await (await fetch("morph_mesh.bin")).arrayBuffer());
    const M = man.grid, S = man.size, step = (S - 1) / (M - 1);
    const idx = {}; man.chars.forEach((c, i) => idx[c] = i);
    const GA = [];
    for (let r = 0; r < M; r++) for (let c = 0; c < M; c++) GA.push([c * step, r * step]);
    const tris = [];
    for (let r = 0; r < M - 1; r++) for (let c = 0; c < M - 1; c++) {
      const a = r * M + c, b = r * M + c + 1, d = (r + 1) * M + c, e = (r + 1) * M + c + 1;
      tris.push([a, b, d]); tris.push([b, e, d]);
    }
    meshData = { M, S, idx, buf, GA, tris, chars: man.chars };
  } catch (e) { meshData = null; console.warn("morph_mesh 読み込み不可 (morph は fade で代替):", e.message); }
}
function getGB(c1, c2) {
  const { M, S, idx, buf, chars } = meshData, n = M * M;
  const base = (idx[c1] * chars.length + idx[c2]) * n * 2;
  const gb = new Array(n);
  for (let i = 0; i < n; i++) gb[i] = [buf[base + i * 2] * S / 255, buf[base + i * 2 + 1] * S / 255];
  return gb;
}
function solve3(rows, y) {   // 3x3 連立を Cramer で解く
  const [[a, b, c], [d, e, f], [g, h, i]] = rows;
  const det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
  if (Math.abs(det) < 1e-9) return null;
  const dx = y[0] * (e * i - f * h) - b * (y[1] * i - f * y[2]) + c * (y[1] * h - e * y[2]);
  const dy = a * (y[1] * i - f * y[2]) - y[0] * (d * i - f * g) + c * (d * y[2] - y[1] * g);
  const dz = a * (e * y[2] - y[1] * h) - b * (d * y[2] - y[1] * g) + y[0] * (d * h - e * g);
  return [dx / det, dy / det, dz / det];
}
function drawTexTri(img, s0, s1, s2, d0, d1, d2, alpha) {
  const S = [[s0[0], s0[1], 1], [s1[0], s1[1], 1], [s2[0], s2[1], 1]];
  const ace = solve3(S, [d0[0], d1[0], d2[0]]);   // 画面X = a*sx + c*sy + e
  const bdf = solve3(S, [d0[1], d1[1], d2[1]]);   // 画面Y = b*sx + d*sy + f
  if (!ace || !bdf) return;
  sctx.save();
  sctx.globalAlpha = alpha;
  sctx.beginPath(); sctx.moveTo(d0[0], d0[1]); sctx.lineTo(d1[0], d1[1]); sctx.lineTo(d2[0], d2[1]); sctx.closePath(); sctx.clip();
  sctx.setTransform(ace[0], bdf[0], ace[1], bdf[1], ace[2], bdf[2]);
  sctx.drawImage(img, 0, 0, SIZE, SIZE);
  sctx.setTransform(1, 0, 0, 1, 0, 0);
  sctx.restore();
}
// C1→C2 のモーフィングの、進み u∈[0,1] の時点の見えを描く
function renderMorph(c1, c2, u) {
  clearStage();
  if (!meshData) { ALGOS.fade(c2, u); return; }   // データ無しの代替
  const GA = meshData.GA, GB = getGB(c1, c2), tris = meshData.tris;
  const V = GA.map((p, i) => [(1 - u) * p[0] + u * GB[i][0], (1 - u) * p[1] + u * GB[i][1]]);
  for (const [i, j, k] of tris) drawTexTri(imgs[c1], GA[i], GA[j], GA[k], V[i], V[j], V[k], 1);   // C1 を土台に
  for (const [i, j, k] of tris) drawTexTri(imgs[c2], GB[i], GB[j], GB[k], V[i], V[j], V[k], u);   // C2 を u で重ねる
}
function playMorph(c1, c2, frac) {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  const cut = frac / 100, t0 = performance.now();
  function frame(now) {
    const u = (now - t0) / CHAR_MS;                // 0→1 を 0.2s で
    if (u < cut) { renderMorph(c1, c2, u); rafId = requestAnimationFrame(frame); }
    else { clearStage(); rafId = null; }           // frac% で消去
  }
  clearStage(); rafId = requestAnimationFrame(frame);
}

// ---- 2文字シーケンスの再生 --------------------------------------------------
// C1 を 0→0.2s でアルゴリズム提示し、0.2s で一瞬で消去して C2 に切り替える。
// C2 は frac% 時点 (0.2s × frac/100) で消去する。経過時間ベースで描く。
function playSeq(c1, c2, frac, algoName) {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  if (algoName === "morph") { playMorph(c1, c2, frac); return; }   // モーフィングは C1→C2 の単一提示
  const render = ALGOS[algoName];
  const c2End = CHAR_MS + CHAR_MS * frac / 100;
  const t0 = performance.now();
  function frame(now) {
    const el = now - t0;
    if (el < CHAR_MS) {
      render(c1, el / CHAR_MS);
    } else if (el < c2End) {
      render(c2, (el - CHAR_MS) / CHAR_MS);
    } else {
      clearStage();          // 消去して終了 (以降は残像 = 記憶で答える)
      rafId = null;
      return;
    }
    rafId = requestAnimationFrame(frame);
  }
  clearStage();
  rafId = requestAnimationFrame(frame);
}

// ---- Inspect ----------------------------------------------------------------
function populateSelect(sel, def) {
  sel.innerHTML = "";
  for (const c of CHARS) {
    const o = document.createElement("option");
    o.value = c; o.textContent = c;
    sel.appendChild(o);
  }
  sel.value = def;
}
function inspectInfo() {
  const f = parseFloat($("fSlider").value);
  $("fValue").textContent = `${f.toFixed(0)}%`;
  $("inspectInfo").textContent =
    `C1=${$("c1Select").value} (0.2s) → C2=${$("c2Select").value} を ${f.toFixed(0)}% ` +
    `(≈${Math.round(CHAR_MS * f / 100)}ms) 時点で消去 / algo=${$("algoSelect").value}`;
}
function setupInspect() {
  populateSelect($("c1Select"), "あ");
  populateSelect($("c2Select"), "き");
  $("c1Select").addEventListener("change", inspectInfo);
  $("c2Select").addEventListener("change", inspectInfo);
  $("algoSelect").addEventListener("change", inspectInfo);
  $("fSlider").addEventListener("input", inspectInfo);
  $("playInspect").addEventListener("click", () =>
    playSeq($("c1Select").value, $("c2Select").value,
            parseFloat($("fSlider").value), $("algoSelect").value));
  inspectInfo();
}

// ---- Trial ------------------------------------------------------------------
function pickFrac() {
  const dist = $("rDist").value;
  let f;
  if (dist === "uniform") f = Math.random() * 100;
  else if (dist === "low") f = Math.random() * 60;
  else if (dist === "grid21") { const g = []; for (let i = 0; i <= 100; i += 5) g.push(i); f = g[Math.floor(Math.random() * g.length)]; }
  else { f = lastCorrect ? Math.max(0, lastF - 5) : Math.min(100, lastF + 5); }
  return Math.max(0, Math.min(100, f));
}
function buildGrid() {
  const div = $("choices"); div.innerHTML = "";
  for (const row of GRID_78) for (const ch of row) {
    if (ch === "") { const s = document.createElement("span"); s.className = "spacer"; div.appendChild(s); }
    else { const b = document.createElement("button"); b.textContent = ch; b.onclick = () => answerTrial(ch); div.appendChild(b); }
  }
}
function startTrial() {
  if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null; }
  const c1 = CHARS[Math.floor(Math.random() * CHARS.length)];
  const c2 = CHARS[Math.floor(Math.random() * CHARS.length)];
  const frac = pickFrac();
  const algo = $("algoSelect").value;
  currentTrial = { c1, c2, frac, algo, t0: performance.now() };
  $("feedback").style.display = "none";
  buildGrid();
  playSeq(c1, c2, frac, algo);
}
function answerTrial(response) {
  if (!currentTrial) return;
  const rt = performance.now() - currentTrial.t0;
  const correct = response === currentTrial.c2;
  trialLog.push({ c1: currentTrial.c1, target: currentTrial.c2, frac: currentTrial.frac,
    algo: currentTrial.algo, response, correct,
    n_choices: CHARS.length, rt_ms: Math.round(rt) });
  lastCorrect = correct; lastF = currentTrial.frac;
  const fb = $("feedback");
  fb.className = "feedback " + (correct ? "correct" : "wrong");
  fb.textContent = (correct ? "✓ 正解" : "✗ 不正解 → 正解は「" + currentTrial.c2 + "」")
    + ` (C1=${currentTrial.c1}, frac=${currentTrial.frac.toFixed(0)}%, ${Math.round(rt)}ms)`;
  fb.style.display = "inline-block";
  for (const b of $("choices").querySelectorAll("button")) b.disabled = true;
  currentTrial = null; drawStats();
  pendingTimer = setTimeout(() => { pendingTimer = null; if (mode === "trial") startTrial(); }, ITI_MS);
}
function resetTrials() { trialLog = []; drawStats(); }
function downloadTrials() {
  const header = "trial_idx,c1,target,frac,algo,response,correct,n_choices,rt_ms";
  const rows = trialLog.map((t, i) => [i + 1, t.c1, t.target, t.frac, t.algo, t.response, t.correct, t.n_choices, t.rt_ms].join(","));
  const blob = new Blob([header + "\n" + rows.join("\n")], { type: "text/csv" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = "pilot_visual2char_trials.csv"; a.click();
}
function setupTrial() {
  $("startTrial").onclick = startTrial;
  $("resetTrials").onclick = resetTrials;
  $("downloadTrials").onclick = downloadTrials;
  $("replayTrial").onclick = () => {
    if (currentTrial) playSeq(currentTrial.c1, currentTrial.c2, currentTrial.frac, currentTrial.algo);
  };
}

// ---- logistic fit (pilot_audio.js と同じ) -----------------------------------
function logL(data,a,b){let ll=0;for(const [x,y,g] of data){const z=b*(x-a);const s=z>=0?1/(1+Math.exp(-z)):Math.exp(z)/(1+Math.exp(z));let p=g+(1-g)*s;if(p<1e-9)p=1e-9;else if(p>1-1e-9)p=1-1e-9;ll+=y*Math.log(p)+(1-y)*Math.log(1-p);}return ll;}
function fitLogistic(trials){
  const data=trials.map(t=>[t.frac,t.correct?1:0,1/Math.max(2,t.n_choices||4)]);
  if(data.length<8)return null;
  const nc=data.filter(d=>d[1]===1).length; if(nc===0||nc===data.length)return null;
  let aLo=0,aHi=100,bLo=0.005,bHi=1.5,bestA=50,bestB=0.2,bestLL=-Infinity;const N=30;
  for(let pass=0;pass<4;pass++){let ca=bestA,cb=bestB,cll=bestLL;
    for(let i=0;i<=N;i++){const a=aLo+(aHi-aLo)*i/N;for(let j=0;j<=N;j++){const b=bLo+(bHi-bLo)*j/N;const ll=logL(data,a,b);if(ll>cll){cll=ll;ca=a;cb=b;}}}
    bestA=ca;bestB=cb;bestLL=cll;const aS=(aHi-aLo)/N*2,bS=(bHi-bLo)/N*2;aLo=bestA-aS;aHi=bestA+aS;bLo=Math.max(1e-4,bestB-bS);bHi=bestB+bS;}
  const mean=data.reduce((s,d)=>s+d[1],0)/data.length;let ln=0;for(const[,y]of data){const p=Math.max(1e-9,Math.min(1-1e-9,mean));ln+=y*Math.log(p)+(1-y)*Math.log(1-p);}
  const r2=ln<0?1-bestLL/ln:0;
  const counts={};for(const[,,g]of data)counts[g]=(counts[g]||0)+1;const gamma=Object.entries(counts).sort((a,b)=>b[1]-a[1])[0][0]*1;
  return {alpha:bestA,beta:bestB,gamma,n:data.length,pseudoR2:r2};
}
function logisticP(x,fit){const z=fit.beta*(x-fit.alpha);const s=z>=0?1/(1+Math.exp(-z)):Math.exp(z)/(1+Math.exp(z));return fit.gamma+(1-fit.gamma)*s;}
function median(xs){if(!xs.length)return 0;const s=xs.slice().sort((a,b)=>a-b);const m=Math.floor(s.length/2);return s.length%2?s[m]:(s[m-1]+s[m])/2;}

// ---- chart (pilot_audio.js と同じ描画) ---------------------------------------
function drawStats() {
  const can=$("chartCanvas"),c=can.getContext("2d");const w=can.width,h=can.height;c.clearRect(0,0,w,h);
  const binW=5,nB=21,bins=Array.from({length:nB},()=>({n:0,c:0}));
  for(const t of trialLog){const bi=Math.min(nB-1,Math.floor(t.frac/binW));bins[bi].n++;if(t.correct)bins[bi].c++;}
  c.strokeStyle="#ccc";c.lineWidth=1;c.beginPath();c.moveTo(40,10);c.lineTo(40,h-24);c.lineTo(w-10,h-24);c.stroke();
  c.fillStyle="#666";c.font="10px monospace";
  for(let y=0;y<=4;y++){const py=10+(h-34)*y/4;c.fillText((100-y*25)+"%",4,py+4);c.strokeStyle="#eee";c.beginPath();c.moveTo(40,py);c.lineTo(w-10,py);c.stroke();}
  const barW=(w-50)/nB;
  for(let i=0;i<nB;i++){const b=bins[i],x=42+i*barW;
    if(b.n>0){const acc=b.c/b.n,bh=acc*(h-34);c.fillStyle="#4a76d6";c.fillRect(x,h-24-bh,Math.max(1,barW-2),bh);c.fillStyle="#222";c.fillText(b.n,x+1,h-12);}
    if(i%4===0){c.fillStyle="#666";c.fillText((i*binW)+"",x+1,h-2);}}
  c.fillStyle="#999";c.fillText("frac %",w-60,h-2);
  const fit=fitLogistic(trialLog);
  if(fit){
    c.strokeStyle="#b5402a";c.lineWidth=2;c.beginPath();
    for(let i=0;i<=200;i++){const x=i*100/200;const p=logisticP(x,fit);const px=42+(x/binW+0.5)*barW,py=(h-24)-p*(h-34);if(i===0)c.moveTo(px,py);else c.lineTo(px,py);}
    c.stroke();
    const pA=fit.gamma+(1-fit.gamma)*0.5;
    if(fit.alpha>=0&&fit.alpha<=100){const px=42+(fit.alpha/binW+0.5)*barW,py=(h-24)-pA*(h-34);
      c.fillStyle="#b5402a";c.beginPath();c.arc(px,py,5,0,2*Math.PI);c.fill();
      c.strokeStyle="#b5402a";c.setLineDash([2,3]);c.beginPath();c.moveTo(px,h-24);c.lineTo(px,py);c.stroke();c.setLineDash([]);}
    $("fitInfo").textContent=`2P logistic: α=${fit.alpha.toFixed(1)}% β=${fit.beta.toFixed(3)} γ=${fit.gamma.toFixed(3)} pseudoR²=${fit.pseudoR2.toFixed(2)} (n=${fit.n})\n`
      +`⌀ 閾値 α (= chance/ceiling 中点, p=${pA.toFixed(3)}): frac=${fit.alpha.toFixed(1)}%`;
  } else $("fitInfo").textContent = trialLog.length>=8?"(全問同正誤などで未フィット)":`(フィットには 8 試行以上必要・現在 ${trialLog.length})`;
  const tot=trialLog.length,cor=trialLog.filter(t=>t.correct).length,rtMed=tot?median(trialLog.map(t=>t.rt_ms)):0;
  $("statsTable").innerHTML=`<table><tr><th>n</th><th>正答</th><th>正答率</th><th>中央RT</th></tr><tr><td>${tot}</td><td>${cor}</td><td>${tot?(100*cor/tot).toFixed(1):"—"}%</td><td>${rtMed.toFixed(0)}ms</td></tr></table>`;
}

// ---- mode switching + boot ----------------------------------------------------
function setMode(m){if(pendingTimer){clearTimeout(pendingTimer);pendingTimer=null;}mode=m;
  $("modeInspect").classList.toggle("active",m==="inspect");$("modeTrial").classList.toggle("active",m==="trial");
  $("inspectPanel").style.display=m==="inspect"?"":"none";$("trialPanel").style.display=m==="trial"?"":"none";}
async function boot(){
  $("modeInspect").onclick=()=>setMode("inspect");
  $("modeTrial").onclick=()=>setMode("trial");
  try { await loadAll(); }
  catch(e){ $("loading").textContent="起動エラー: "+e.message; $("loading").style.color="#900"; return; }
  await loadMeshData();   // morph 用のメッシュ頂点対応 (無ければ morph は fade で代替)
  clearStage();
  setupInspect(); setupTrial(); drawStats(); setMode("inspect");
}
boot();
