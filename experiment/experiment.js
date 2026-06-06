// =========================================================================
// 視覚版 Kikiwake 本実験 (減算 F1)
//   - Fixed 50音 grid response (no distractors), q_set = all (84) / karuta (48)
//   - k-grid difficulty (manifest carries q_set, k_index, k, r per stimulus)
//   - Catch trials = k = ∞ (r = 100, target-only)
// =========================================================================

// EDIT BEFORE DEPLOY: deployed Google Apps Script /exec URL.
// Leave "" during development to skip submission and just log to console.
const SUBMIT_URL = "";

// Which question set this deployment runs. Must exist in manifest.q_sets.
//   "all"    = 全 84 字
//   "karuta" = 競技かるた 48 字 (清音46 + ゐゑ)
const Q_SET = "all";

// Number of main trials per participant (excluding practice).
const N_TRIALS = 200;
const N_PRACTICE = 5;

// =========================================================================
// Character sets + fixed 50音 grids (mirror experiment/pilot.js)
// =========================================================================

const SEION = [..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"];
const DAKUTEN = [..."がぎぐげござじずぜぞだぢづでどばびぶべぼ"];
const HANDAKU = [..."ぱぴぷぺぽ"];
const SMALL = [..."ぁぃぅぇぉっゃゅょゎ"];
const KOGO = [..."ゐゑ"];
const OTHER = [..."ゔ"];

// 50音 layout. "" cells are spacers so あ/か/さ… rows line up and any kana
// is fast to find. Rendered as hidden, disabled buttons.
const GRID_84 = [
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
  ["ぁ","ぃ","ぅ","ぇ","ぉ"],
  ["ゃ","",  "ゅ","",  "ょ"],
  ["っ","",  "",  "",  "ゎ"],
  ["ゐ","",  "",  "",  "ゑ"],
  ["ゔ","",  "",  "",  ""  ],
];

// Karuta grid: 清音 11 rows + ゐゑ row.
const GRID_KARUTA = [...GRID_84.slice(0, 11), GRID_84[GRID_84.length - 2]];

const CHARSET_FOR = { all: [...SEION, ...DAKUTEN, ...HANDAKU, ...SMALL, ...KOGO, ...OTHER],
                      karuta: [...SEION, ...KOGO] };
const GRID_FOR = { all: GRID_84, karuta: GRID_KARUTA };

const activeChars = CHARSET_FOR[Q_SET];
const activeGrid = GRID_FOR[Q_SET];
const N_CHOICES = activeChars.length;            // γ = 1 / N_CHOICES
const GRID_FLAT = activeGrid.flat();             // includes "" spacers
const GRID_COLS = 5;
const GRID_ROWS = activeGrid.length;

// =========================================================================
// Setup
// =========================================================================

const params = new URLSearchParams(window.location.search);
const workerId = params.get("worker_id") || params.get("wid") || "";
const participantId = workerId || ("anon-" + Math.random().toString(36).slice(2, 10));

// Random 16-char completion code; also recorded server-side for verification.
const completionCode = Array.from({length: 16},
  () => "ABCDEFGHJKMNPQRSTUVWXYZ23456789"[Math.floor(Math.random() * 30)]).join("");

const jsPsych = initJsPsych({
  display_element: document.body,
  show_progress_bar: true,
  message_progress_bar: "進捗",
});

// =========================================================================
// Helpers
// =========================================================================

async function loadManifest() {
  const res = await fetch("manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("manifest.json fetch failed: " + res.status);
  return await res.json();
}

function sampleStimuli(manifest, n) {
  const pool = manifest.stimuli.filter(s => s.q_set === Q_SET);
  if (pool.length === 0) {
    throw new Error(`manifest に q_set="${Q_SET}" の刺激がありません`);
  }
  return jsPsych.randomization.sampleWithoutReplacement(pool, Math.min(n, pool.length));
}

// A stimulus is a catch trial iff k = ∞ (serialized as null) → r = 100.
function isCatchStim(stim) {
  return stim.k === null || stim.r === 100;
}

function buttonHtml(choice) {
  if (choice === "") {
    return '<button class="jspsych-btn grid-spacer" disabled tabindex="-1"></button>';
  }
  return `<button class="jspsych-btn grid-kana">${choice}</button>`;
}

function makeTrial(stim, isPractice = false) {
  const isCatch = isCatchStim(stim);
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `<img class="stim-img" src="stimuli/${stim.id}.png" alt="">`,
    prompt: '<div class="trial-prompt">表示された文字を 50音表から選んでください</div>',
    choices: GRID_FLAT,
    button_html: buttonHtml,
    grid_rows: GRID_ROWS,
    grid_columns: GRID_COLS,
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: stim.id,
      q_set: stim.q_set,
      k_index: stim.k_index,
      k: stim.k,
      r: stim.r,
      n_choices: N_CHOICES,
      is_catch: isCatch,
    },
    on_finish: (data) => {
      data.response_char = GRID_FLAT[data.response];
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
              q_set: data.q_set,
              k_index: data.k_index,
              k: data.k,
              r: data.r,
              n_choices: data.n_choices,
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
      '<p style="padding:40px;color:#900;">刺激データの読み込みに失敗しました: ' + e.message + '</p>';
    return;
  }

  let all;
  try {
    all = sampleStimuli(manifest, N_TRIALS + N_PRACTICE);
  } catch (e) {
    document.body.innerHTML =
      '<p style="padding:40px;color:#900;">' + e.message + '</p>';
    return;
  }
  const practiceStims = all.slice(0, N_PRACTICE);
  const mainStims = all.slice(N_PRACTICE);

  const setLabel = Q_SET === "karuta" ? "競技かるた 48 字" : "全 84 字";

  // ---- Preload -----------------------------------------------------------
  const allImageUrls = all.map(s => `stimuli/${s.id}.png`);
  const preload = {
    type: jsPsychPreload,
    images: allImageUrls,
    message: '画像を読み込んでいます…',
    show_progress_bar: true,
  };

  // ---- Consent -----------------------------------------------------------
  const consent = {
    type: jsPsychInstructions,
    pages: [
      `<h2>インクルーシブ字幕の研究実験</h2>
       <p>本実験は、視覚的な文字の認識可能性を測ることを目的としています。
       所要時間は約 20 分です。ご協力ありがとうございます。</p>
       <p>取得するデータ: 各設問への回答とその所要時間、参加識別子。</p>
       <p>個人を特定する情報は収集しません。途中で中断する場合はブラウザを閉じてください。
       完了画面で表示される完了コードを応募元に貼り付けることで報酬の対象となります。</p>
       <p><b>続けて参加することに同意される場合は「次へ」を押してください。</b></p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "同意して次へ",
  };

  const instructions = {
    type: jsPsychInstructions,
    pages: [
      `<h2>課題</h2>
       <p>画面中央にひらがな1文字が表示されます。
       はっきり見える場合もあれば、ほとんど見えない場合もあります。</p>
       <p>下の <b>50音表</b>(${setLabel})から、表示されたと思う 1 文字を
       <b>素早く</b> クリックしてください。表は毎回同じ並びです。</p>
       <p>確信が持てない場合でも、感覚で答えて構いません。
       考え込まずに次々と答えてください。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。</p>
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
       途中休憩はありませんので、集中できる環境で挑んでください。</p>
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
    preload,
    consent,
    instructions,
    ...practiceBlock,
    mainStart,
    ...mainBlock,
    finish,
  ]);
}

run();
