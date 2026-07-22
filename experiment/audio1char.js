// =========================================================================
// 聴覚版 1文字課題 本実験 (統一モデルの C1=∅ = 発話先頭の特殊ケース)
//   - 単一のかなを発話先頭の音高 B3・1文字0.2秒で合成した音声を、frac% まで
//     再生して (truncation) 何の文字かを問う。frac=0 無音 / frac=100 完全 (catch)。
//   - 時間ゲートは再生時に Web Audio でライブ切り出し (audio2char と同方式)。
//   - 時間ゲートは実測の音響的開始(gate_onset_ms)を起点に、量子化済みゲイン(gate_gain)を適用する(2026-07-23修正)。
//   - 回答は固定50音グリッド(68字。を・ぢ・づ・ゔは同音のため除外、同音は併記ボタン)。
//     manifest は公開(回答なし・68刺激)、正解は answer_key。
// =========================================================================

const SUBMIT_URL = "";              // EDIT BEFORE DEPLOY

const N_TRIALS = 200;
const N_PRACTICE = 5;
const CATCH_RATE = 0.05;
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);
const FADE_MS = 8;
// 各問の音声の前後に鳴らす合図音(ビープ)。開始と終了が分かるようにするため。
const BEEP_HZ = 880;         // 合図音の高さ
const BEEP_MS = 80;          // 合図音1回の長さ
const BEEP_LEAD_MS = 300;    // 開始の合図音から、文字の音声が始まるまでの間隔
const END_GAP_MS = 500;      // 文字の音声が終わってから、終了の合図音までの間隔
const END_BEEP_GAP_MS = 140; // 終了の合図音を2回鳴らすときの、1回目と2回目の間隔

// 68音の固定50音グリッド (pilot_soa_audio.js の GRID_AUDIO と一致=乙課題と統一)。
// を・ぢ・づ は お・じ・ず と同音、ゔ は ぶ と区別されないため、出題・回答から外す。
// 同音の別表記は「じ／ぢ」のように1ボタンに併記する(HOMOPHONE_LABEL。値は代表音)。
const GRID_AUDIO = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","ん"],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","","","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
];
const GRID_FLAT = GRID_AUDIO.flat();
const GRID_COLS = 5;
const GRID_ROWS = GRID_AUDIO.length;
const N_CHOICES = GRID_FLAT.filter(c => c !== "").length;   // 68

// 同音のかなを1つのボタンに併記する。表示は併記、値(採点・記録)は代表音(左)。
// 単音を聞いて綴りを確定できない同音字(お／を・じ／ぢ・ず／づ)を、音のクラスとして正直に名づける。
const HOMOPHONE_LABEL = { "お": "お／を", "じ": "じ／ぢ", "ず": "ず／づ" };
function kanaLabel(ch) { return HOMOPHONE_LABEL[ch] || ch; }

const params = new URLSearchParams(window.location.search);
const workerId = params.get("worker_id") || params.get("wid") || "";
const participantId = workerId || ("anon-" + Math.random().toString(36).slice(2, 10));
const completionCode = Array.from({length: 16},
  () => "ABCDEFGHJKMNPQRSTUVWXYZ23456789"[Math.floor(Math.random() * 30)]).join("");

const jsPsych = initJsPsych({
  display_element: document.body,
  show_progress_bar: true,
  message_progress_bar: "進捗",
});

let ctx = null;
const _bufCache = {};
let _replays = 0;
let _nodes = [];   // 予約済みの音声ノード(合図音・刺激)。再生し直すときにまとめて止める。

