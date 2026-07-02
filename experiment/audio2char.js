// =========================================================================
// 聴覚版 2文字課題 (C1→C2, C2 を時間ゲート)  ※2026-07-02 設計改訂版
//   - 統一モデル: 先行する1文字目(C1)を全提示し、ターゲットの2文字目(C2)を
//     frac%(0〜100) まで再生して何の文字かを問う。
//   - 語彙は競技かるたに限定しない。C1・C2 とも全72字(音声で区別可能なかな)から
//     ランダム。プールは 72×72 の総当たり。
//   - 音高は競技かるたの読みの規定で固定: C1=B3(246.94Hz), C2=E4(329.63Hz)。
//     提示速度も規定で固定: 1文字 0.2 秒。
//   - 刺激は VOICEVOX 合成の全長音声(C1+C2)。2文字目の時間ゲートは
//     Web Audio で再生時に行う(pilot_audio と同じライブ切り出し)。
//   - 回答は固定50音グリッド(全 72 字)。catch = frac=100(C2 全提示)。
//   - manifest = experiment/audio2char_manifest.json (回答は含まない)。
// =========================================================================

// EDIT BEFORE DEPLOY: deployed Google Apps Script /exec URL.
const SUBMIT_URL = "";

const N_TRIALS = 200;
const N_PRACTICE = 5;

// 2文字目を切り出す割合のグリッド(0〜100 を 5 刻み = 21 段階)。ifont_common.FRAC_GRID と一致。
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);

const FADE_MS = 8;   // ゲート切断点の短いフェード(クリック防止)

// =========================================================================
// 全 72 字の固定50音グリッド (audio.js の GRID_AUDIO と一致)
// =========================================================================
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
const GRID_FLAT = GRID_AUDIO.flat();
const GRID_COLS = 5;
const GRID_ROWS = GRID_AUDIO.length;
const N_CHOICES = GRID_FLAT.filter(c => c !== "").length;   // 72, γ = 1/72

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

// Web Audio: 全長音声をデコードしてキャッシュし、再生時に [0, gate] を切り出す。
let ctx = null;
const _bufCache = {};   // id -> AudioBuffer
let _replays = 0;
let _curSrc = null;

function ensureCtx() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

async function decodeStim(stim) {
  if (_bufCache[stim.id]) return _bufCache[stim.id];
  const res = await fetch(`audio2char_stimuli/${stim.id}.mp3`, {cache: "force-cache"});
  if (!res.ok) throw new Error(`audio2char_stimuli/${stim.id}.mp3 ${res.status}`);
  const buf = await ensureCtx().decodeAudioData(await res.arrayBuffer());
  _bufCache[stim.id] = buf;
  return buf;
}

// C1 を全提示し、C2 を frac% まで残す = ファイル先頭から gate 秒までを再生。
function gatedBuffer(buf, c2_onset, c2_dur, frac) {
  const sr = buf.sampleRate;
  const gate = c2_onset + (frac / 100) * c2_dur;
  const src = buf.getChannelData(0);
  const len = Math.max(1, Math.min(src.length, Math.round(gate * sr)));
  const ab = ctx.createBuffer(1, len, sr);
  const out = ab.getChannelData(0);
  for (let i = 0; i < len; i++) out[i] = src[i] || 0;
  const fade = Math.min(Math.round(sr * FADE_MS / 1000), len);
  for (let i = 0; i < fade; i++) out[len - fade + i] *= (1 - i / fade);
  return ab;
}

function playGated(buf, stim) {
  ensureCtx();
  if (_curSrc) { try { _curSrc.stop(); } catch (e) {} }
  const s = ctx.createBufferSource();
  s.buffer = gatedBuffer(buf, stim.c2_onset_s, stim.c2_dur_s, stim.frac);
  s.connect(ctx.destination);
  s.start();
  _curSrc = s;
}

// =========================================================================
// Manifest
// =========================================================================
async function loadManifest() {
  const res = await fetch("audio2char_manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("audio2char_manifest.json fetch failed: " + res.status);
  return await res.json();
}

// 各刺激(対×条件)に frac を割り当てる。catch=frac=100 をおよそ 5% 入れ、
// 残りは FRAC_GRID から一様抽出する。
function assignFrac(isCatch) {
  if (isCatch) return 100;
  return FRAC_GRID[Math.floor(Math.random() * FRAC_GRID.length)];
}

function sampleTrials(manifest, n) {
  const pool = manifest.stimuli || [];
  if (pool.length === 0) throw new Error("audio2char_manifest に刺激がありません");
  const picked = jsPsych.randomization.sampleWithoutReplacement(pool, Math.min(n, pool.length));
  return picked.map((s, i) => {
    const isCatch = Math.random() < 0.05;
    return Object.assign({}, s, {frac: assignFrac(isCatch), is_catch: isCatch || false});
  });
}

// =========================================================================
// Trial
// =========================================================================
function buttonHtml(choice) {
  if (choice === "") {
    return '<button class="jspsych-btn grid-spacer" disabled tabindex="-1"></button>';
  }
  return `<button class="jspsych-btn grid-kana">${choice}</button>`;
}

function makeTrial(stim, isPractice = false) {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `
      <div class="audio-controls">
        <button type="button" id="replay-btn" class="replay-btn">▶ 音をきく / もう一度</button>
      </div>
      <div class="trial-prompt">2文字つづけて読み上げます。<b>2文字目</b>が何か、50音表から選んでください</div>`,
    choices: GRID_FLAT,
    button_html: buttonHtml,
    grid_rows: GRID_ROWS,
    grid_columns: GRID_COLS,
    on_load: () => {
      _replays = 0;
      const btn = document.getElementById("replay-btn");
      decodeStim(stim).then(buf => {
        playGated(buf, stim);          // 初回は同意クリック後なので自動再生できる
        if (btn) btn.addEventListener("click", () => {
          _replays += 1;
          playGated(buf, stim);
        });
      }).catch(err => {
        const p = document.querySelector(".trial-prompt");
        if (p) p.textContent = "音声の読み込みに失敗しました: " + err.message;
      });
    },
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: stim.id,
      modality: "audio2char",
      q_set: "all",
      pitch_scheme: "B3-E4",
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
              pitch_scheme: data.pitch_scheme,
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
    all = sampleTrials(manifest, N_TRIALS + N_PRACTICE);
  } catch (e) {
    document.body.innerHTML = '<p style="padding:40px;color:#900;">' + e.message + '</p>';
    return;
  }
  const practiceStims = all.slice(0, N_PRACTICE);
  const mainStims = all.slice(N_PRACTICE);

  const consent = {
    type: jsPsychInstructions,
    pages: [
      `<h2>インクルーシブ字幕の研究実験（音声・2文字版）</h2>
       <p>本実験は、競技かるたの読み上げに似た音声で、文字の聞き取りやすさを測ることを目的としています。
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
       <p>各問で、ひらがなを <b>2文字つづけて</b> 読み上げます。
       1文字目は最後まで聞こえますが、<b>2文字目は途中までしか流れない</b>ことがあります
       (ごく短いこともあれば、最後まで聞こえることもあります)。</p>
       <p>「▶ 音をきく / もう一度」ボタンで <b>何度でも</b> 聞き直せます。
       下の <b>50音表</b>(濁音・半濁音を含む 72 字)から、<b>2文字目</b>だと思う 1 文字を選んでください。
       表は毎回同じ並びです。</p>
       <p>2文字のつながりに意味はありません。ことばとして自然かどうかは気にせず、
       聞こえた音だけで答えてください。</p>
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
