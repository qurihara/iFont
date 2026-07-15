// iFont パイロット: 視覚・2文字の SOA 掃引 (ブロックB) 自己完結版。
// 先行文字(char1)をフル鮮明で SOA[ms] 提示し、次の事象(char2)で同じ固定領域を上書きする。
// char2 も SOA[ms] 提示したのち中立マスク(別かな重畳)で打ち切り、両文字を50音グリッドで回答させる。
// SOA を恒常法で掃引し、位置別(char1=上書きされる先頭 / char2=末尾)の識別率を得る。
// ブロックA(pilot_soa_visual.html)の f(D) と引き算すれば干渉指標 I(S)=実測−f(S) になる。
// jsPsych・音声・サーバ不要。base/<かな>.png を流用。結果は画面表示＋JSONダウンロード。
"use strict";

// ---- 設定 (URLパラメータで上書き可: ?levels=100,150,200,300,450,700&perlevel=6&mask=250) ----
const VERSION = "1.1";   // パイロットのバージョン(細かい改変ごとにインクリメント)
const P = new URLSearchParams(location.search);
const SOA_LEVELS = (P.get("levels") || "100,150,200,300,450,700").split(",").map(Number);
const PER_LEVEL = Number(P.get("perlevel") || 6);   // 各水準の対数(1対=2回答)
const N_PRACTICE = Number(P.get("practice") || 2);
const MASK_MS = Number(P.get("mask") || 250);       // 末尾の中立マスク時間
const FIX_MS = 400;
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
let trials = [], results = [], ti = 0, mainStarted = false;

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
function pickPair(){ const c1=pick(CHARS); let c2=pick(CHARS); while(c2===c1) c2=pick(CHARS); return [c1,c2]; }

function buildTrials() {
  const main = [];
  for (const S of SOA_LEVELS) for (let k=0;k<PER_LEVEL;k++) { const [c1,c2]=pickPair(); main.push({ S, c1, c2, practice:false }); }
  shuffle(main);
  // 練習は流れを覚えるため、あえて長め(見やすい)SOAの2水準から出す
  const easy = [...SOA_LEVELS].sort((a,b)=>b-a).slice(0,2);
  const prac = [];
  for (let k=0;k<N_PRACTICE;k++) { const [c1,c2]=pickPair(); prac.push({ S: pick(easy), c1, c2, practice:true }); }
  return prac.concat(main);
}

function newCanvas() { const c=document.createElement("canvas"); c.id="stim"; c.width=SIZE; c.height=SIZE; return c; }
function drawChar(ctx, ch) { ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE); if (imgs[ch]) ctx.drawImage(imgs[ch],0,0,SIZE,SIZE); }
// 中立マスク: 層化・H/V偏向の連結細線クロスハッチ・メッシュ(手続き生成・資産不要)。
// 全セルに必ず1本描き(層化=大きな白穴を作らない)、線長をセルより長くして隣接セルと連結、
// H/V偏向でかなの縦横ストロークに同方位マスキングを効かせる。実グリフ不使用=可読なかな/特定字の想起なし。
// かな84字での実測: 墨率≈0.18 / 中心の最大空円≈11px(≈線幅) / 毎試行<5ms。被覆で旧スクランブル(穴32px)を大きく上回る。
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
    if (Math.random() < OB) { th = Math.random() * Math.PI; }
    else {
      let base = ((gx + gy) & 1) === 0 ? 0 : Math.PI / 2;
      if (Math.random() < 0.5) base = Math.PI / 2 - base;
      th = base + (Math.random() - 0.5) * 2 * SPREAD;
    }
    const ll = LF * C * (0.85 + 0.3 * Math.random());
    const dx = Math.cos(th) * ll / 2, dy = Math.sin(th) * ll / 2;
    ctx.beginPath(); ctx.moveTo(px - dx, py - dy); ctx.lineTo(px + dx, py + dy); ctx.stroke();
  }
}

