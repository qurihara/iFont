// iFont パイロット: 視覚・単文字の露出時間 (ブロックA) 自己完結版。
// かな1文字を露出時間 D[ms] だけ提示し、直後に後方マスクを置いて、何の文字かを50音グリッドで答える。
// 露出時間 D を恒常法で掃引し、露出時間に対する識別率 f(D) を得る (約260msで飽和するかを見る)。
// jsPsych・音声・サーバ不要。base/<かな>.png を流用。結果は画面表示＋JSONダウンロード。
"use strict";

// ---- 設定 (URLパラメータで上書き可: ?levels=100,150,200,300,450,700&perlevel=8&mask=250) ----
const P = new URLSearchParams(location.search);
const D_LEVELS = (P.get("levels") || "100,150,200,300,450,700").split(",").map(Number);
const PER_LEVEL = Number(P.get("perlevel") || 8);   // 各水準の試行数
const N_PRACTICE = Number(P.get("practice") || 3);
const MASK_MS = Number(P.get("mask") || 250);       // 後方マスク時間
const FIX_MS = 400;                                  // 注視点
const SIZE = 256;

const GRID_78 = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
  ["ゃ","","ゅ","","ょ"],["っ","","","",""],
  ["ゐ","","","","ゑ"],["ゔ","","","",""],
];
const CHARS = GRID_78.flat().filter(Boolean);   // 78字

const screen = document.getElementById("screen");
const imgs = {};
let trials = [], results = [], ti = 0;

function loadImage(ch) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error(`base/${ch}.png の読込に失敗`));
    im.src = `base/${encodeURIComponent(ch)}.png`;
  });
}
async function preload() {
  screen.innerHTML = `<h1>読み込み中…</h1><p class="muted">かな画像を読み込んでいます。</p>`;
  await Promise.all(CHARS.map(async ch => { imgs[ch] = await loadImage(ch); }));
}

