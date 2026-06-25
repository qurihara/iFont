// ===========================================================================
// iFont 聴覚セルフパイロット
//   - Loads 84 base kana mp3s, decodes to PCM via Web Audio.
//   - For target T and parameter k (→ r), mixes the chorus IN THE BROWSER:
//        mix = (a_target - a_other)·base[T] + a_other·Σ base[c]
//        a_target = r/100, a_other = (1-r/100)/N
//     i.e. the same 音声もやもや model as make_audio_stimuli.py, at any k.
//   - Inspect: target + continuous k slider + play.
//   - Trial: random target × k, 50音 grid, immediate feedback, RT, logistic fit.
//   Mirrors experiment/pilot.js (visual) for the auditory modality.
// ===========================================================================

const CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."がぎぐげござじずぜぞだぢづでどばびぶべぼ",
  ..."ぱぴぷぺぽ",
  ..."ぁぃぅぇぉっゃゅょゎ",
  ..."ゐゑ",
  ..."ゔ",
];
const KARUTA_CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."ゐゑ",
];

// 50音 grids (same layout as pilot.js / experiment.js).
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

const OUT_RMS = 0.12, PEAK_LIMIT = 0.97;

const $ = (id) => document.getElementById(id);

// ---- state ----------------------------------------------------------------
let ctx = null;                  // AudioContext (created on first gesture)
let basePCM = {};                // char -> Float32Array (decoded, padded)
let maxLen = 0, sr = 0;
let sumAll = null, sumKaruta = null;  // Float32Array sums per set
let activeChars = CHARS, activeGrid = GRID_84, activeSum = null;
let mode = "inspect";
let currentTrial = null, trialLog = [], lastCorrect = true, lastR = 50;
let pendingTimer = null;
const ITI_MS = 1000;

// ---- k <-> r --------------------------------------------------------------
function nDistr() { return activeChars.length - 1; }
function rToK(r, n) { const N = (n==null)?nDistr():n; return r>=100 ? Infinity : N*r/(100-r); }
function kToR(k, n) { const N = (n==null)?nDistr():n; return !isFinite(k) ? 100 : 100*k/(N+k); }
function fmtK(k) { return !isFinite(k) ? "∞" : (k>=100?k.toFixed(0):k>=10?k.toFixed(1):k.toFixed(2)); }

// ---- load + decode --------------------------------------------------------
async function fetchPCM(ch) {
  const res = await fetch(`audio_base/${encodeURIComponent(ch)}.mp3`, {cache: "force-cache"});
  if (!res.ok) throw new Error(`audio_base/${ch}.mp3 ${res.status}`);
  const buf = await res.arrayBuffer();
  const audioBuf = await ctx.decodeAudioData(buf);
  return audioBuf.getChannelData(0).slice();   // copy Float32
}

async function loadAll() {
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  sr = ctx.sampleRate;
  const raw = {};
  for (const ch of CHARS) raw[ch] = await fetchPCM(ch);
  maxLen = Math.max(...Object.values(raw).map(a => a.length));
  for (const ch of CHARS) {
    const a = raw[ch];
    if (a.length < maxLen) { const b = new Float32Array(maxLen); b.set(a); basePCM[ch] = b; }
    else basePCM[ch] = a;
  }
  sumAll = sumOver(CHARS);
  sumKaruta = sumOver(KARUTA_CHARS);
  setActiveSet($("qSet").value);
  $("loading").style.display = "none";
}

function sumOver(chars) {
  const s = new Float32Array(maxLen);
  for (const ch of chars) { const a = basePCM[ch]; for (let i=0;i<maxLen;i++) s[i]+=a[i]; }
  return s;
}

function setActiveSet(name) {
  if (name === "karuta") { activeChars = KARUTA_CHARS; activeGrid = GRID_KARUTA; activeSum = sumKaruta; }
  else { activeChars = CHARS; activeGrid = GRID_84; activeSum = sumAll; }
}