function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  const inPractice = t.practice;
  if (!inPractice && !mainStarted) { mainStarted = true; return showMainGate(runTrial); }
  screen.innerHTML = `<div class="muted">${inPractice ? `練習 ${ti+1} / ${N_PRACTICE}` : `本番 ${ti-N_PRACTICE+1} / ${trials.length-N_PRACTICE}`} (SOA=${t.S}ms)</div><div id="stage"></div>`;
  const stage = document.getElementById("stage");
  startGate(stage, (ctx) => presentTrial(t, inPractice, ctx));
}

// 練習の後、本番に入る前の確認画面。クリック/スペースで本番開始。
function showMainGate(next) {
  const nMain = trials.length - N_PRACTICE;
  screen.innerHTML = `<div style="text-align:center;padding:40px 20px">
    <h2 style="color:#1E2A5E">これから本番です</h2>
    <p>本番では <b>正解は表示されません</b>。ここからの回答が記録されます。</p>
    <p class="muted">本番は <b>${nMain}問</b>（各2文字回答）です。やり方は練習と同じです。</p>
    <p style="margin-top:20px"><button class="primary" id="mainGo">本番を始める（またはスペースキー）</button></p></div>`;
  const key = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); go(); } };
  function go(){ document.removeEventListener("keydown", key); next(); }
  document.getElementById("mainGo").addEventListener("click", go, { once: true });
  document.addEventListener("keydown", key);
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