function shuffle(a){ for(let i=a.length-1;i>0;i--){ const j=Math.floor(Math.random()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; } return a; }
function pick(a){ return a[Math.floor(Math.random()*a.length)]; }

function buildTrials() {
  const main = [];
  for (const D of D_LEVELS) for (let k=0;k<PER_LEVEL;k++) main.push({ D, ch: pick(CHARS), practice:false });
  shuffle(main);
  const prac = [];
  for (let k=0;k<N_PRACTICE;k++) prac.push({ D: pick(D_LEVELS), ch: pick(CHARS), practice:true });
  return prac.concat(main);
}

// ---- 描画 ----
function newCanvas() {
  const c = document.createElement("canvas"); c.id="stim"; c.width=SIZE; c.height=SIZE;
  return c;
}
function drawChar(ctx, ch) {
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  if (imgs[ch]) ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
}
function drawMask(ctx) {
  // 後方マスク: 別のかなを複数枚重ねたパターンマスク
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  ctx.save(); ctx.globalAlpha = 0.55;
  for (let i=0;i<6;i++){
    const ch = pick(CHARS);
    const dx=(Math.random()-0.5)*40, dy=(Math.random()-0.5)*40;
    if (imgs[ch]) ctx.drawImage(imgs[ch], dx, dy, SIZE, SIZE);
  }
  ctx.restore();
}

function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  const inPractice = t.practice;
  screen.innerHTML = `<div class="muted">${inPractice ? "練習" : `試行 ${ti-N_PRACTICE+1} / ${trials.length-N_PRACTICE}`}</div><div id="stage"></div>`;
  const stage = document.getElementById("stage");
  const canvas = newCanvas(); stage.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  // 注視点 → 露出D → マスクMASK_MS → 応答
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  ctx.fillStyle="#333"; ctx.font="40px system-ui"; ctx.textAlign="center"; ctx.textBaseline="middle";
  ctx.fillText("+", SIZE/2, SIZE/2);
  const t0 = performance.now();
  let phase = "fix";
  function frame(now) {
    const el = now - t0;
    if (phase==="fix" && el >= FIX_MS) { phase="target"; drawChar(ctx, t.ch); }
    else if (phase==="target" && el >= FIX_MS + t.D) { phase="mask"; drawMask(ctx); }
    else if (phase==="mask" && el >= FIX_MS + t.D + MASK_MS) { phase="resp"; return respond(t, inPractice, now); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function respond(t, inPractice, tShown) {
  const stage = document.getElementById("stage");
  stage.innerHTML = `<div style="text-align:center"><div class="muted">提示された文字は？</div></div>`;
  const grid = document.createElement("div"); grid.id="grid";
  for (const row of GRID_78) for (const ch of row) {
    if (ch==="") { const s=document.createElement("div"); s.className="kana spacer"; grid.appendChild(s); continue; }
    const b = document.createElement("button"); b.className="kana"; b.textContent=ch;
    b.onclick = () => {
      const rt = performance.now() - tShown;
      if (!inPractice) results.push({ char:t.ch, D:t.D, response:ch, correct: ch===t.ch, rt_ms: Math.round(rt) });
      ti++; runTrial();
    };
    grid.appendChild(b);
  }
  stage.parentElement.appendChild(grid);
}

// ---- 結果 ----
function byLevel() {
  const m = {};
  for (const D of D_LEVELS) m[D] = { n:0, correct:0 };
  for (const r of results) { m[r.D].n++; if (r.correct) m[r.D].correct++; }
  return D_LEVELS.map(D => ({ D, n:m[D].n, acc: m[D].n ? m[D].correct/m[D].n : null }));
}
function svgCurve(rows) {
  const W=440,H=220,ml=44,mb=30,mt=12,mr=12;
  const xs = D=> ml + (D-Math.min(...D_LEVELS))/(Math.max(...D_LEVELS)-Math.min(...D_LEVELS))*(W-ml-mr);
  const ys = a=> mt + (1-a)*(H-mt-mb);
  let pts = rows.filter(r=>r.acc!=null).map(r=>`${xs(r.D).toFixed(1)},${ys(r.acc).toFixed(1)}`);
  const chance = 1/CHARS.length;
  return `<svg width="${W}" height="${H}" style="background:#fff;border:1px solid #eee">
    <line x1="${ml}" y1="${ys(chance)}" x2="${W-mr}" y2="${ys(chance)}" stroke="#bbb" stroke-dasharray="4"/>
    <polyline points="${pts.join(" ")}" fill="none" stroke="#1E2A5E" stroke-width="2"/>
    ${rows.filter(r=>r.acc!=null).map(r=>`<circle cx="${xs(r.D)}" cy="${ys(r.acc)}" r="4" fill="#1E2A5E"/>`).join("")}
    <text x="${ml}" y="${H-8}" font-size="11">${Math.min(...D_LEVELS)}ms</text>
    <text x="${W-mr-34}" y="${H-8}" font-size="11">${Math.max(...D_LEVELS)}ms</text>
    <text x="8" y="${mt+8}" font-size="11">100%</text><text x="12" y="${ys(chance)-2}" font-size="10" fill="#999">偶然</text>
    <text x="${W/2-40}" y="${H-2}" font-size="11">露出時間 D (ms)</text>
  </svg>`;
}
function showResults() {
  const rows = byLevel();
  const tbl = `<table><tr><th>D(ms)</th>${rows.map(r=>`<td>${r.D}</td>`).join("")}</tr>
    <tr><th>識別率</th>${rows.map(r=>`<td>${r.acc==null?"-":(r.acc*100).toFixed(0)+"%"}</td>`).join("")}</tr>
    <tr><th>n</th>${rows.map(r=>`<td>${r.n}</td>`).join("")}</tr></table>`;
  screen.innerHTML = `<h1>パイロット完了</h1>
    <p class="muted">露出時間に対する識別率 f(D)。約260msで飽和(頭打ち)する形が見えれば、単文字の利用時間の仮説と整合します。</p>
    ${svgCurve(rows)} ${tbl}
    <p><button class="primary" id="dl">結果JSONをダウンロード</button></p>`;
  document.getElementById("dl").onclick = () => {
    const blob = new Blob([JSON.stringify({ config:{D_LEVELS,PER_LEVEL,MASK_MS,FIX_MS}, byLevel:rows, trials:results }, null, 2)], {type:"application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `pilot_soa_visual_${Date.now()}.json`; a.click();
  };
}

function start() {
  trials = buildTrials(); results = []; ti = 0; runTrial();
}
function intro() {
  screen.innerHTML = `<h1>iFont パイロット: 視覚・単文字の露出時間 (ブロックA)</h1>
    <p>画面中央に、かな1文字が <b>${D_LEVELS.join("・")}ms</b> のいずれかの短い時間だけ表示され、直後に別のかなが重なった「マスク」が出ます。
    その後、<b>提示された1文字を50音の表から選んで</b>ください。</p>
    <p class="muted">水準ごと${PER_LEVEL}試行 (計${D_LEVELS.length*PER_LEVEL}試行) ＋練習${N_PRACTICE}。マスク${MASK_MS}ms。所要5〜8分。
    音声・通信なし。結果はこの端末内でJSON保存できます。</p>
    <p><button class="primary" id="go">開始する</button></p>`;
  document.getElementById("go").onclick = start;
}

(async function(){
  try { await preload(); intro(); }
  catch(e){ screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}<br>このページは experiment/ 内でHTTP配信して開いてください (file:// では画像が読めないことがあります)。</p>`; }
})();
