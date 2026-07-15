// iFont パイロット: 視覚・単文字の露出時間 (ブロックA) 自己完結版。
// かな1文字を露出時間 D[ms] だけ提示し、直後に後方マスクを置いて、何の文字かを50音グリッドで答える。
// 露出時間 D を恒常法で掃引し、露出時間に対する識別率 f(D) を得る (約260msで飽和するかを見る)。
// jsPsych・音声・サーバ不要。base/<かな>.png を流用。結果は画面表示＋JSONダウンロード。
"use strict";

// ---- 設定 (URLパラメータで上書き可: ?levels=100,150,200,300,450,700&perlevel=8&mask=250) ----
// mask=0 にすると後方マスクを置かず「1文字を出して消すだけ」になる(残像込みの比較・体感用。本番は必ずマスクあり)。
const P = new URLSearchParams(location.search);
const D_LEVELS = (P.get("levels") || "100,150,200,300,450,700").split(",").map(Number);
const PER_LEVEL = Number(P.get("perlevel") || 8);   // 各水準の試行数
const N_PRACTICE = Number(P.get("practice") || 3);
const MASK_MS = Number(P.get("mask") || 250);       // 後方マスク時間
const FIX_MS = 400;                                  // 注視点
const COUNTDOWN_S = Number(P.get("countdown") ?? 5); // countdownモード時の秒数
const COUNTDOWN_MS = COUNTDOWN_S * 1000;
const START_MODE = P.get("start") || "click";        // "click"(既定・自己ペース) / "countdown" / "none"
const FIX_JITTER = 300;                              // 注視点の追加ゆらぎ上限(ms・先読み防止)
const SIZE = 256;

// 端末・表示環境(実測タイミング解析用にログする)
const ENV = { ua: navigator.userAgent, dpr: window.devicePixelRatio || 1,
  screen: `${window.screen.width}x${window.screen.height}`, touch: (navigator.maxTouchPoints || 0) > 0, refreshHz: null };
(function measureRefresh(){ let n=0; const t0=performance.now();
  function f(now){ n++; if(n<40) requestAnimationFrame(f); else ENV.refreshHz = Math.round(1000/((now-t0)/n)); }
  requestAnimationFrame(f);
})();

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
  // 練習は流れを覚えるため、あえて長め(見やすい)の2水準から出す
  const easy = [...D_LEVELS].sort((a,b)=>b-a).slice(0,2);
  const prac = [];
  for (let k=0;k<N_PRACTICE;k++) prac.push({ D: pick(easy), ch: pick(CHARS), practice:true });
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
// 後方マスク: 層化・H/V偏向の連結細線クロスハッチ・メッシュ(手続き生成・資産不要)。
// 全セルに必ず1本描き(層化=大きな白穴を作らない)、線長をセルより長くして隣接セルと連結、
// H/V偏向でかなの縦横ストロークに同方位マスキングを効かせる。実グリフ不使用=可読なかな/特定字の想起なし。
// かな84字での実測比較(自作の周波数・被覆スクリプトで検証):
//   墨率≈0.18(かな0.11〜上限0.18内) / 中心の最大空円≈11px(≈線幅、これ以上大きい穴が残らない) / 毎試行<5ms。
//   現行スクランブル(墨率0.34・穴32px)や疎な線分・ドット(穴36〜84px)を被覆で大きく上回る。
function drawMask(ctx) {
  const C = 14, W = 1.7, JIT = 0.40, OB = 0.15, SPREAD = 0.20, LF = 1.55;
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, SIZE, SIZE);
  ctx.strokeStyle = "#000"; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.lineWidth = W;
  const n = Math.ceil(SIZE / C) + 1;
  for (let gy = -1; gy <= n; gy++) for (let gx = -1; gx <= n; gx++) {
    const cx = (gx + 0.5) * C, cy = (gy + 0.5) * C;
    const px = cx + (Math.random() - 0.5) * 2 * JIT * C;
    const py = cy + (Math.random() - 0.5) * 2 * JIT * C;
    let th;
    if (Math.random() < OB) { th = Math.random() * Math.PI; }         // 少数の斜め線で字画想起を崩す
    else {
      let base = ((gx + gy) & 1) === 0 ? 0 : Math.PI / 2;             // 市松でH/Vを撒く
      if (Math.random() < 0.5) base = Math.PI / 2 - base;            // 規則性を崩し両軸に障壁
      th = base + (Math.random() - 0.5) * 2 * SPREAD;
    }
    const ll = LF * C * (0.85 + 0.3 * Math.random());                // 線長>セル → 隣接セルと連結し穴を塞ぐ
    const dx = Math.cos(th) * ll / 2, dy = Math.sin(th) * ll / 2;
    ctx.beginPath(); ctx.moveTo(px - dx, py - dy); ctx.lineTo(px + dx, py + dy); ctx.stroke();
  }
}