// 刺激提示: 既存canvasに 注視(ゆらぎ付き) → char1(SOA) → char2(SOA, char1を上書き) → マスク → 回答。実測SOAを記録。
function presentTrial(t, inPractice, ctx) {
  drawFix(ctx);
  const fixDur = FIX_MS + Math.floor(Math.random() * FIX_JITTER);   // 先読み防止のゆらぎ
  const t0 = performance.now();
  let phase = "fix", t1 = 0, t2 = 0, tm = 0;
  function frame(now) {
    const el = now - t0;
    if (phase==="fix" && el >= fixDur) { phase="c1"; drawChar(ctx, t.c1); t1 = now; }
    else if (phase==="c1" && el >= fixDur + t.S) { phase="c2"; drawChar(ctx, t.c2); t2 = now; }
    else if (phase==="c2" && el >= fixDur + 2*t.S) { phase="mask"; drawMask(ctx); tm = now; }
    else if (phase==="mask" && el >= fixDur + 2*t.S + MASK_MS) {
      t._actualSoa1 = Math.round(t2 - t1); t._actualSoa2 = Math.round(tm - t2);
      return respond(t, inPractice);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
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

function respond(t, inPractice) {
  askOne(t, 1, (r1) => {
    askOne(t, 2, (r2) => {
      if (!inPractice) {
        results.push({
          c1: t.c1, c2: t.c2, S: t.S,
          actual_soa1: t._actualSoa1, actual_soa2: t._actualSoa2,
          resp1: r1, resp2: r2,
          correct1: r1 === t.c1, correct2: r2 === t.c2,
        });
        ti++; runTrial(); return;
      }
      // 練習: 2文字の正解を提示して流れを覚えてもらう
      const ok1 = r1===t.c1, ok2 = r2===t.c2;
      screen.innerHTML = `<div style="text-align:center;padding:30px">
        <p>正解 — 1文字目「<b style="font-size:20px">${t.c1}</b>」<span style="color:${ok1?'#2E7D8F':'#C25B4E'}">${ok1?'◯':'×'}</span>
        ／ 2文字目「<b style="font-size:20px">${t.c2}</b>」<span style="color:${ok2?'#2E7D8F':'#C25B4E'}">${ok2?'◯':'×'}</span></p>
        <p class="muted">これは練習です。本番も同じ流れ（＋ → 1文字目 → 2文字目で上書き → モザイク → 2つ回答）をくり返します。</p></div>`;
      setTimeout(() => { ti++; runTrial(); }, 1600);
    });
  });
}
function askOne(t, pos, done) {
  const stage = document.getElementById("stage");
  stage.style.height = "auto";   // 刺激用の空欄を詰めて、かなの表をプロンプト直下に出す
  const label = pos===1 ? "1文字目（先に出た文字）は？" : "2文字目（上書きした文字）は？";
  stage.innerHTML = `<div style="text-align:center"><div class="ask">${label}</div>
    <div class="muted">分からなければ勘でOK（モザイクは答えではありません）</div></div>`;
  document.getElementById("grid")?.remove();
  const grid = document.createElement("div"); grid.id="grid";
  for (const row of GRID_78) for (const ch of row) {
    if (ch==="") { const s=document.createElement("div"); s.className="kana spacer"; grid.appendChild(s); continue; }
    const b=document.createElement("button"); b.className="kana"; b.textContent=ch;
    b.onclick = () => done(ch);
    grid.appendChild(b);
  }
  stage.parentElement.appendChild(grid);
}

function byLevel() {
  const m = {};
  for (const S of SOA_LEVELS) m[S] = { n:0, ok1:0, ok2:0, okBoth:0 };
  for (const r of results) { const e=m[r.S]; e.n++; if(r.correct1)e.ok1++; if(r.correct2)e.ok2++; if(r.correct1&&r.correct2)e.okBoth++; }
  return SOA_LEVELS.map(S => ({ S, n:m[S].n,
    acc1: m[S].n? m[S].ok1/m[S].n : null,
    acc2: m[S].n? m[S].ok2/m[S].n : null,
    accBoth: m[S].n? m[S].okBoth/m[S].n : null }));
}
function svgCurves(rows) {
  const W=460,H=230,ml=44,mb=30,mt=12,mr=12;
  const lo=Math.min(...SOA_LEVELS), hi=Math.max(...SOA_LEVELS);
  const xs=S=> ml + (S-lo)/(hi-lo)*(W-ml-mr);
  const ys=a=> mt + (1-a)*(H-mt-mb);
  const line=(key,color,dash)=>{
    const pts=rows.filter(r=>r[key]!=null).map(r=>`${xs(r.S).toFixed(1)},${ys(r[key]).toFixed(1)}`).join(" ");
    const dots=rows.filter(r=>r[key]!=null).map(r=>`<circle cx="${xs(r.S)}" cy="${ys(r[key])}" r="4" fill="${color}"/>`).join("");
    return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" ${dash?`stroke-dasharray="5 3"`:""}/>`+dots;
  };
  const chance=1/CHARS.length;
  return `<svg width="${W}" height="${H}" style="background:#fff;border:1px solid #eee">
    <line x1="${ml}" y1="${ys(chance)}" x2="${W-mr}" y2="${ys(chance)}" stroke="#bbb" stroke-dasharray="4"/>
    ${line("acc1","#1E2A5E",false)}
    ${line("acc2","#2E7D8F",true)}
    <text x="${ml}" y="${H-8}" font-size="11">${lo}ms</text>
    <text x="${W-mr-34}" y="${H-8}" font-size="11">${hi}ms</text>
    <text x="8" y="${mt+8}" font-size="11">100%</text>
    <text x="${W/2-56}" y="${H-2}" font-size="11">文字間 SOA (ms)</text>
    <rect x="${ml+8}" y="${mt+4}" width="10" height="3" fill="#1E2A5E"/><text x="${ml+22}" y="${mt+10}" font-size="10.5">char1(上書きされる先頭)</text>
    <rect x="${ml+8}" y="${mt+20}" width="10" height="3" fill="#2E7D8F"/><text x="${ml+22}" y="${mt+26}" font-size="10.5">char2(末尾)</text>
  </svg>`;
}
function showResults() {
  const rows = byLevel();
  const pc = v => v==null?"-":(v*100).toFixed(0)+"%";
  const tbl = `<table><tr><th>SOA(ms)</th>${rows.map(r=>`<td>${r.S}</td>`).join("")}</tr>
    <tr><th>char1</th>${rows.map(r=>`<td>${pc(r.acc1)}</td>`).join("")}</tr>
    <tr><th>char2</th>${rows.map(r=>`<td>${pc(r.acc2)}</td>`).join("")}</tr>
    <tr><th>両方</th>${rows.map(r=>`<td>${pc(r.accBoth)}</td>`).join("")}</tr>
    <tr><th>n(対)</th>${rows.map(r=>`<td>${r.n}</td>`).join("")}</tr></table>`;
  screen.innerHTML = `<h1>パイロット完了</h1>
    <p class="muted">SOA に対する位置別識別率。ブロックA(pilot_soa_visual.html)の f(D) と引き算すると干渉指標 I(S)=実測−f(S) になります。
    char1 が短い SOA で落ち、SOA とともに回復すれば後方マスキング型の干渉です。</p>
    ${svgCurves(rows)} ${tbl}
    <p><button class="primary" id="dl">結果JSONをダウンロード</button></p>`;
  document.getElementById("dl").onclick = () => {
    const blob = new Blob([JSON.stringify({ config:{SOA_LEVELS,PER_LEVEL,MASK_MS,FIX_MS,START_MODE}, env:ENV, byLevel:rows, trials:results }, null, 2)], {type:"application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `pilot_soa_visual2_${Date.now()}.json`; a.click();
  };
}

function start() { trials = buildTrials(); results = []; ti = 0; mainStarted = false; runTrial(); }
function intro() {
  const startNote = START_MODE==="click"
    ? `各問題は、準備ができたら <b>ボタン（またはスペースキー）</b> を押して自分のペースで始めます。`
    : START_MODE==="countdown" ? `各問題の前に${COUNTDOWN_S}秒のカウントダウンが出ます。` : ``;
  const pcNote = ENV.touch
    ? `<p class="muted" style="color:#C25B4E">この実験は表示のタイミングが重要です。<b>できればPC（パソコン）での参加を推奨します。</b>スマートフォンの場合は横向き・明るさ最大でお願いします。</p>` : ``;
  screen.innerHTML = `<h1>iFont パイロット: 視覚・2文字の SOA 掃引 (ブロックB)</h1>
    ${pcNote}
    <p><b>1問で答える文字は「2つ」です。</b>同じ場所に、かなが2文字つづけて出ます。${startNote}以下の手順で進みます。</p>
    <ol style="font-size:15px;line-height:1.9;padding-left:1.2em">
      <li>表示枠の中央にある <b>＋</b> を見つめる</li>
      <li>見たまま、枠の下の <b>[開始]</b> ボタン（またはスペース）を押す</li>
      <li><b>1文字目</b> が出る（<b>${SOA_LEVELS.join("・")}ms</b> のいずれかの間）</li>
      <li>同じ場所に <b>2文字目</b> が出て1文字目を<b>上書き</b>する（同じ時間だけ）</li>
      <li><b>モザイク模様</b>が出る <span class="muted">（目の残像を消すためのものです）</span></li>
      <li><b>1文字目 → 2文字目</b> の順に、それぞれかなの表から選ぶ</li>
    </ol>
    <p style="background:#eef4f6;border-radius:8px;padding:10px 12px">まず <b>練習 ${N_PRACTICE}問</b>（正解を表示）→ そのあと <b>本番 ${SOA_LEVELS.length*PER_LEVEL}問</b>（各2文字回答・正解は非表示・記録あり）を行います。所要7〜10分。</p>
    <p class="muted">1文字目は2文字目に上書きされるので見えにくくなります。分からなければ勘でOKです（外れも大切なデータ）。回答はこの端末の中だけで完結します。</p>
    <p><button class="primary" id="go">練習を始める（${N_PRACTICE}問）</button></p>
    <p class="muted" style="text-align:right;font-size:12px;margin-top:6px">研究者向けパイロット版 v${VERSION}</p>`;
  document.getElementById("go").onclick = start;
}

(async function(){
  try { await preload(); intro(); }
  catch(e){ screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}<br>このページは experiment/ 内でHTTP配信して開いてください。</p>`; }
})();
