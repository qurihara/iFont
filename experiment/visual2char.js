// =========================================================================
// 視覚版 2文字課題 本実験 (2026-07-02 設計改訂版)
//   - 固定領域に C1→C2 を各 0.2 秒で提示。前の文字は一瞬で消去。
//     C2 は frac% 時点で消去 (聴覚 truncation の視覚版)。2文字目を当てる。
//   - 提示アルゴリズムは ALGO_LIST から試行ごとにランダム
//     (パイロット pilot_visual2char.html で比較して絞り込んだら書き換える)。
//   - 文字は VISUAL 78字。C1 も C2 も一様ランダム (競技かるた語彙に限定しない)。
//   - 刺激は base/<char>.png からブラウザ側で合成 (事前レンダリング不要)。
//     このため正解はクライアント側にあり、GAS へは target_char を申告して採点する
//     (音声2文字も全長音声がファイルに入るため、チート耐性は同水準。
//      catch 試行と反応時間フィルタで担保する方針は他課題と同じ)。
// =========================================================================

// EDIT BEFORE DEPLOY: deployed Google Apps Script /exec URL.
const SUBMIT_URL = "";

// 本実験に載せる提示アルゴリズム。パイロットで絞り込んだらここを書き換える。
const ALGO_LIST = ["fade", "stroke", "zoom", "blur", "moya", "slideB", "slideR"];

const N_TRIALS = 200;
const N_PRACTICE = 5;
const CATCH_RATE = 0.05;          // frac=100 (C2 を最後まで見せる) の統制試行
const CHAR_MS = 200;              // 1文字の提示時間 (競技かるたの規定 0.2 秒)
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);
const FONT_TAG = "bizudgothic";   // base/ 画像のフォント
const SIZE = 256;
const STROKE_THRESH = 128;
const BLUR_MAX_PX = 12;

// =========================================================================
// VISUAL 78字と固定50音グリッド (pilot_visual2char.js と一致)
// =========================================================================
const CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."がぎぐげござじずぜぞだぢづでどばびぶべぼ",
  ..."ぱぴぷぺぽ",
  ..."っゃゅょ",
  ..."ゐゑ",
  ..."ゔ",
];
const GRID_78 = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
  ["ゃ","","ゅ","","ょ"],["っ","","","",""],
  ["ゐ","","","","ゑ"],
  ["ゔ","","","",""],
];
const GRID_FLAT = GRID_78.flat();
const GRID_COLS = 5;
const GRID_ROWS = GRID_78.length;
const N_CHOICES = CHARS.length;   // 78, γ = 1/78

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

let _replays = 0;
let rafId = null;

// =========================================================================
// 描画: 画像読込 + 提示アルゴリズム (pilot_visual2char.js と同じ方式)
// =========================================================================
let imgs = {};
let strokeIdx = {};
let overlayCanvas = null;

function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function loadImage(ch) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error(`base/${ch}.png の読み込みに失敗`));
    im.src = `base/${encodeURIComponent(ch)}.png`;
  });
}

async function loadAllImages() {
  const off = document.createElement("canvas");
  off.width = off.height = SIZE;
  const octx = off.getContext("2d", { willReadFrequently: true });
  const meanInk = new Float32Array(SIZE * SIZE);
  for (const ch of CHARS) {
    const im = await loadImage(ch);
    imgs[ch] = im;
    octx.fillStyle = "#fff";
    octx.fillRect(0, 0, SIZE, SIZE);
    octx.drawImage(im, 0, 0, SIZE, SIZE);
    const d = octx.getImageData(0, 0, SIZE, SIZE).data;
    const idx = [];
    for (let i = 0; i < SIZE * SIZE; i++) {
      const lum = (d[i * 4] + d[i * 4 + 1] + d[i * 4 + 2]) / 3;
      if (lum <= STROKE_THRESH) idx.push(i);
      meanInk[i] += 255 - lum;
    }
    const rnd = mulberry32(ch.codePointAt(0) * 2654435761 % 4294967296);
    for (let i = idx.length - 1; i > 0; i--) {
      const j = Math.floor(rnd() * (i + 1));
      [idx[i], idx[j]] = [idx[j], idx[i]];
    }
    strokeIdx[ch] = Uint32Array.from(idx);
  }
  overlayCanvas = document.createElement("canvas");
  overlayCanvas.width = overlayCanvas.height = SIZE;
  const oc = overlayCanvas.getContext("2d");
  const od = oc.createImageData(SIZE, SIZE);
  for (let i = 0; i < SIZE * SIZE; i++) {
    const lum = Math.max(0, Math.min(255, 255 - meanInk[i] / CHARS.length));
    od.data[i * 4] = od.data[i * 4 + 1] = od.data[i * 4 + 2] = lum;
    od.data[i * 4 + 3] = 255;
  }
  oc.putImageData(od, 0, 0);
}