function drawFix(ctx) {
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  ctx.fillStyle="#333"; ctx.font="40px system-ui"; ctx.textAlign="center"; ctx.textBaseline="middle";
  ctx.fillText("+", SIZE/2, SIZE/2);
}
function drawCountdown(ctx, sec) {
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  ctx.fillStyle="#2E7D8F"; ctx.font="bold 72px system-ui"; ctx.textAlign="center"; ctx.textBaseline="middle";
  ctx.fillText(String(sec), SIZE/2, SIZE/2 - 12);
  ctx.fillStyle="#8a93a6"; ctx.font="15px system-ui";
  ctx.fillText("中央を見て準備してください", SIZE/2, SIZE/2 + 52);
}

function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  const inPractice = t.practice;
  screen.innerHTML = `<div class="muted">${inPractice ? "練習" : `試行 ${ti-N_PRACTICE+1} / ${trials.length-N_PRACTICE}`}</div><div id="stage"></div>`;
  const stage = document.getElementById("stage");
  startGate(stage, (ctx) => presentTrial(t, inPractice, ctx));
}

// 開始ゲート: 文字表示枠(canvas)と「＋」を最初から出し、その下にボタンを置く。
// ボタンは表示枠の外(下)にあるので、押してもカーソルが刺激に被らず、枠も動かない。
function startGate(stage, onStart) {
  stage.style.height = "auto"; stage.innerHTML = "";
  const box = document.createElement("div"); box.style.textAlign = "center";
  const canvas = newCanvas(); canvas.style.display = "block"; canvas.style.margin = "0 auto";
  box.appendChild(canvas); stage.appendChild(box);
  const ctx = canvas.getContext("2d"); drawFix(ctx);

  if (START_MODE === "none") return onStart(ctx);
  if (START_MODE === "countdown") {
    const t0 = performance.now(); let lastSec = -1;
    (function cd(now){ const remain = COUNTDOWN_MS - (now - t0);
      if (remain > 0) { const s = Math.ceil(remain/1000); if (s!==lastSec){ drawCountdown(ctx, s); lastSec=s; } requestAnimationFrame(cd); }
      else { drawFix(ctx); onStart(ctx); }
    })(performance.now());
    return;
  }
  const btnWrap = document.createElement("div"); btnWrap.style.marginTop = "14px";
  btnWrap.innerHTML = `<button class="primary" id="startBtn">準備ができたら開始（またはスペースキー）</button>
    <div class="muted" style="margin-top:6px">上の枠の中央にある ＋ を見たまま、このボタンを押してください</div>`;
  box.appendChild(btnWrap);
  const key = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); go(); } };
  function go(){ document.removeEventListener("keydown", key); btnWrap.style.visibility = "hidden"; onStart(ctx); }
  document.getElementById("startBtn").addEventListener("click", go, { once: true });
  document.addEventListener("keydown", key);
}

