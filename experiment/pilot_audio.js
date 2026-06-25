// ===========================================================================
// iFont 聴覚セルフパイロット — 単音 時間ゲーティング (truncation)
//   - Loads 84 base kana mp3s, decodes to PCM via Web Audio.
//   - For target T and frac% of its voiced duration, plays [onset, onset+frac]
//     with a short fade (same model as make_audio_stimuli.py), computed live.
//   - Inspect: target + continuous frac slider + play.
//   - Trial: random target × frac, 50音 grid, immediate feedback, RT, logistic
//     fit. Mirrors experiment/pilot.js (visual) for the auditory modality.
// ===========================================================================

const CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."がぎぐげござじずぜぞだぢづでどばびぶべぼ",
  ..."ぱぴぷぺぽ", ..."ぁぃぅぇぉっゃゅょゎ", ..."ゐゑ", ..."ゔ",
];
const KARUTA_CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."ゐゑ",
];
const GRID_84 = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
  ["ぁ","ぃ","ぅ","ぇ","ぉ"],["ゃ","","ゅ","","ょ"],["っ","","","","ゎ"],
  ["ゐ","","","","ゑ"],["ゔ","","","",""],
];
const GRID_KARUTA = [...GRID_84.slice(0, 11), GRID_84[GRID_84.length - 2]];

const SILENCE_THRESH = 0.02, FADE_MS = 8;
const $ = (id) => document.getElementById(id);

// ---- state ----------------------------------------------------------------
let ctx = null, basePCM = {}, bounds = {}, sr = 0;   // bounds[ch] = [i0,i1]
let activeChars = CHARS, activeGrid = GRID_84;
let mode = "inspect";
let currentTrial = null, trialLog = [], lastCorrect = true, lastF = 50;
let pendingTimer = null;
const ITI_MS = 1000;

// ---- load + decode --------------------------------------------------------
async function fetchPCM(ch) {
  const res = await fetch(`audio_base/${encodeURIComponent(ch)}.mp3`, {cache: "force-cache"});
  if (!res.ok) throw new Error(`audio_base/${ch}.mp3 ${res.status}`);
  const audioBuf = await ctx.decodeAudioData(await res.arrayBuffer());
  return audioBuf.getChannelData(0).slice();
}
function voicedBounds(x) {
  let peak = 0; for (let i=0;i<x.length;i++){const a=Math.abs(x[i]); if(a>peak)peak=a;}
  const th = SILENCE_THRESH*peak + 1e-9;
  let i0=0; while(i0<x.length && Math.abs(x[i0])<=th) i0++;
  let i1=x.length; while(i1>i0 && Math.abs(x[i1-1])<=th) i1--;
  if (i0>=i1) { i0=0; i1=x.length; }
  return [i0, i1];
}
async function loadAll() {
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  sr = ctx.sampleRate;
  for (const ch of CHARS) { basePCM[ch] = await fetchPCM(ch); bounds[ch] = voicedBounds(basePCM[ch]); }
  setActiveSet($("qSet").value);
  $("loading").style.display = "none";
}
function setActiveSet(name) {
  if (name === "karuta") { activeChars = KARUTA_CHARS; activeGrid = GRID_KARUTA; }
  else { activeChars = CHARS; activeGrid = GRID_84; }
}

// ---- truncation + playback ------------------------------------------------
function truncBuffer(target, frac) {
  const x = basePCM[target], [i0,i1] = bounds[target];
  const span = i1 - i0;
  const end = i0 + Math.round(span * frac / 100);
  const len = Math.max(1, end - i0);
  const ab = ctx.createBuffer(1, len, sr);
  const ch0 = ab.getChannelData(0);
  for (let i=0;i<len;i++) ch0[i] = x[i0+i] || 0;
  const fade = Math.min(Math.round(sr*FADE_MS/1000), len);
  for (let i=0;i<fade;i++) ch0[len-fade+i] *= (1 - i/fade);
  return ab;
}
let _src = null;
function play(target, frac) {
  if (ctx.state === "suspended") ctx.resume();
  if (_src) { try { _src.stop(); } catch(e){} }
  if (frac <= 0) { _src = null; return; }     // silence anchor
  const s = ctx.createBufferSource();
  s.buffer = truncBuffer(target, frac);
  s.connect(ctx.destination); s.start(); _src = s;
}