function clearStage(ctx) {
  ctx.filter = "none";
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, SIZE, SIZE);
}

const ALGOS = {
  fade(ctx, ch, u) {
    clearStage(ctx);
    ctx.globalAlpha = u;
    ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    ctx.globalAlpha = 1;
  },
  stroke(ctx, ch, u) {
    clearStage(ctx);
    const idx = strokeIdx[ch];
    const k = Math.floor(idx.length * u);
    const img = ctx.getImageData(0, 0, SIZE, SIZE);
    const d = img.data;
    for (let i = 0; i < k; i++) {
      const p = idx[i] * 4;
      d[p] = d[p + 1] = d[p + 2] = 0;
    }
    ctx.putImageData(img, 0, 0);
  },
  zoom(ctx, ch, u) {
    clearStage(ctx);
    if (u <= 0) return;
    const s = SIZE * u;
    ctx.drawImage(imgs[ch], (SIZE - s) / 2, (SIZE - s) / 2, s, s);
  },
  blur(ctx, ch, u) {
    clearStage(ctx);
    ctx.filter = `blur(${(1 - u) * BLUR_MAX_PX}px)`;
    ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    ctx.filter = "none";
  },
  moya(ctx, ch, u) {
    clearStage(ctx);
    ctx.globalAlpha = 1 - u;
    ctx.drawImage(overlayCanvas, 0, 0);
    ctx.globalAlpha = u;
    ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    ctx.globalAlpha = 1;
  },
  slideB(ctx, ch, u) {
    clearStage(ctx);
    ctx.drawImage(imgs[ch], 0, (1 - u) * SIZE, SIZE, SIZE);
  },
  slideR(ctx, ch, u) {
    clearStage(ctx);
    ctx.drawImage(imgs[ch], (1 - u) * SIZE, 0, SIZE, SIZE);
  },
};

// C1 を 0→0.2s で提示し 0.2s で一瞬で消去、C2 は frac% 時点で消去。経過時間ベース。
function playSeq(ctx, c1, c2, frac, algoName) {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  const render = ALGOS[algoName];
  const c2End = CHAR_MS + CHAR_MS * frac / 100;
  const t0 = performance.now();
  function frame(now) {
    const el = now - t0;
    if (el < CHAR_MS) {
      render(ctx, c1, el / CHAR_MS);
    } else if (el < c2End) {
      render(ctx, c2, (el - CHAR_MS) / CHAR_MS);
    } else {
      clearStage(ctx);
      rafId = null;
      return;
    }
    rafId = requestAnimationFrame(frame);
  }
  clearStage(ctx);
  rafId = requestAnimationFrame(frame);
}

