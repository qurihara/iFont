// iFont パイロット: 視覚・2文字の SOA 掃引 (ブロックB) 自己完結版。
// 先行文字(char1)をフル鮮明で SOA[ms] 提示し、次の事象(char2)で同じ固定領域を上書きする。
// char2 も SOA[ms] 提示したのち中立マスク(別かな重畳)で打ち切り、両文字を50音グリッドで回答させる。
// SOA を恒常法で掃引し、位置別(char1=上書きされる先頭 / char2=末尾)の識別率を得る。
// ブロックA(pilot_soa_visual.html)の f(D) と引き算すれば干渉指標 I(S)=実測−f(S) になる。
// jsPsych・音声・サーバ不要。base/<かな>.png を流用。結果は画面表示＋JSONダウンロード。
"use strict";

// ---- 設定 (URLパラメータで上書き可: ?levels=100,150,200,300,450,700&perlevel=6&mask=250) ----
const P = new URLSearchParams(location.search);
const SOA_LEVELS = (P.get("levels") || "100,150,200,300,450,700").split(",").map(Number);
const PER_LEVEL = Number(P.get("perlevel") || 6);   // 各水準の対数(1対=2回答)
const N_PRACTICE = Number(P.get("practice") || 2);
const MASK_MS = Number(P.get("mask") || 250);       // 末尾の中立マスク時間
const FIX_MS = 400;
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
function pickPair(){ const c1=pick(CHARS); let c2=pick(CHARS); while(c2===c1) c2=pick(CHARS); return [c1,c2]; }

function buildTrials() {
  const main = [];
  for (const S of SOA_LEVELS) for (let k=0;k<PER_LEVEL;k++) { const [c1,c2]=pickPair(); main.push({ S, c1, c2, practice:false }); }
  shuffle(main);
  const prac = [];
  for (let k=0;k<N_PRACTICE;k++) { const [c1,c2]=pickPair(); prac.push({ S: pick(SOA_LEVELS), c1, c2, practice:true }); }
  return prac.concat(main);
}

function newCanvas() { const c=document.createElement("canvas"); c.id="stim"; c.width=SIZE; c.height=SIZE; return c; }
function drawChar(ctx, ch) { ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE); if (imgs[ch]) ctx.drawImage(imgs[ch],0,0,SIZE,SIZE); }
function drawMask(ctx) {
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  ctx.save(); ctx.globalAlpha = 0.55;
  for (let i=0;i<6;i++){ const ch=pick(CHARS); ctx.drawImage(imgs[ch],(Math.random()-0.5)*40,(Math.random()-0.5)*40,SIZE,SIZE); }
  ctx.restore();
}

function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  const inPractice = t.practice;
  screen.innerHTML = `<div class="muted">${inPractice ? "練習" : `試行 ${ti-N_PRACTICE+1} / ${trials.length-N_PRACTICE}`} (SOA=${t.S}ms)</div><div id="stage"></div>`;
  const stage = document.getElementById("stage");
  const canvas = newCanvas(); stage.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE);
  ctx.fillStyle="#333"; ctx.font="40px system-ui"; ctx.textAlign="center"; ctx.textBaseline="middle";
  ctx.fillText("+", SIZE/2, SIZE/2);
  const t0 = performance.now();
  let phase = "fix";
  // 注視 → char1(SOA) → char2(SOA, char1を上書き) → マスク(MASK_MS) → 回答
  function frame(now) {
    const el = now - t0;
    if (phase==="fix" && el >= FIX_MS) { phase="c1"; drawChar(ctx, t.c1); }
    else if (phase==="c1" && el >= FIX_MS + t.S) { phase="c2"; drawChar(ctx, t.c2); }
    else if (phase==="c2" && el >= FIX_MS + 2*t.S) { phase="mask"; drawMask(ctx); }
    else if (phase==="mask" && el >= FIX_MS + 2*t.S + MASK_MS) { return respond(t, inPractice); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function respond(t, inPractice) {
  askOne(t, 1, (r1) => {
    askOne(t, 2, (r2) => {
      if (!inPractice) results.push({
        c1: t.c1, c2: t.c2, S: t.S,
        resp1: r1, resp2: r2,
        correct1: r1 === t.c1, correct2: r2 === t.c2,
      });
      ti++; runTrial();
    });
  });
}
function askOne(t, pos, done) {
  const stage = document.getElementById("stage");
  stage.innerHTML = `<div style="text-align:center"><div class="ask">${pos}文字目は？</div></div>`;
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
    const blob = new Blob([JSON.stringify({ config:{SOA_LEVELS,PER_LEVEL,MASK_MS,FIX_MS}, byLevel:rows, trials:results }, null, 2)], {type:"application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `pilot_soa_visual2_${Date.now()}.json`; a.click();
  };
}

function start() { trials = buildTrials(); results = []; ti = 0; runTrial(); }
function intro() {
  screen.innerHTML = `<h1>iFont パイロット: 視覚・2文字の SOA 掃引 (ブロックB)</h1>
    <p>画面中央に、かなが<b>2文字続けて</b>表示されます。1文字目は次の文字が出るまで(<b>SOA=${SOA_LEVELS.join("・")}ms</b>)、
    2文字目も同じ時間だけ表示され、直後に「マスク」が出ます。そのあと、<b>1文字目と2文字目を順に</b>50音の表から選んでください。</p>
    <p class="muted">水準ごと${PER_LEVEL}対 (計${SOA_LEVELS.length*PER_LEVEL}対=回答${SOA_LEVELS.length*PER_LEVEL*2}回) ＋練習${N_PRACTICE}。マスク${MASK_MS}ms。
    音声・通信なし。結果はこの端末内でJSON保存できます。</p>
    <p><button class="primary" id="go">開始する</button></p>`;
  document.getElementById("go").onclick = start;
}

(async function(){
  try { await preload(); intro(); }
  catch(e){ screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}<br>このページは experiment/ 内でHTTP配信して開いてください。</p>`; }
})();