// 刺激提示: 既存canvasに 注視点(ゆらぎ付き) → 露出D → マスクMASK_MS(0なら白紙) → 応答。実際の表示msを記録。
function presentTrial(t, inPractice, ctx) {
  drawFix(ctx);
  const fixDur = FIX_MS + Math.floor(Math.random() * FIX_JITTER);   // 先読み防止のゆらぎ
  const t0 = performance.now();
  let phase = "fix", tOn = 0, tOff = 0;
  function frame(now) {
    const el = now - t0;
    if (phase==="fix" && el >= fixDur) { phase="target"; drawChar(ctx, t.ch); tOn = now; }
    else if (phase==="target" && el >= fixDur + t.D) {
      phase="mask";
      if (MASK_MS>0) drawMask(ctx);
      else { ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE); }  // mask=0: 出して消すだけ(残像込み・比較用)
      tOff = now;
    }
    else if (phase==="mask" && el >= fixDur + t.D + MASK_MS) {
      phase="resp"; t._actualMs = Math.round(tOff - tOn); return respond(t, inPractice, now);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function respond(t, inPractice, tShown) {
  const stage = document.getElementById("stage");
  stage.style.height = "auto";   // 刺激用の空欄を詰めて、かなの表をプロンプト直下に出す
  stage.innerHTML = `<div style="text-align:center"><div class="ask">最初に表示された文字を選んでください</div>
    <div class="muted">分からなければ勘でOK（モザイク模様は答えではありません）</div></div>`;
  const grid = document.createElement("div"); grid.id="grid";
  for (const row of GRID_78) for (const ch of row) {
    if (ch==="") { const s=document.createElement("div"); s.className="kana spacer"; grid.appendChild(s); continue; }
    const b = document.createElement("button"); b.className="kana"; b.textContent=ch;
    b.onclick = () => {
      const rt = performance.now() - tShown;
      if (!inPractice) { results.push({ char:t.ch, D:t.D, actual_ms:t._actualMs, response:ch, correct: ch===t.ch, rt_ms: Math.round(rt) }); ti++; runTrial(); return; }
      // 練習: 正解を短く提示して流れを覚えてもらう
      const ok = ch===t.ch;
      screen.innerHTML = `<div style="text-align:center;padding:34px">
        <div style="font-size:44px;color:${ok?'#2E7D8F':'#C25B4E'}">${ok?'◯':'×'}</div>
        <p>表示されていたのは「<b style="font-size:22px">${t.ch}</b>」でした。</p>
        <p class="muted">これは練習です。本番も同じ流れ（＋ → 一瞬の1文字 → モザイク → 回答）をくり返します。</p></div>`;
      setTimeout(() => { ti++; runTrial(); }, 1300);
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
    const blob = new Blob([JSON.stringify({ config:{D_LEVELS,PER_LEVEL,MASK_MS,FIX_MS,START_MODE}, env:ENV, byLevel:rows, trials:results }, null, 2)], {type:"application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `pilot_soa_visual_${Date.now()}.json`; a.click();
  };
}

function start() {
  trials = buildTrials(); results = []; ti = 0; runTrial();
}
function intro() {
  const maskNote = MASK_MS>0
    ? `目の残像を消すために <b>モザイク模様</b> が出ます`
    : `画面が <b>白紙</b> に戻ります <span class="muted">（このモードはマスクなし。比較・体感用）</span>`;
  const startNote = START_MODE==="click"
    ? `各問題は、準備ができたら <b>ボタン（またはスペースキー）</b> を押して自分のペースで始めます。`
    : START_MODE==="countdown" ? `各問題の前に${COUNTDOWN_S}秒のカウントダウンが出ます。` : ``;
  const pcNote = ENV.touch
    ? `<p class="muted" style="color:#C25B4E">この実験は表示のタイミングが重要です。<b>できればPC（パソコン）での参加を推奨します。</b>スマートフォンの場合は横向き・明るさ最大でお願いします。</p>` : ``;
  screen.innerHTML = `<h1>iFont パイロット: 視覚・単文字の露出時間 (ブロックA)</h1>
    ${pcNote}
    <p><b>1問で答える文字は「1つ」だけです。</b>${startNote}以下の手順で進みます。</p>
    <ol style="font-size:15px;line-height:1.9;padding-left:1.2em">
      <li>表示枠の中央にある <b>＋</b> を見つめる</li>
      <li>見たまま、枠の下の <b>[開始]</b> ボタン（またはスペース）を押す</li>
      <li>かな <b>1文字</b> が一瞬（<b>${D_LEVELS.join("・")}ms</b> のいずれか）だけ表示される。<b>この文字を覚えてください</b></li>
      <li>${maskNote}</li>
      <li><b>最初に表示された文字</b> を、かなの表から選ぶ</li>
    </ol>
    <p class="muted">わざと短く・見えにくく提示しているので、半分くらい勘になる問題もあります。
    分からなければ推測で選んでください（外れも大切なデータです）。まず練習が${N_PRACTICE}問あり、正解が表示されます。</p>
    <p class="muted">水準ごと${PER_LEVEL}試行 (計${D_LEVELS.length*PER_LEVEL}試行)。所要5〜8分。音声・通信なし。結果はこの端末内でJSON保存できます。</p>
    <p><button class="primary" id="go">練習を始める</button></p>`;
  document.getElementById("go").onclick = start;
}

(async function(){
  try { await preload(); intro(); }
  catch(e){ screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}<br>このページは experiment/ 内でHTTP配信して開いてください (file:// では画像が読めないことがあります)。</p>`; }
})();
