// =========================================================================
// 視覚版 Kikiwake 実験 (減算 F1, BIZ UDGothic 単独)
// =========================================================================

// EDIT BEFORE DEPLOY:  set this to the deployed Google Apps Script /exec URL.
// During development, leave as "" to skip submission and just log to console.
const SUBMIT_URL = "";

// Number of main trials per participant (excluding practice).
const N_TRIALS = 200;
const N_PRACTICE = 5;

// =========================================================================
// Setup
// =========================================================================

const params = new URLSearchParams(window.location.search);
const workerId = params.get("worker_id") || params.get("wid") || "";
const participantId = workerId || ("anon-" + Math.random().toString(36).slice(2, 10));

// Random 16-char completion code that participants paste back into the
// crowdsourcing platform; we also record it server-side for verification.
const completionCode = Array.from({length: 16},
  () => "ABCDEFGHJKMNPQRSTUVWXYZ23456789"[Math.floor(Math.random() * 30)]).join("");

const jsPsych = initJsPsych({
  display_element: document.body,
  show_progress_bar: true,
  message_progress_bar: "進捗",
  on_finish: () => {
    // No-op: the completion screen is the last timeline node and handles UI.
  }
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
  // Random subset without replacement.
  const pool = manifest.stimuli.slice();
  return jsPsych.randomization.sampleWithoutReplacement(pool, n);
}

function makeTrial(stim, isPractice = false, isCatch = false) {
  return {
    type: jsPsychImageButtonResponse,
    stimulus: `stimuli/${stim.id}.png`,
    choices: stim.choices,
    prompt: '<div style="font-size:18px; margin: 16px 0;">表示された文字を選んでください</div>',
    button_html: (choice) =>
      `<button class="jspsych-btn choice-btn">${choice}</button>`,
    css_classes: ["stim-img-wrap"],
    stimulus_width: 320,
    stimulus_height: 320,
    maintain_aspect_ratio: true,
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: stim.id,
      choices: stim.choices,
      r: stim.r,
      is_catch: isCatch,
    },
    on_finish: (data) => {
      data.response_char = data.choices[data.response];
      if (!isPractice && SUBMIT_URL) {
        // Fire-and-forget POST; failures don't block UX.
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
      '<p style="padding: 40px; color: #900;">刺激データの読み込みに失敗しました: ' + e.message + '</p>';
    return;
  }

  const all = sampleStimuli(manifest, N_TRIALS + N_PRACTICE);
  const practiceStims = all.slice(0, N_PRACTICE);
  const mainStims = all.slice(N_PRACTICE);

  // Catch trials = stimuli with r = 100 (fully visible target). The
  // analysis flags participants whose accuracy on r=100 stimuli is low.
  const catchIds = new Set(mainStims.filter(s => s.r === 100).map(s => s.id));

  // ---- Preload all assets for this session ------------------------------
  const allImageUrls = all.map(s => `stimuli/${s.id}.png`);
  const preload = {
    type: jsPsychPreload,
    images: allImageUrls,
    message: '画像を読み込んでいます…',
    show_progress_bar: true,
  };

  // ---- Consent + instructions -------------------------------------------
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
       <p>下に並ぶ <b>4 つの候補</b> から、表示されたと思う 1 文字を <b>素早く</b> クリックしてください。</p>
       <p>確信が持てない場合でも、感覚で答えて構いません。
       考え込まずに次々と答えてください。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。
       練習問題の答えは記録されません。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "練習を始める",
  };

  const practiceBlock = practiceStims.map(s => makeTrial(s, true, false));

  const mainStart = {
    type: jsPsychInstructions,
    pages: [
      `<h2>練習終了</h2>
       <p>続いて本番 ${N_TRIALS} 問に入ります。
       途中休憩はありませんので、集中できる環境で挑んでください。</p>
       <p>準備ができたら「本番を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "本番を始める",
  };

  const mainBlock = mainStims.map(s => makeTrial(s, false, catchIds.has(s.id)));

  const finish = {
    type: jsPsychHtmlButtonResponse,
    stimulus: () => `
      <h2>ご協力ありがとうございました</h2>
      <p>下の <b>完了コード</b> を、応募元の入力欄に貼り付けてください。</p>
      <p><span class="completion-code">${completionCode}</span></p>
      <p style="font-size: 12px; color: #666;">
        参加者ID: ${participantId} ／ 所要時間: ${Math.round(jsPsych.getTotalTime() / 1000)} 秒
      </p>`,
    choices: ["閉じる"],
  };

  // ---- Run -------------------------------------------------------------
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