// =========================================================================
// 試行の生成 (クライアント側で C1/C2/frac/アルゴリズムを無作為に組む)
// =========================================================================
function makeTrialSpec() {
  const c1 = CHARS[Math.floor(Math.random() * CHARS.length)];
  const c2 = CHARS[Math.floor(Math.random() * CHARS.length)];
  const isCatch = Math.random() < CATCH_RATE;
  const frac = isCatch ? 100 : FRAC_GRID[Math.floor(Math.random() * FRAC_GRID.length)];
  const algo = ALGO_LIST[Math.floor(Math.random() * ALGO_LIST.length)];
  return { c1, c2, frac, algo, is_catch: isCatch,
           id: `v2c-${c1}${c2}-${algo}-f${String(frac).padStart(3, "0")}` };
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

function makeTrial(spec, isPractice = false) {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `
      <div class="stim-wrap">
        <canvas id="stim-canvas" width="${SIZE}" height="${SIZE}"></canvas>
        <button type="button" id="replay-btn" class="replay-btn">▶ もう一度みる</button>
      </div>
      <div class="trial-prompt">2文字つづけて表示されます。<b>2文字目</b>が何か、50音表から選んでください</div>`,
    choices: GRID_FLAT,
    button_html: buttonHtml,
    grid_rows: GRID_ROWS,
    grid_columns: GRID_COLS,
    on_load: () => {
      _replays = 0;
      const canvas = document.getElementById("stim-canvas");
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      clearStage(ctx);
      playSeq(ctx, spec.c1, spec.c2, spec.frac, spec.algo);
      const btn = document.getElementById("replay-btn");
      if (btn) btn.addEventListener("click", () => {
        _replays += 1;
        playSeq(ctx, spec.c1, spec.c2, spec.frac, spec.algo);
      });
    },
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: spec.id,
      modality: "visual2char",
      q_set: "all",
      font: FONT_TAG,
      c1: spec.c1,
      target_char: spec.c2,
      algo: spec.algo,
      frac: spec.frac,
      n_choices: N_CHOICES,
      is_catch: spec.is_catch,
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
              target_char: data.target_char,
              c1: data.c1,
              modality: data.modality,
              q_set: data.q_set,
              font: data.font,
              algo: data.algo,
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
  const loading = document.createElement("p");
  loading.style.cssText = "padding:40px;color:#4a76d6;";
  loading.textContent = "文字画像を読み込み中…";
  document.body.appendChild(loading);
  try {
    await loadAllImages();
  } catch (e) {
    loading.textContent = "画像の読み込みに失敗しました: " + e.message;
    loading.style.color = "#900";
    return;
  }
  loading.remove();

  const specs = Array.from({length: N_TRIALS + N_PRACTICE}, () => makeTrialSpec());
  const practiceSpecs = specs.slice(0, N_PRACTICE);
  const mainSpecs = specs.slice(N_PRACTICE);

  const consent = {
    type: jsPsychInstructions,
    pages: [
      `<h2>インクルーシブ字幕の研究実験（視覚・2文字版）</h2>
       <p>本実験は、画面にすばやく表示される文字の読み取りやすさを測ることを目的としています。
       所要時間は約 20 分です。ご協力ありがとうございます。</p>
       <p><b>文字が短い時間 (1文字 0.2 秒) で次々に表示されます。</b>
       画面がよく見える明るさ・距離でご参加ください。</p>
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
       <p>各問で、ひらがなが <b>2文字つづけて同じ場所に</b> 表示されます。
       1文字ずつ 0.2 秒の速さで、字は「だんだん現れる」ように表示されます
       (現れかたは問題ごとにさまざまです)。</p>
       <p>1文字目は最後まで表示されますが、<b>2文字目は途中で消える</b>ことがあります
       (ごく一瞬のこともあれば、最後まで見えることもあります)。</p>
       <p>「▶ もう一度みる」ボタンで <b>何度でも</b> 見直せます。
       下の <b>50音表</b>(濁音・半濁音などを含む 78 字)から、<b>2文字目</b>だと思う 1 文字を
       選んでください。表は毎回同じ並びです。</p>
       <p>2文字のつながりに意味はありません。ことばとして自然かどうかは気にせず、
       見えたものだけで答えてください。</p>
       <p>確信が持てなくても、感覚で答えて構いません。考え込まずに次々と答えてください。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "練習を始める",
  };

  const practiceBlock = practiceSpecs.map(s => makeTrial(s, true));

  const mainStart = {
    type: jsPsychInstructions,
    pages: [
      `<h2>練習終了</h2>
       <p>続いて本番 ${mainSpecs.length} 問に入ります。
       静かで集中できる環境で挑んでください。</p>
       <p>準備ができたら「本番を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "本番を始める",
  };

  const mainBlock = mainSpecs.map(s => makeTrial(s, false));

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
