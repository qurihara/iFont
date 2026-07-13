// iFont パイロット: 聴覚・2文字の SOA 掃引 (ブロックB) 研究者向け版。
// 単音プール(audio1char_stimuli, B3, 0.2秒/モーラ)から2文字を選び、
// char1 を SOA[ms] だけ聞かせて char2 の開始で打ち切り(次事象=上書き)、
// char2 も SOA[ms] で打ち切って雑音バースト(中立マスク)を置き、両文字を回答させる。
// Web Audio でサンプル精度にスケジュールする。SOA が音長(200ms)以上なら自然に鳴り終わる。
// 【注意】正解の対応づけに answer_key_merged.json(Git管理外・ローカルのみ)が必要。
//        公開ページでは動かない(研究者のローカル配信専用)。
"use strict";

const P = new URLSearchParams(location.search);
const SOA_LEVELS = (P.get("levels") || "100,150,200,300,450,700").split(",").map(Number);
const PER_LEVEL = Number(P.get("perlevel") || 6);
const N_PRACTICE = Number(P.get("practice") || 2);
const MASK_MS = Number(P.get("mask") || 250);
const FADE_S = 0.008;                       // 打ち切りのクリック音を避けるフェード

// audio1char.js と同じ 72字グリッド
const GRID_AUDIO = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],["ゔ","","","",""],
];
const CHARS = GRID_AUDIO.flat().filter(Boolean);   // 72字

const screen = document.getElementById("screen");
let audioCtx = null, stimByChar = {}, bufByChar = {};
let trials = [], results = [], ti = 0;

function ensureCtx(){ if(!audioCtx) audioCtx = new (window.AudioContext||window.webkitAudioContext)(); return audioCtx; }

// 正解表(answer_key_merged.json)を読み込む。Git管理外のため、同ディレクトリからの
// fetch に失敗した場合(GitHub Pages 等)は、研究者が手元のファイルを選択して読み込む。
async function loadAnswerKey() {
  if (!P.has("nokey")) {
    try {
      const r = await fetch("answer_key_merged.json", {cache:"no-store"});
      if (r.ok) return await r.json();
    } catch (e) { /* fetch不可 → ファイル選択へ */ }
  }
  return await new Promise((resolve) => {
    screen.innerHTML = `<h1>正解表を選択してください</h1>
      <p class="muted">このページはかな→音声ファイルの対応づけに <b>answer_key_merged.json</b>(Git管理外・研究者のみ保有)が必要です。
      公開サーバには置いていないため、手元のファイルを選択してください。ファイルは<b>この端末内でのみ</b>使われ、どこにも送信されません。</p>
      <p><input type="file" id="akfile" accept=".json,application/json"></p>`;
    document.getElementById("akfile").addEventListener("change", (ev) => {
      const f = ev.target.files[0];
      if (!f) return;
      const rd = new FileReader();
      rd.onload = () => {
        try { resolve(JSON.parse(rd.result)); }
        catch (e) { screen.querySelector("p.muted").textContent = "JSONとして読めませんでした: " + e.message; }
      };
      rd.readAsText(f);
    });
  });
}

async function preload() {
  screen.innerHTML = `<h1>読み込み中…</h1><p class="muted">マニフェストと正解表(ローカル)、音声72クリップを読み込んでいます。</p>`;
  const mres = await fetch("audio1char_manifest.json", {cache:"no-store"});
  if (!mres.ok) throw new Error("audio1char_manifest.json が読めない");
  const manifest = await mres.json();
  const akey = await loadAnswerKey();
  for (const s of manifest.stimuli) {
    const rec = akey[`audio1char|${s.id}`];
    if (rec && rec.char) stimByChar[rec.char] = s;
  }
  const have = CHARS.filter(c => stimByChar[c]);
  if (have.length < 60) throw new Error(`正解表と音声の対応が不足(${have.length}/72)`);
  // 72クリップをデコード
  let done = 0;
  await Promise.all(have.map(async ch => {
    const s = stimByChar[ch];
    const r = await fetch(`audio1char_stimuli/${s.file}`);
    bufByChar[ch] = await ensureCtx().decodeAudioData(await r.arrayBuffer());
    done++; if (done % 12 === 0) screen.querySelector("p").textContent = `音声デコード中… ${done}/${have.length}`;
  }));
}

