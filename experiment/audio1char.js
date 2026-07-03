// =========================================================================
// 聴覚版 1文字課題 本実験 (統一モデルの C1=∅ = 発話先頭の特殊ケース)
//   - 単一のかなを発話先頭の音高 B3・1文字0.2秒で合成した音声を、frac% まで
//     再生して (truncation) 何の文字かを問う。frac=0 無音 / frac=100 完全 (catch)。
//   - 時間ゲートは再生時に Web Audio でライブ切り出し (audio2char と同方式)。
//   - 回答は固定50音グリッド(全72字)。manifest は公開(回答なし)、正解は answer_key。
// =========================================================================

const SUBMIT_URL = "";              // EDIT BEFORE DEPLOY

const N_TRIALS = 200;
const N_PRACTICE = 5;
const CATCH_RATE = 0.05;
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);
const FADE_MS = 8;

// 全72字の固定50音グリッド (audio.js の GRID_AUDIO と一致)
const GRID_AUDIO = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],["ゔ","","","",""],
];
const GRID_FLAT = GRID_AUDIO.flat();
const GRID_COLS = 5;
const GRID_ROWS = GRID_AUDIO.length;
const N_CHOICES = GRID_FLAT.filter(c => c !== "").length;   // 72

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
let _curSrc = null;

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
// 文字の開始から frac% まで = [char_onset, char_onset + char_dur*frac/100] を再生。
function gatedBuffer(buf, onset, dur, frac) {
  const sr = buf.sampleRate;
  const start = Math.round(onset * sr);
  const len = Math.max(0, Math.round(dur * frac / 100 * sr));
  const src = buf.getChannelData(0);
  const ab = ctx.createBuffer(1, Math.max(1, len), sr);
  const out = ab.getChannelData(0);
  for (let i = 0; i < len; i++) out[i] = src[start + i] || 0;
  const fade = Math.min(Math.round(sr * FADE_MS / 1000), len);
  for (let i = 0; i < fade; i++) out[len - fade + i] *= (1 - i / fade);
  return ab;
}
function playGated(buf, stim) {
  ensureCtx();
  if (_curSrc) { try { _curSrc.stop(); } catch (e) {} }
  if (stim.frac <= 0) { _curSrc = null; return; }   // 無音アンカー
  const s = ctx.createBufferSource();
  s.buffer = gatedBuffer(buf, stim.char_onset_s, stim.char_dur_s, stim.frac);
  s.connect(ctx.destination);
  s.start();
  _curSrc = s;
}

async function loadManifest() {
  const res = await fetch("audio1char_manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("audio1char_manifest.json fetch failed: " + res.status);
  return await res.json();
}
function sampleTrials(manifest, n) {
  const pool = manifest.stimuli || [];
  if (pool.length === 0) throw new Error("audio1char_manifest に刺激がありません");
  // プールは72字なので、必要数だけ復元抽出して frac を割り当てる。
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
  return `<button class="jspsych-btn grid-kana">${choice}</button>`;
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
       <p>各問で、ひらがな1文字の読み上げ音声が流れます。
       発話のごく途中までしか流れず短くて分かりにくい場合もあれば、最後まではっきり聞こえる場合もあります。</p>
       <p>「▶ 音をきく / もう一度」ボタンで <b>何度でも</b> 聞き直せます。
       下の <b>50音表</b>(濁音・半濁音を含む 72 字)から、聞こえたと思う 1 文字を選んでください。
       表は毎回同じ並びです。</p>
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