// ---- mixing + playback ----------------------------------------------------
function mixBuffer(target, r) {
  const N = nDistr();
  const aT = r/100, aO = (1-aT)/N;
  const tgt = basePCM[target];
  const out = new Float32Array(maxLen);
  // (aT - aO)·target + aO·Σactive
  const c = aT - aO;
  for (let i=0;i<maxLen;i++) out[i] = c*tgt[i] + aO*activeSum[i];
  // RMS normalize + peak limit
  let ss=0; for (let i=0;i<maxLen;i++) ss+=out[i]*out[i];
  const rms = Math.sqrt(ss/maxLen)+1e-12;
  let g = OUT_RMS/rms, peak=0;
  for (let i=0;i<maxLen;i++){ const v=Math.abs(out[i]*g); if(v>peak)peak=v; }
  if (peak>PEAK_LIMIT) g *= PEAK_LIMIT/peak;
  const ab = ctx.createBuffer(1, maxLen, sr);
  const ch0 = ab.getChannelData(0);
  for (let i=0;i<maxLen;i++) ch0[i]=out[i]*g;
  return ab;
}

let _activeSrc = null;
function play(target, r) {
  if (ctx.state === "suspended") ctx.resume();
  if (_activeSrc) { try { _activeSrc.stop(); } catch(e){} }
  const src = ctx.createBufferSource();
  src.buffer = mixBuffer(target, r);
  src.connect(ctx.destination);
  src.start();
  _activeSrc = src;
}

// ---- Inspect --------------------------------------------------------------
function populateCharSelect() {
  const sel = $("charSelect"); sel.innerHTML = "";
  for (const c of activeChars) { const o=document.createElement("option"); o.value=c; o.textContent=c; sel.appendChild(o); }
  sel.value = activeChars.includes("あ") ? "あ" : activeChars[0];
}
function inspectInfo() {
  const k = Math.pow(2, parseFloat($("kSlider").value));
  const r = kToR(k);
  $("kValue").textContent = `k=${fmtK(k)}`;
  $("inspectInfo").textContent =
    `target=${$("charSelect").value}, k=${fmtK(k)}, r=${r.toFixed(2)}% (${activeChars===KARUTA_CHARS?"karuta48":"全84"}字中)`;
}
function setupInspect() {
  populateCharSelect();
  $("charSelect").addEventListener("change", inspectInfo);
  $("kSlider").addEventListener("input", inspectInfo);
  $("playInspect").addEventListener("click", () => {
    const k = Math.pow(2, parseFloat($("kSlider").value));
    play($("charSelect").value, kToR(k));
  });
  inspectInfo();
}

// ---- Trial ----------------------------------------------------------------
function pickR() {
  const dist = $("rDist").value;
  let r;
  if (dist === "uniform") r = Math.random()*100;
  else if (dist === "logK") r = kToR(Math.pow(2, -1 + Math.random()*8));
  else if (dist === "logKWide") r = kToR(Math.pow(2, -2 + Math.random()*10));
  else if (dist === "kGrid11") { const g=[0,0.5,1,2,4,8,16,32,64,128,Infinity]; r=kToR(g[Math.floor(Math.random()*g.length)]); }
  else { const cur=rToK(lastR); const nx=lastCorrect?cur/Math.SQRT2:cur*Math.SQRT2; r=kToR(Math.min(1024,Math.max(0.1,nx))); }
  return Math.max(0, Math.min(100, r));
}

function buildGrid() {
  const div = $("choices"); div.innerHTML = "";
  for (const row of activeGrid) for (const ch of row) {
    if (ch === "") { const s=document.createElement("span"); s.className="spacer"; div.appendChild(s); }
    else { const b=document.createElement("button"); b.textContent=ch; b.onclick=()=>answerTrial(ch); div.appendChild(b); }
  }
}

function startTrial() {
  if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer=null; }
  const target = activeChars[Math.floor(Math.random()*activeChars.length)];
  const r = pickR();
  currentTrial = { target, r, t0: performance.now() };
  $("feedback").style.display = "none";
  buildGrid();
  play(target, r);            // autoplay once
}

