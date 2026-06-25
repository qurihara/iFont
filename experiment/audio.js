// =========================================================================
// 聴覚版 Kikiwake 本実験 (音声もやもや = audio F1)
//   - Same fixed 50音 grid response as the visual experiment.js
//   - Stimulus is a chorus mix (all candidate kana), target amplitude raised
//   - k-grid difficulty; manifest = experiment/audio_manifest.json
//   - Catch trials = k = ∞ (r = 100, clear single kana)
//   - Audio is replayable (analog of the persistent visual image); replays
//     are counted and submitted so noisy participants can be filtered.
// =========================================================================

// EDIT BEFORE DEPLOY: deployed Google Apps Script /exec URL.
const SUBMIT_URL = "";

// Which question set this deployment runs. Must exist in audio_manifest.q_sets.
const Q_SET = "all";        // "all" = 全 84 字 / "karuta" = 競技かるた 48 字

const N_TRIALS = 200;
const N_PRACTICE = 5;

// =========================================================================
// Character sets + fixed 50音 grids (mirror experiment.js / pilot.js)
// =========================================================================

// AUDIO response set = 72 字: only the acoustically-distinct kana
// (清音46 + 濁20 + 半5 + ゔ). ゐゑ→いえ, ゃゅょ→やゆよ, っ=無音, 小書き母音→母音
// are degenerate in isolation and are excluded (recovered via the C1≠∅
// 2-char task / assumed = base). Mirrors ifont_common.AUDIO_ALL / AUDIO_KARUTA.
const SEION = [..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"];
const DAKUTEN = [..."がぎぐげござじずぜぞだぢづでどばびぶべぼ"];
const HANDAKU = [..."ぱぴぷぺぽ"];
const OTHER = [..."ゔ"];

const GRID_AUDIO = [
  ["あ","い","う","え","お"],
  ["か","き","く","け","こ"],
  ["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],
  ["な","に","ぬ","ね","の"],
  ["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],
  ["や","",  "ゆ","",  "よ"],
  ["ら","り","る","れ","ろ"],
  ["わ","",  "",  "",  "を"],
  ["ん","",  "",  "",  ""  ],
  ["が","ぎ","ぐ","げ","ご"],
  ["ざ","じ","ず","ぜ","ぞ"],
  ["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],
  ["ぱ","ぴ","ぷ","ぺ","ぽ"],
  ["ゔ","",  "",  "",  ""  ],
];
// Karuta audio grid: 清音 11 rows only (46; ゐゑ folded onto いえ).
const GRID_AUDIO_KARUTA = GRID_AUDIO.slice(0, 11);

const CHARSET_FOR = { all: [...SEION, ...DAKUTEN, ...HANDAKU, ...OTHER],
                      karuta: [...SEION] };
const GRID_FOR = { all: GRID_AUDIO, karuta: GRID_AUDIO_KARUTA };

const activeChars = CHARSET_FOR[Q_SET];
const activeGrid = GRID_FOR[Q_SET];
const N_CHOICES = activeChars.length;       // γ = 1 / N_CHOICES
const GRID_FLAT = activeGrid.flat();
const GRID_COLS = 5;
const GRID_ROWS = activeGrid.length;

// =========================================================================
// Setup
// =========================================================================

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

// Per-trial replay counter (reset in each trial's on_load).
let _replays = 0;

// =========================================================================
// Helpers
// =========================================================================

async function loadManifest() {
  const res = await fetch("audio_manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("audio_manifest.json fetch failed: " + res.status);
  return await res.json();
}

function sampleStimuli(manifest, n) {
  // Truncation clips are shared across sets; each carries the q_sets it is
  // valid for (a karuta char -> ["all","karuta"]).
  const pool = manifest.stimuli.filter(s => (s.q_sets || []).includes(Q_SET));
  if (pool.length === 0) throw new Error(`audio_manifest に q_set="${Q_SET}" がありません`);
  return jsPsych.randomization.sampleWithoutReplacement(pool, Math.min(n, pool.length));
}

function isCatchStim(stim) {
  return stim.frac === 100;          // full clean kana
}

function buttonHtml(choice) {
  if (choice === "") {
    return '<button class="jspsych-btn grid-spacer" disabled tabindex="-1"></button>';
  }
  return `<button class="jspsych-btn grid-kana">${choice}</button>`;
}

function makeTrial(stim, isPractice = false) {
  const isCatch = isCatchStim(stim);
  const src = `audio_stimuli/${stim.id}.mp3`;
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `
      <audio id="stim-audio" src="${src}" preload="auto"></audio>
      <div class="audio-controls">
        <button type="button" id="replay-btn" class="replay-btn">▶ 音をきく / もう一度</button>
      </div>
      <div class="trial-prompt">きこえた文字を 50音表から選んでください</div>`,
    choices: GRID_FLAT,
    button_html: buttonHtml,
    grid_rows: GRID_ROWS,
    grid_columns: GRID_COLS,
    on_load: () => {
      _replays = 0;
      const audio = document.getElementById("stim-audio");
      const btn = document.getElementById("replay-btn");
      // Autoplay once; browsers allow it after the earlier consent click.
      if (audio) {
        const p = audio.play();
        if (p && p.catch) p.catch(() => { /* gesture required; user uses replay */ });
      }
      if (btn && audio) {
        btn.addEventListener("click", () => {
          _replays += 1;
          audio.currentTime = 0;
          audio.play();
        });
      }
    },
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: stim.id,
      modality: "audio",
      q_set: Q_SET,
      frac_index: stim.frac_index,
      frac: stim.frac,
      n_choices: N_CHOICES,
      is_catch: isCatch,
    },
    on_finish: (data) => {
      data.response_char = GRID_FLAT[data.response];
      data.replays = _replays;
      if (!isPractice && SUBMIT_URL) {
        try {
          fetch(SUBMIT_URL, {
            method: "POST",
            mode: "no-cors",
            headers: {"Content-Type": "text/plain;charset=utf-8"},
            body: JSON.stringify({
              participant_id: participantId,
              worker_id: workerId,
              completion_code: completionCode,
              stimulus_id: data.stimulus_id,
              response_char: data.response_char,
              modality: data.modality,
              q_set: data.q_set,
              frac_index: data.frac_index,
              frac: data.frac,
              n_choices: data.n_choices,
              replays: data.replays,
              rt_ms: data.rt,
              is_catch: data.is_catch,
              ts: Date.now(),
            }),
          });
        } catch (e) { console.warn("submit failed:", e); }
      }
    },
  };
}

// =========================================================================
// Timeline
// =========================================================================

async function run() {
  let manifest;
  try {
    manifest = await loadManifest();
  } catch (e) {
    document.body.innerHTML =
      '<p style="padding:40px;color:#900;">音声データの読み込みに失敗しました: ' + e.message + '</p>';
    return;
  }

  let all;
  try {
    all = sampleStimuli(manifest, N_TRIALS + N_PRACTICE);
  } catch (e) {
    document.body.innerHTML = '<p style="padding:40px;color:#900;">' + e.message + '</p>';
    return;
  }
  const practiceStims = all.slice(0, N_PRACTICE);
  const mainStims = all.slice(N_PRACTICE);
  const setLabel = Q_SET === "karuta" ? "競技かるた 48 字" : "全 84 字";

  // NOTE: we deliberately do NOT use jsPsychPreload's `audio:` option.
  // jsPsych preloads audio through the Web Audio API (decodeAudioData), which
  // several browsers (esp. Safari/iOS) refuse before a user gesture — that
  // makes the preload step fail with "The experiment failed to load.".
  // Each trial uses a plain <audio preload="auto"> element instead, which the
  // browser loads on demand; the files are tiny (~2KB) so there is no delay.
  const consent = {
    type: jsPsychInstructions,
    pages: [
      `<h2>インクルーシブ字幕の研究実験（音声版）</h2>
       <p>本実験は、音声で呈示された文字の聞き取りやすさを測ることを目的としています。
       所要時間は約 20 分です。ご協力ありがとうございます。</p>
       <p><b>音声を使用します。スピーカーまたはイヤホン・ヘッドフォンをご用意のうえ、
       音量を適切に調整してください。</b></p>
       <p>取得するデータ: 各設問への回答とその所要時間、参加識別子。
       個人を特定する情報は収集しません。</p>
       <p><b>続けて参加することに同意される場合は「次へ」を押してください。</b></p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "同意して次へ",
  };

  const instructions = {
    type: jsPsychInstructions,
    pages: [
      `<h2>課題</h2>
       <p>各問で、ひらがな1文字の読み上げ音声が再生されます。
       発話のごく途中までしか流れず短くて分かりにくい場合もあれば、最後まではっきり聞こえる場合もあります。</p>
       <p>「▶ 音をきく / もう一度」ボタンで <b>何度でも</b> 聞き直せます。
       下の <b>50音表</b>(${setLabel})から、聞こえたと思う 1 文字を選んでください。表は毎回同じ並びです。</p>
       <p>確信が持てなくても、感覚で答えて構いません。考え込まずに次々と答えてください。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。
       ここで音量を調整してください。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "練習を始める",
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
    show_clickable_nav: true,
    button_label_next: "本番を始める",
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

  jsPsych.run([
    consent,
    instructions,
    ...practiceBlock,
    mainStart,
    ...mainBlock,
    finish,
  ]);
}

run();