// ---- Inspect --------------------------------------------------------------
function populateCharSelect() {
  const sel = $("charSelect"); sel.innerHTML = "";
  for (const c of activeChars){const o=document.createElement("option");o.value=c;o.textContent=c;sel.appendChild(o);}
  sel.value = activeChars.includes("あ") ? "あ" : activeChars[0];
}
function inspectInfo() {
  const f = parseFloat($("fSlider").value);
  $("fValue").textContent = `${f.toFixed(0)}%`;
  const [i0,i1] = bounds[$("charSelect").value] || [0,0];
  const ms = Math.round((i1-i0)/sr*1000 * f/100);
  $("inspectInfo").textContent = `target=${$("charSelect").value}, frac=${f.toFixed(0)}% (≈${ms}ms / 発話${Math.round((i1-i0)/sr*1000)}ms 中)`;
}
function setupInspect() {
  populateCharSelect();
  $("charSelect").addEventListener("change", inspectInfo);
  $("fSlider").addEventListener("input", inspectInfo);
  $("playInspect").addEventListener("click", () => play($("charSelect").value, parseFloat($("fSlider").value)));
  inspectInfo();
}

// ---- Trial ----------------------------------------------------------------
function pickFrac() {
  const dist = $("rDist").value;
  let f;
  if (dist === "uniform") f = Math.random()*100;
  else if (dist === "low") f = Math.random()*60;
  else if (dist === "grid21") { const g=[]; for(let i=0;i<=100;i+=5)g.push(i); f=g[Math.floor(Math.random()*g.length)]; }
  else { f = lastCorrect ? Math.max(0,lastF-5) : Math.min(100,lastF+5); }   // adaptive
  return Math.max(0, Math.min(100, f));
}
function buildGrid() {
  const div = $("choices"); div.innerHTML = "";
  for (const row of activeGrid) for (const ch of row) {
    if (ch === "") { const s=document.createElement("span"); s.className="spacer"; div.appendChild(s); }
    else { const b=document.createElement("button"); b.textContent=ch; b.onclick=()=>answerTrial(ch); div.appendChild(b); }
  }
}
function startTrial() {
  if (pendingTimer){clearTimeout(pendingTimer);pendingTimer=null;}
  const target = activeChars[Math.floor(Math.random()*activeChars.length)];
  const frac = pickFrac();
  currentTrial = { target, frac, t0: performance.now() };
  $("feedback").style.display = "none";
  buildGrid();
  play(target, frac);
}
function answerTrial(response) {
  if (!currentTrial) return;
  const rt = performance.now() - currentTrial.t0;
  const correct = response === currentTrial.target;
  trialLog.push({ target: currentTrial.target, frac: currentTrial.frac, response, correct,
    n_choices: activeChars.length, q_set: activeChars===KARUTA_CHARS?"karuta":"all", rt_ms: Math.round(rt) });
  lastCorrect = correct; lastF = currentTrial.frac;
  const fb = $("feedback");
  fb.className = "feedback " + (correct?"correct":"wrong");
  fb.textContent = (correct?"✓ 正解":"✗ 不正解 → 正解は「"+currentTrial.target+"」")
    + ` (frac=${currentTrial.frac.toFixed(0)}%, ${Math.round(rt)}ms)`;
  fb.style.display = "inline-block";
  for (const b of $("choices").querySelectorAll("button")) b.disabled = true;
  currentTrial = null; drawStats();
  pendingTimer = setTimeout(()=>{pendingTimer=null; if(mode==="trial")startTrial();}, ITI_MS);
}
function resetTrials(){ trialLog=[]; drawStats(); }
function downloadTrials() {
  const header="trial_idx,target,frac,response,correct,n_choices,q_set,rt_ms";
  const rows=trialLog.map((t,i)=>[i+1,t.target,t.frac,t.response,t.correct,t.n_choices,t.q_set,t.rt_ms].join(","));
  const blob=new Blob([header+"\n"+rows.join("\n")],{type:"text/csv"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="pilot_audio_trunc_trials.csv"; a.click();
}
function setupTrial() {
  $("startTrial").onclick = startTrial;
  $("resetTrials").onclick = resetTrials;
  $("downloadTrials").onclick = downloadTrials;
  $("replayTrial").onclick = () => { if (currentTrial) play(currentTrial.target, currentTrial.frac); };
}

// ---- logistic fit (linear frac axis; reused from pilot.js) ----------------
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

// ---- chart (frac on x, linear 0-100) --------------------------------------
function drawStats() {
  const can=$("chartCanvas"),c=can.getContext("2d");const w=can.width,h=can.height;c.clearRect(0,0,w,h);
  const binW=5,nB=21,bins=Array.from({length:nB},()=>({n:0,c:0}));
  for(const t of trialLog){const bi=Math.min(nB-1,Math.floor(t.frac/binW));bins[bi].n++;if(t.correct)bins[bi].c++;}
  c.strokeStyle="#ccc";c.lineWidth=1;c.beginPath();c.moveTo(40,10);c.lineTo(40,h-24);c.lineTo(w-10,h-24);c.stroke();
  c.fillStyle="#666";c.font="10px monospace";
  for(let y=0;y<=4;y++){const py=10+(h-34)*y/4;c.fillText((100-y*25)+"%",4,py+4);c.strokeStyle="#eee";c.beginPath();c.moveTo(40,py);c.lineTo(w-10,py);c.stroke();}
  const barW=(w-50)/nB;
  for(let i=0;i<nB;i++){const b=bins[i],x=42+i*barW;
    if(b.n>0){const acc=b.c/b.n,bh=acc*(h-34);c.fillStyle="#d6904a";c.fillRect(x,h-24-bh,Math.max(1,barW-2),bh);c.fillStyle="#222";c.fillText(b.n,x+1,h-12);}
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
    $("fitInfo").textContent=`2P logistic: α=${fit.alpha.toFixed(1)}% β=${fit.beta.toFixed(3)} γ=${fit.gamma.toFixed(2)} pseudoR²=${fit.pseudoR2.toFixed(2)} (n=${fit.n})\n`
      +`⌀ 閾値 α (= chance/ceiling 中点, p=${pA.toFixed(3)}): frac=${fit.alpha.toFixed(1)}%`;
  } else $("fitInfo").textContent = trialLog.length>=8?"(全問同正誤などで未フィット)":`(フィットには 8 試行以上必要・現在 ${trialLog.length})`;
  const tot=trialLog.length,cor=trialLog.filter(t=>t.correct).length,rtMed=tot?median(trialLog.map(t=>t.rt_ms)):0;
  $("statsTable").innerHTML=`<table><tr><th>n</th><th>正答</th><th>正答率</th><th>中央RT</th></tr><tr><td>${tot}</td><td>${cor}</td><td>${tot?(100*cor/tot).toFixed(1):"—"}%</td><td>${rtMed.toFixed(0)}ms</td></tr></table>`;
}

// ---- mode switching + boot ------------------------------------------------
function setMode(m){if(pendingTimer){clearTimeout(pendingTimer);pendingTimer=null;}mode=m;
  $("modeInspect").classList.toggle("active",m==="inspect");$("modeTrial").classList.toggle("active",m==="trial");
  $("inspectPanel").style.display=m==="inspect"?"":"none";$("trialPanel").style.display=m==="trial"?"":"none";}
async function boot(){
  $("modeInspect").onclick=()=>setMode("inspect");
  $("modeTrial").onclick=()=>setMode("trial");
  $("qSet").addEventListener("change",()=>{setActiveSet($("qSet").value);populateCharSelect();if(mode==="inspect")inspectInfo();});
  try { await loadAll(); }
  catch(e){ $("loading").textContent="起動エラー: "+e.message; $("loading").style.color="#900"; return; }
  setupInspect(); setupTrial(); drawStats(); setMode("inspect");
}
boot();