function shuffle(a){ for(let i=a.length-1;i>0;i--){ const j=Math.floor(Math.random()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; } return a; }
function pick(a){ return a[Math.floor(Math.random()*a.length)]; }
function avail(){ return CHARS.filter(c => bufByChar[c]); }
function pickPair(){ const A=avail(); const c1=pick(A); let c2=pick(A); while(c2===c1) c2=pick(A); return [c1,c2]; }

function buildTrials() {
  const main = [];
  for (const S of SOA_LEVELS) for (let k=0;k<PER_LEVEL;k++) { const [c1,c2]=pickPair(); main.push({S,c1,c2,practice:false}); }
  shuffle(main);
  const prac = [];
  for (let k=0;k<N_PRACTICE;k++) { const [c1,c2]=pickPair(); prac.push({S:pick(SOA_LEVELS),c1,c2,practice:true}); }
  return prac.concat(main);
}

// クリップの「モーラ区間の先頭から d 秒」をゲートして再生するバッファを作る
function gatedBuffer(ch, gateS) {
  const s = stimByChar[ch], src = bufByChar[ch];
  const sr = src.sampleRate;
  const start = Math.floor(s.char_onset_s * sr);
  const dur = Math.min(gateS, s.char_dur_s);
  const n = Math.max(1, Math.floor(dur * sr));
  const out = ensureCtx().createBuffer(1, n, sr);
  const a = src.getChannelData(0), b = out.getChannelData(0);
  for (let i=0;i<n;i++) b[i] = a[start+i] || 0;
  const nf = Math.min(Math.floor(FADE_S*sr), n>>1);
  for (let i=0;i<nf;i++){ b[i]*=i/nf; b[n-1-i]*=i/nf; }   // 立上げ/立下げフェード
  return out;
}
function playNoise(when, durS) {
  const ctx = ensureCtx(); const n = Math.floor(durS*ctx.sampleRate);
  const buf = ctx.createBuffer(1, n, ctx.sampleRate);
  const d = buf.getChannelData(0);
  for (let i=0;i<n;i++) d[i] = (Math.random()*2-1)*0.25;
  const nf = Math.floor(FADE_S*ctx.sampleRate);
  for (let i=0;i<nf;i++){ d[i]*=i/nf; d[n-1-i]*=i/nf; }
  const s = ctx.createBufferSource(); s.buffer = buf; s.connect(ctx.destination); s.start(when);
}
function playSeq(t) {
  const ctx = ensureCtx();
  const t0 = ctx.currentTime + 0.15;
  const S = t.S/1000;
  const s1 = ctx.createBufferSource(); s1.buffer = gatedBuffer(t.c1, S); s1.connect(ctx.destination); s1.start(t0);
  const s2 = ctx.createBufferSource(); s2.buffer = gatedBuffer(t.c2, S); s2.connect(ctx.destination); s2.start(t0 + S);
  playNoise(t0 + 2*S, MASK_MS/1000);
  return (t0 + 2*S + MASK_MS/1000 - ctx.currentTime) * 1000;   // 終了までのms
}

function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  const inPractice = t.practice;
  screen.innerHTML = `<div class="muted">${inPractice ? "練習" : `試行 ${ti-N_PRACTICE+1} / ${trials.length-N_PRACTICE}`} (SOA=${t.S}ms)</div>
    <div id="stage">♪</div>`;
  const waitMs = playSeq(t);
  setTimeout(() => respond(t, inPractice), waitMs + 120);
}
function respond(t, inPractice) {
  askOne(t, 1, (r1) => {
    askOne(t, 2, (r2) => {
      if (!inPractice) results.push({ c1:t.c1, c2:t.c2, S:t.S, resp1:r1, resp2:r2,
        correct1:r1===t.c1, correct2:r2===t.c2 });
      ti++; runTrial();
    });
  });
}
function askOne(t, pos, done) {
  const stage = document.getElementById("stage");
  stage.innerHTML = `<div class="ask" style="font-size:18px">${pos}文字目は？</div>`;
  document.getElementById("grid")?.remove();
  const grid = document.createElement("div"); grid.id="grid";
  for (const row of GRID_AUDIO) for (const ch of row) {
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
    acc1:m[S].n?m[S].ok1/m[S].n:null, acc2:m[S].n?m[S].ok2/m[S].n:null, accBoth:m[S].n?m[S].okBoth/m[S].n:null }));
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
    <rect x="${ml+8}" y="${mt+4}" width="10" height="3" fill="#1E2A5E"/><text x="${ml+22}" y="${mt+10}" font-size="10.5">char1(先頭)</text>
    <rect x="${ml+8}" y="${mt+20}" width="10" height="3" fill="#2E7D8F"/><text x="${ml+22}" y="${mt+26}" font-size="10.5">char2(末尾)</text>
  </svg>`;
}
function showResults() {
  const rows = byLevel();
  const pc=v=>v==null?"-":(v*100).toFixed(0)+"%";
  const tbl = `<table><tr><th>SOA(ms)</th>${rows.map(r=>`<td>${r.S}</td>`).join("")}</tr>
    <tr><th>char1</th>${rows.map(r=>`<td>${pc(r.acc1)}</td>`).join("")}</tr>
    <tr><th>char2</th>${rows.map(r=>`<td>${pc(r.acc2)}</td>`).join("")}</tr>
    <tr><th>両方</th>${rows.map(r=>`<td>${pc(r.accBoth)}</td>`).join("")}</tr>
    <tr><th>n(対)</th>${rows.map(r=>`<td>${r.n}</td>`).join("")}</tr></table>`;
  screen.innerHTML = `<h1>パイロット完了</h1>
    <p class="muted">SOA に対する位置別識別率(聴覚)。聴覚1文字frac(絶対ms記録・マスク条件をそろえたもの)を基準線 f(D) にすると干渉指標 I(S) になります。</p>
    ${svgCurves(rows)} ${tbl}
    <p><button class="primary" id="dl">結果JSONをダウンロード</button></p>`;
  document.getElementById("dl").onclick = () => {
    const blob = new Blob([JSON.stringify({ config:{SOA_LEVELS,PER_LEVEL,MASK_MS,pitch:"B3",mora_dur_s:0.2}, byLevel:rows, trials:results }, null, 2)], {type:"application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `pilot_soa_audio_${Date.now()}.json`; a.click();
  };
}

function start() { ensureCtx().resume(); trials = buildTrials(); results = []; ti = 0; runTrial(); }
function intro() {
  screen.innerHTML = `<h1>iFont パイロット: 聴覚・2文字の SOA 掃引 (ブロックB)</h1>
    <p>かなの音声が<b>2文字続けて</b>流れます。1文字目は次の文字の開始(<b>SOA=${SOA_LEVELS.join("・")}ms</b>)で打ち切られ、
    2文字目も同じ時間で打ち切られて雑音(マスク)が流れます。そのあと、<b>1文字目と2文字目を順に</b>50音の表から選んでください。</p>
    <p class="muted">水準ごと${PER_LEVEL}対＋練習${N_PRACTICE}。音声は単音プール(B3・0.2秒/モーラ)。
    正解表(ローカル)が必要な研究者向けページです。ヘッドホン推奨・音量を確認してから開始してください。</p>
    <p><button class="primary" id="go">開始する</button></p>`;
  document.getElementById("go").onclick = start;
}

(async function(){
  try { await preload(); intro(); }
  catch(e){ screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}</p>`; }
})();
