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
// 後方マスク: 数枚のかなを描いた画を小タイルに切り、位置と向きをシャッフルした「構造マスク」。
// 目標文字と同じ線の太さ・空間周波数をもつが、可読なかなにはならない(＝別の文字と混同されない)。
function buildMaskSource() {
  const off = document.createElement("canvas"); off.width=SIZE; off.height=SIZE;
  const o = off.getContext("2d");
  o.fillStyle="#fff"; o.fillRect(0,0,SIZE,SIZE);
  for (let i=0;i<4;i++){ const ch=pick(CHARS); if (imgs[ch]) o.drawImage(imgs[ch],0,0,SIZE,SIZE); }
  return off;
}
function drawMask(ctx) {
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  const src = buildMaskSource();
  const N = 16, ts = SIZE / N;   // 16x16タイルに切って、各セルへランダムなタイルを回転して貼る(細かい線テクスチャ)
  for (let gy=0; gy<N; gy++) for (let gx=0; gx<N; gx++){
    const sx = Math.floor(Math.random()*N)*ts, sy = Math.floor(Math.random()*N)*ts;
    ctx.save();
    ctx.translate(gx*ts+ts/2, gy*ts+ts/2);
    ctx.rotate((Math.floor(Math.random()*4))*Math.PI/2);   // 90°単位の回転で可読性を消す
    ctx.drawImage(src, sx, sy, ts, ts, -ts/2, -ts/2, ts, ts);
    ctx.restore();
  }
}

function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  const inPractice = t.practice;
  screen.innerHTML = `<div class="muted">${inPractice ? "練習" : `試行 ${ti-N_PRACTICE+1} / ${trials.length-N_PRACTICE}`}</div><div id="stage"></div>`;
  const stage = document.getElementById("stage");
  const canvas = newCanvas(); stage.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  // 注視点 → 露出D → マスクMASK_MS(0なら白紙) → 応答
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  ctx.fillStyle="#333"; ctx.font="40px system-ui"; ctx.textAlign="center"; ctx.textBaseline="middle";
  ctx.fillText("+", SIZE/2, SIZE/2);
  const t0 = performance.now();
  let phase = "fix";
  function frame(now) {
    const el = now - t0;
    if (phase==="fix" && el >= FIX_MS) { phase="target"; drawChar(ctx, t.ch); }
    else if (phase==="target" && el >= FIX_MS + t.D) {
      phase="mask";
      if (MASK_MS>0) drawMask(ctx);
      else { ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE); }  // mask=0: 出して消すだけ(残像込み・比較用)
    }
    else if (phase==="mask" && el >= FIX_MS + t.D + MASK_MS) { phase="resp"; return respond(t, inPractice, now); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function respond(t, inPractice, tShown) {
  const stage = document.getElementById("stage");
  stage.innerHTML = `<div style="text-align:center"><div class="ask">最後に一瞬見えた1文字を選んでください</div>
    <div class="muted">分からなければ勘でOK（モザイク模様は答えではありません）</div></div>`;
  const grid = document.createElement("div"); grid.id="grid";
  for (const row of GRID_78) for (const ch of row) {
    if (ch==="") { const s=document.createElement("div"); s.className="kana spacer"; grid.appendChild(s); continue; }
    const b = document.createElement("button"); b.className="kana"; b.textContent=ch;
    b.onclick = () => {
      const rt = performance.now() - tShown;
      if (!inPractice) { results.push({ char:t.ch, D:t.D, response:ch, correct: ch===t.ch, rt_ms: Math.round(rt) }); ti++; runTrial(); return; }
      // 練習: 正解を短く提示して流れを覚えてもらう
      const ok = ch===t.ch;
      screen.innerHTML = `<div style="text-align:center;padding:34px">
        <div style="font-size:44px;color:${ok?'#2E7D8F':'#C25B4E'}">${ok?'◯':'×'}</div>
        <p>一瞬見えていたのは「<b style="font-size:22px">${t.ch}</b>」でした。</p>
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
    const blob = new Blob([JSON.stringify({ config:{D_LEVELS,PER_LEVEL,MASK_MS,FIX_MS}, byLevel:rows, trials:results }, null, 2)], {type:"application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `pilot_soa_visual_${Date.now()}.json`; a.click();
  };
}

function start() {
  trials = buildTrials(); results = []; ti = 0; runTrial();
}
function intro() {
  const maskNote = MASK_MS>0
    ? `すぐに <b>文字にならないモザイク模様</b> が出ます <span class="muted">（目の残像を消すためのもの。<b>読めるかなではありません／答えなくてよい</b>）</span>`
    : `すぐに画面が <b>白紙</b> に戻ります <span class="muted">（このモードはマスクなし。比較・体感用）</span>`;
  screen.innerHTML = `<h1>iFont パイロット: 視覚・単文字の露出時間 (ブロックA)</h1>
    <p><b>1問で答える文字は「1つ」だけです。</b>画面はこの順に進みます。</p>
    <ol style="font-size:15px;line-height:1.9;padding-left:1.2em">
      <li>中央の <b>＋</b> を見つめる</li>
      <li>かな <b>1文字</b> が一瞬（<b>${D_LEVELS.join("・")}ms</b> のいずれか）だけ表示される</li>
      <li>${maskNote}</li>
      <li><b>最後に一瞬見えた1文字</b> を、下のかなの表から選ぶ</li>
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