function ensureCtx() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}
async function decodeStim(stim) {
  if (_bufCache[stim.id]) return _bufCache[stim.id];
  const res = await fetch(`audio1char_stimuli/${stim.id}.mp3`, {cache: "force-cache"});
  if (!res.ok) throw new Error(`audio1char_stimuli/${stim.id}.mp3 ${res.status}`);
  const buf = await ensureCtx().decodeAudioData(await res.arrayBuffer());
  _bufCache[stim.id] = buf;
  return buf;
}
// 実測の音響的開始から、スロット末までの残りの frac% を再生。
function gatedBuffer(buf, stim) {
  const sr = buf.sampleRate;
  const onsetMs = (typeof stim.gate_onset_ms === "number") ? stim.gate_onset_ms : 0;
  const gain = (typeof stim.gate_gain === "number") ? stim.gate_gain : 1.0;
  const start = Math.round((stim.char_onset_s + onsetMs / 1000) * sr);
  const avail = Math.max(0.01, stim.char_dur_s - onsetMs / 1000);
  const len = Math.max(0, Math.round(avail * stim.frac / 100 * sr));
  const src = buf.getChannelData(0);
  const ab = ctx.createBuffer(1, Math.max(1, len), sr);
  const out = ab.getChannelData(0);
  for (let i = 0; i < len; i++) out[i] = (src[start + i] || 0) * gain;
  const fade = Math.min(Math.round(sr * FADE_MS / 1000), len >> 1);
  for (let i = 0; i < fade; i++) {
    out[i] *= i / fade;
    out[len - 1 - i] *= i / fade;
  }
  return ab;
}
// 予約済みの音声ノードをまとめて止める(再生し直し・次の問への移行時)。
function stopAll() {
  for (const n of _nodes) { try { n.stop(); } catch (e) {} }
  _nodes = [];
}
// 合図音(短いビープ)を when 秒に鳴らす。
function playBeep(when) {
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = "sine";
  osc.frequency.value = BEEP_HZ;
  osc.connect(g); g.connect(ctx.destination);
  g.gain.setValueAtTime(0.0001, when);
  g.gain.exponentialRampToValueAtTime(0.12, when + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, when + BEEP_MS / 1000);
  osc.start(when);
  osc.stop(when + BEEP_MS / 1000 + 0.02);
  _nodes.push(osc);
}
// 1問の再生: 開始の合図音 → 文字の音声 → (終わって0.5秒後に)終了の合図音を2回。
function playGated(buf, stim) {
  ensureCtx();
  stopAll();
  const t0 = ctx.currentTime + 0.02;
  playBeep(t0);                                     // 開始の合図音(1回)
  const stimStart = t0 + BEEP_LEAD_MS / 1000;
  const onsetMs = (typeof stim.gate_onset_ms === "number") ? stim.gate_onset_ms : 0;
  const stimDur = Math.max(0, (stim.char_dur_s - onsetMs / 1000)) * stim.frac / 100; // 実際に鳴る音声の長さ(frac=0なら0)
  if (stim.frac > 0) {                              // 無音の問でも合図音は前後に鳴る
    const s = ctx.createBufferSource();
    s.buffer = gatedBuffer(buf, stim);
    s.connect(ctx.destination);
    s.start(stimStart);
    _nodes.push(s);
  }
  const endAt = stimStart + stimDur + END_GAP_MS / 1000;
  playBeep(endAt);                                  // 終了の合図音(開始と区別するため2回)
  playBeep(endAt + END_BEEP_GAP_MS / 1000);
}

async function loadManifest() {
  const res = await fetch("audio1char_manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("audio1char_manifest.json fetch failed: " + res.status);
  return await res.json();
}
function sampleTrials(manifest, n) {
  const pool = manifest.stimuli || [];
  if (pool.length === 0) throw new Error("audio1char_manifest に刺激がありません");
  // プールは68刺激(を・ぢ・づ・ゔ除外)なので、必要数だけ復元抽出して frac を割り当てる。
  const out = [];
  for (let i = 0; i < n; i++) {
    const s = pool[Math.floor(Math.random() * pool.length)];
    const isCatch = Math.random() < CATCH_RATE;
    const frac = isCatch ? 100 : FRAC_GRID[Math.floor(Math.random() * FRAC_GRID.length)];
    out.push(Object.assign({}, s, {frac, is_catch: isCatch}));
  }
  return out;
}

function buttonHtml(choice) {
  if (choice === "") return '<button class="jspsych-btn grid-spacer" disabled tabindex="-1"></button>';
  return `<button class="jspsych-btn grid-kana">${kanaLabel(choice)}</button>`;
}

function makeTrial(stim, isPractice = false) {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `
      <div class="audio-controls">
        <button type="button" id="replay-btn" class="replay-btn">▶ 音をきく / もう一度</button>
      </div>
      <div class="trial-prompt">ひらがな1文字の読み上げが流れます。きこえた文字を 50音表から選んでください</div>`,
    choices: GRID_FLAT,
    button_html: buttonHtml,
    grid_rows: GRID_ROWS,
    grid_columns: GRID_COLS,
    on_load: () => {
      _replays = 0;
      const btn = document.getElementById("replay-btn");
      decodeStim(stim).then(buf => {
        playGated(buf, stim);
        if (btn) btn.addEventListener("click", () => { _replays += 1; playGated(buf, stim); });
      }).catch(err => {
        const p = document.querySelector(".trial-prompt");
        if (p) p.textContent = "音声の読み込みに失敗しました: " + err.message;
      });
    },
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: stim.id,
      modality: "audio1char",
      q_set: "all",
      pitch_scheme: "B3",
      frac: stim.frac,
      n_choices: N_CHOICES,
      is_catch: stim.is_catch,
    },
    on_finish: (data) => {
      data.response_char = GRID_FLAT[data.response];
      data.replays = _replays;
      if (!isPractice && SUBMIT_URL) {
        try {
          fetch(SUBMIT_URL, {
            method: "POST", mode: "no-cors",
            headers: {"Content-Type": "text/plain;charset=utf-8"},
            body: JSON.stringify({
              participant_id: participantId, worker_id: workerId,
              completion_code: completionCode, stimulus_id: data.stimulus_id,
              response_char: data.response_char, modality: data.modality,
              q_set: data.q_set, pitch_scheme: data.pitch_scheme, frac: data.frac,
              n_choices: data.n_choices, replays: data.replays, rt_ms: data.rt,
              is_catch: data.is_catch, ts: Date.now(),
            }),
          });
        } catch (e) { console.warn("submit failed:", e); }
      }
    },
  };
}