function answerTrial(response) {
  if (!currentTrial) return;
  const rt = performance.now() - currentTrial.t0;
  const correct = response === currentTrial.target;
  trialLog.push({
    target: currentTrial.target, r: currentTrial.r, k: rToK(currentTrial.r),
    response, correct, n_choices: activeChars.length,
    q_set: activeChars===KARUTA_CHARS?"karuta":"all", rt_ms: Math.round(rt),
  });
  lastCorrect = correct; lastR = currentTrial.r;
  const kv = rToK(currentTrial.r);
  const fb = $("feedback");
  fb.className = "feedback " + (correct?"correct":"wrong");
  fb.textContent = (correct?"✓ 正解":"✗ 不正解 → 正解は「"+currentTrial.target+"」")
    + ` (k=${fmtK(kv)}, r=${currentTrial.r.toFixed(2)}%, ${Math.round(rt)}ms)`;
  fb.style.display = "inline-block";
  for (const b of $("choices").querySelectorAll("button")) b.disabled = true;
  currentTrial = null;
  drawStats();
  pendingTimer = setTimeout(() => { pendingTimer=null; if (mode==="trial") startTrial(); }, ITI_MS);
}

function resetTrials() { trialLog = []; drawStats(); }
function downloadTrials() {
  const header = "trial_idx,target,r,k,response,correct,n_choices,q_set,rt_ms";
  const rows = trialLog.map((t,i)=>[i+1,t.target,t.r,(isFinite(t.k)?t.k.toFixed(4):"Inf"),
    t.response,t.correct,t.n_choices,t.q_set,t.rt_ms].join(","));
  const blob = new Blob([header+"\n"+rows.join("\n")], {type:"text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "pilot_audio_trials.csv"; a.click();
}

function setupTrial() {
  $("startTrial").onclick = startTrial;
  $("resetTrials").onclick = resetTrials;
  $("downloadTrials").onclick = downloadTrials;
  $("replayTrial").onclick = () => { if (currentTrial) play(currentTrial.target, currentTrial.r); };
  $("chartAxis").addEventListener("change", drawStats);
}

// ---- logistic fit (verbatim from pilot.js) --------------------------------
function logL(data, alpha, beta) {
  let ll = 0;
  for (const [x,y,gamma] of data) {
    const z = beta*(x-alpha);
    const sig = z>=0 ? 1/(1+Math.exp(-z)) : Math.exp(z)/(1+Math.exp(z));
    let p = gamma+(1-gamma)*sig;
    if (p<1e-9) p=1e-9; else if (p>1-1e-9) p=1-1e-9;
    ll += y*Math.log(p)+(1-y)*Math.log(1-p);
  }
  return ll;
}
function fitLogistic(trials, axis) {
  const data = [];
  for (const t of trials) {
    let x;
    if (axis==="logK") { if(!isFinite(t.k)) x=10; else if(t.k<=1e-3) x=-10; else x=Math.log2(t.k); }
    else x = t.r;
    const gamma = 1/Math.max(2, t.n_choices||4);
    data.push([x, t.correct?1:0, gamma]);
  }
  if (data.length<8) return null;
  const nc = data.filter(d=>d[1]===1).length;
  if (nc===0 || nc===data.length) return null;
  let aLo,aHi,bLo,bHi;
  if (axis==="logK"){aLo=-3;aHi=10;bLo=0.05;bHi=8;} else {aLo=0;aHi=100;bLo=0.005;bHi=1.5;}
  let bestA=(aLo+aHi)/2,bestB=(bLo+bHi)/2,bestLL=-Infinity; const N=30;
  for (let pass=0;pass<4;pass++){
    let ca=bestA,cb=bestB,cll=bestLL;
    for(let i=0;i<=N;i++){const a=aLo+(aHi-aLo)*i/N;
      for(let j=0;j<=N;j++){const b=bLo+(bHi-bLo)*j/N;const ll=logL(data,a,b);if(ll>cll){cll=ll;ca=a;cb=b;}}}
    bestA=ca;bestB=cb;bestLL=cll;
    const aS=(aHi-aLo)/N*2,bS=(bHi-bLo)/N*2;
    aLo=bestA-aS;aHi=bestA+aS;bLo=Math.max(1e-4,bestB-bS);bHi=bestB+bS;
  }
  const meanAcc=data.reduce((s,d)=>s+d[1],0)/data.length;
  let llNull=0; for(const [,y] of data){const p=Math.max(1e-9,Math.min(1-1e-9,meanAcc));llNull+=y*Math.log(p)+(1-y)*Math.log(1-p);}
  const r2 = llNull<0 ? 1-bestLL/llNull : 0;
  const counts={}; for(const [,,g] of data) counts[g]=(counts[g]||0)+1;
  const modalGamma = Object.entries(counts).sort((a,b)=>b[1]-a[1])[0][0]*1;
  return {alpha:bestA,beta:bestB,gamma:modalGamma,n:data.length,pseudoR2:r2};
}
function logisticP(x, fit) {
  const z=fit.beta*(x-fit.alpha);
  const sig = z>=0 ? 1/(1+Math.exp(-z)) : Math.exp(z)/(1+Math.exp(z));
  return fit.gamma+(1-fit.gamma)*sig;
}
function median(xs){ if(!xs.length)return 0; const s=xs.slice().sort((a,b)=>a-b); const m=Math.floor(s.length/2); return s.length%2?s[m]:(s[m-1]+s[m])/2; }

// ---- chart ----------------------------------------------------------------
function drawStats() {
  const axis = $("chartAxis").value;
  const can = $("chartCanvas"), c = can.getContext("2d");
  const w = can.width, h = can.height; c.clearRect(0,0,w,h);

  let bins, labels, binW, axisLabel;
  if (axis==="logK") {
    const lo=-2, hi=8; binW=0.5; const nB=Math.round((hi-lo)/binW)+1;
    bins=Array.from({length:nB},()=>({n:0,c:0})); labels=[];
    for(let i=0;i<nB-1;i++)labels.push(Math.pow(2,lo+i*binW)); labels.push(Infinity);
    for(const t of trialLog){ let bi; if(!isFinite(t.k))bi=nB-1; else if(t.k<=0)bi=0;
      else bi=Math.max(0,Math.min(nB-2,Math.floor((Math.log2(t.k)-lo)/binW)));
      bins[bi].n++; if(t.correct)bins[bi].c++; }
    axisLabel="k (½ oct bin)";
  } else {
    binW=10; const nB=11; bins=Array.from({length:nB},()=>({n:0,c:0})); labels=[];
    for(let i=0;i<nB;i++)labels.push(i*binW);
    for(const t of trialLog){ const bi=Math.min(nB-1,Math.floor(t.r/binW)); bins[bi].n++; if(t.correct)bins[bi].c++; }
    axisLabel="r%";
  }

  c.strokeStyle="#ccc"; c.lineWidth=1;
  c.beginPath(); c.moveTo(40,10); c.lineTo(40,h-24); c.lineTo(w-10,h-24); c.stroke();
  c.fillStyle="#666"; c.font="10px monospace";
  for(let y=0;y<=4;y++){const py=10+(h-34)*y/4; c.fillText((100-y*25)+"%",4,py+4);
    c.strokeStyle="#eee"; c.beginPath(); c.moveTo(40,py); c.lineTo(w-10,py); c.stroke();}
  const nV=bins.length, barW=(w-50)/nV, lblStep=Math.max(1,Math.round(nV/12));
  for(let i=0;i<nV;i++){const b=bins[i],x=42+i*barW;
    if(b.n>0){const acc=b.c/b.n,bh=acc*(h-34); c.fillStyle="#d6904a"; c.fillRect(x,h-24-bh,Math.max(1,barW-2),bh);
      c.fillStyle="#222"; c.fillText(b.n,x+2,h-12);}
    if(i%lblStep===0){const lb=labels[i]; const s=!isFinite(lb)?"∞":(axis==="logK"?fmtK(lb):lb.toFixed(0));
      c.fillStyle="#666"; c.fillText(s,x+2,h-2);}}
  c.fillStyle="#999"; c.fillText(axisLabel,w-90,h-2);

  // logistic overlay
  const fit = fitLogistic(trialLog, axis);
  if (fit) {
    let xMin,xMax,toIdx;
    if(axis==="logK"){const lo=-2; xMin=lo; xMax=lo+(nV-1)*binW; toIdx=x=>(x-lo)/binW;}
    else {xMin=0; xMax=(nV-1)*binW; toIdx=x=>x/binW;}
    c.strokeStyle="#b5402a"; c.lineWidth=2; c.beginPath();
    for(let i=0;i<=200;i++){const x=xMin+(xMax-xMin)*i/200; const p=logisticP(x,fit);
      const px=42+(toIdx(x)+0.5)*barW, py=(h-24)-p*(h-34);
      if(i===0)c.moveTo(px,py); else c.lineTo(px,py);}
    c.stroke();
    const pAlpha = fit.gamma+(1-fit.gamma)*0.5;
    if(fit.alpha>=xMin && fit.alpha<=xMax){
      const px=42+(toIdx(fit.alpha)+0.5)*barW, py=(h-24)-pAlpha*(h-34);
      c.fillStyle="#b5402a"; c.beginPath(); c.arc(px,py,5,0,2*Math.PI); c.fill();
      c.strokeStyle="#b5402a"; c.setLineDash([2,3]); c.beginPath(); c.moveTo(px,h-24); c.lineTo(px,py); c.stroke(); c.setLineDash([]);
    }
    let unit;
    if(axis==="logK"){const ka=Math.pow(2,fit.alpha); unit=`log₂k=${fit.alpha.toFixed(2)} (k≈${fmtK(ka)}, r≈${kToR(ka).toFixed(2)}%)`;}
    else unit=`r=${fit.alpha.toFixed(2)}%`;
    $("fitInfo").textContent =
      `2P logistic: α=${fit.alpha.toFixed(2)} β=${fit.beta.toFixed(2)} γ=${fit.gamma.toFixed(2)} pseudoR²=${fit.pseudoR2.toFixed(2)} (n=${fit.n})\n`
      + `⌀ 閾値 α (= chance/ceiling 中点, p=${pAlpha.toFixed(3)}): ${unit}`;
  } else {
    $("fitInfo").textContent = trialLog.length>=8 ? "(全問同正誤などで未フィット)" : `(フィットには 8 試行以上必要・現在 ${trialLog.length})`;
  }

  const tot=trialLog.length, cor=trialLog.filter(t=>t.correct).length;
  const rtMed=tot?median(trialLog.map(t=>t.rt_ms)):0;
  $("statsTable").innerHTML = `<table><tr><th>n</th><th>正答</th><th>正答率</th><th>中央RT</th></tr>`
    + `<tr><td>${tot}</td><td>${cor}</td><td>${tot?(100*cor/tot).toFixed(1):"—"}%</td><td>${rtMed.toFixed(0)}ms</td></tr></table>`;
}

// ---- mode switching -------------------------------------------------------
function setMode(m) {
  if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer=null; }
  mode = m;
  $("modeInspect").classList.toggle("active", m==="inspect");
  $("modeTrial").classList.toggle("active", m==="trial");
  $("inspectPanel").style.display = m==="inspect" ? "" : "none";
  $("trialPanel").style.display = m==="trial" ? "" : "none";
}

// ---- boot -----------------------------------------------------------------
async function boot() {
  $("modeInspect").onclick = () => setMode("inspect");
  $("modeTrial").onclick = () => setMode("trial");
  $("qSet").addEventListener("change", () => {
    setActiveSet($("qSet").value);
    populateCharSelect();
    if (mode==="inspect") inspectInfo();
  });
  try {
    await loadAll();
  } catch (e) {
    $("loading").textContent = "起動エラー: " + e.message;
    $("loading").style.color = "#900";
    return;
  }
  setupInspect();
  setupTrial();
  drawStats();
  setMode("inspect");
}

// AudioContext needs a user gesture; create it lazily on first interaction.
// We attempt to load immediately, but if the context starts suspended the
// first play()/start() resumes it.
boot();