async function run() {
  let manifest;
  try { manifest = await loadManifest(); }
  catch (e) {
    document.body.innerHTML =
      '<p style="padding:40px;color:#900;">音声データの読み込みに失敗しました: ' + e.message + '</p>';
    return;
  }
  let all;
  try { all = sampleTrials(manifest, N_TRIALS + N_PRACTICE); }
  catch (e) { document.body.innerHTML = '<p style="padding:40px;color:#900;">' + e.message + '</p>'; return; }
  const practiceStims = all.slice(0, N_PRACTICE);
  const mainStims = all.slice(N_PRACTICE);

  const consent = {
    type: jsPsychInstructions,
    pages: [
      `<h2>インクルーシブ字幕の研究実験（音声・1文字版）</h2>
       <p>本実験は、音声で呈示された文字の聞き取りやすさを測ることを目的としています。
       所要時間は約 20 分です。ご協力ありがとうございます。</p>
       <p><b>音声を使用します。スピーカーまたはイヤホン・ヘッドフォンをご用意のうえ、
       音量を適切に調整してください。</b></p>
       <p>取得するデータ: 各設問への回答とその所要時間、参加識別子。
       個人を特定する情報は収集しません。</p>
       <p><b>続けて参加することに同意される場合は「次へ」を押してください。</b></p>`,
    ],
    show_clickable_nav: true, button_label_next: "同意して次へ",
  };
  const instructions = {
    type: jsPsychInstructions,
    pages: [
      `<h2>課題</h2>
       <p>各問で、まず短い「ピッ」という合図音が1回鳴り、そのあとに、ひらがな1文字の読み上げ音声が流れます。
       読み上げが終わってしばらくすると、今度は合図音が「ピッピッ」と2回鳴り、その問が終わったことをお知らせします。
       始まりの合図音は1回、終わりの合図音は2回で区別できます。</p>
       <p>読み上げは、発話のごく途中までしか流れず短くて分かりにくい場合もあれば、
       最後まではっきり聞こえる場合もあります。ほとんど何も聞こえない問もありますが、その場合も合図音は前後に鳴ります。</p>
       <p>「▶ 音をきく / もう一度」ボタンで <b>何度でも</b> 聞き直せます。
       下の <b>50音表</b>(濁音・半濁音を含む 68 字)から、聞こえたと思う 1 文字を選んでください。
       表は毎回同じ並びです。</p>
       <p>かなは<b>単独で読んだときの音</b>です（「は」はハ、「へ」はヘ）。
       「じ／ぢ」のように<b>同じ音のかなは1つのボタンにまとめて</b>あり、どちらの字かを選ぶ必要はありません。</p>
       <p>確信が持てなくても、感覚で答えて構いません。考え込まずに次々と答えてください。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。
       ここで音量を調整してください。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true, button_label_next: "練習を始める",
  };
  const practiceBlock = practiceStims.map(s => makeTrial(s, true));
  const mainStart = {
    type: jsPsychInstructions,
    pages: [
      `<h2>練習終了</h2>
       <p>続いて本番 ${mainStims.length} 問に入ります。
       静かで集中できる環境で挑んでください。</p>
       <p>準備ができたら「本番を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true, button_label_next: "本番を始める",
  };
  const mainBlock = mainStims.map(s => makeTrial(s, false));
  const finish = {
    type: jsPsychHtmlButtonResponse,
    stimulus: () => `
      <h2>ご協力ありがとうございました</h2>
      <p>下の <b>完了コード</b> を、応募元の入力欄に貼り付けてください。</p>
      <p><span class="completion-code">${completionCode}</span></p>
      <p style="font-size:12px;color:#666;">
        参加者ID: ${participantId} ／ 所要時間: ${Math.round(jsPsych.getTotalTime() / 1000)} 秒
      </p>`,
    choices: ["閉じる"],
  };

  jsPsych.run([consent, instructions, ...practiceBlock, mainStart, ...mainBlock, finish]);
}

run();
