// =========================================================================
// 測定B: 上毛かるた 文字の現れ方の課題 (44択の札当て・フェード5段階)
//   - 各札の読みをモーラ単位の文字列として表示する。1文字目(読みの1モーラ目)は時刻 0 から
//     フェードで現れ(不透明度 = min(1, t / fade_ms))、2文字目以降は音声の通し読みで
//     そのモーラが読まれた時刻(audio/cards_audio.json の mora_onsets_rel_ms。第一音の音響的開始が原点)に
//     一括で現れる。これを cut_ms で打ち切って消し、どの札かを44択で問う。
//   - フェードの速さは5段階(等比)。fade_ms = 600 × 10^(−k/4)、k = 0..4 → 600, 337, 190, 107, 60 ms。
//     1文字目が濃くなりきるまでの時間で、音声側の傾き β1 ≈ 0.06〜0.6/ms の範囲に対応づける(10倍の幅)。
//   - 打ち切りは JOMO.CUTS_MS の8点(音声課題と同じ)。統制試行は 1000 ms。
//   - 速さは参加者内の要因(5段階 × 8時点 = 40 セルに均等に配る)。?speed=k で1段階に固定できる(点検用)。
//   - 描画は canvas の fillText と globalAlpha(透明度)で行う。ぼかしと違い WebKit でも正しく出る。
//   - クリック開始(自己ペース)。押すと注視点が 300 ms 出て、そのあと提示が始まる。「もう一度みる」で再生し直せる。
//   - 実際の提示時間 actual_ms(最初に描いたフレームから消したフレームまで)と描画フレーム数 actual_frames を記録する。
// =========================================================================
const TASK = "visual_card";
const FADE_MS_LEVELS = [600, 337, 190, 107, 60];   // 600 × 10^(−k/4) を丸めた値
const LEAD_MS = 300;             // 開始ボタンから提示開始までの注視点の時間
const CANVAS_W = 400, CANVAS_H = 120;
const FONT_PX = 36;
const MAX_PER_LINE = 9;          // 1行に入れるモーラ数の上限(18モーラの札は2行)
const FONT_FAMILY = '"BIZ UDGothic Jomo", "BIZ UDGothic", "Hiragino Sans", sans-serif';

const participantId = PROD.participantId;
const completionCode = PROD.completionCode;
const jsPsych = initJsPsych({ display_element: document.body, show_progress_bar: true, message_progress_bar: "進捗" });

let SET = null, AUDIO = null;
let _raf = null, _replays = 0, _tTrial = 0, _tStim = null, _spaceHandler = null, _trialIndex = 0;
let _actual = { ms: null, frames: 0 };

function newCanvas() {
  const c = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  c.id = "stim"; c.width = Math.round(CANVAS_W * dpr); c.height = Math.round(CANVAS_H * dpr);
  c.style.width = CANVAS_W + "px"; c.style.height = CANVAS_H + "px";
  const ctx = c.getContext("2d");
  ctx.scale(dpr, dpr);
  return c;
}
function drawBlank(ctx) { ctx.globalAlpha = 1; ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, CANVAS_W, CANVAS_H); }
function drawFix(ctx) {
  drawBlank(ctx);
  ctx.fillStyle = "#333"; ctx.font = "32px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("+", CANVAS_W / 2, CANVAS_H / 2);
}
// モーラ列の配置(行分け・各モーラの描画位置)。1モーラは等幅 FONT_PX で左から並べる。
function layout(moras) {
  const n = moras.length;
  const lines = n > MAX_PER_LINE ? 2 : 1;
  const perLine = Math.ceil(n / lines);
  const pos = [];
  for (let i = 0; i < n; i++) {
    const li = Math.floor(i / perLine), ci = i % perLine;
    const cnt = Math.min(perLine, n - li * perLine);
    const x0 = (CANVAS_W - cnt * FONT_PX) / 2;
    const y = lines === 1 ? CANVAS_H / 2 : (li === 0 ? CANVAS_H * 0.3 : CANVAS_H * 0.7);
    pos.push({ x: x0 + ci * FONT_PX + FONT_PX / 2, y });
  }
  return pos;
}
// 時刻 t(ms)の1コマを描く。1モーラ目はフェード、2モーラ目以降は読まれた時刻に一括表示。
function drawFrame(ctx, card, fadeMs, onsetsRel, t) {
  drawBlank(ctx);
  ctx.fillStyle = "#000"; ctx.font = `${FONT_PX}px ${FONT_FAMILY}`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  const pos = card._pos || (card._pos = layout(card.moras));
  const a = Math.max(0, Math.min(1, t / fadeMs));
  if (a > 0) { ctx.globalAlpha = a; ctx.fillText(card.moras[0], pos[0].x, pos[0].y); }
  ctx.globalAlpha = 1;
  for (let i = 1; i < card.moras.length; i++) {
    if (t >= onsetsRel[i - 1]) ctx.fillText(card.moras[i], pos[i].x, pos[i].y);
  }
}
function cancelAnim() { if (_raf !== null) { cancelAnimationFrame(_raf); _raf = null; } }
// 1問の提示: 注視点 LEAD_MS → 提示を cut_ms まで → 消去。完了後に onDone(actual) を呼ぶ。
function present(ctx, card, fadeMs, cutMs, onDone) {
  cancelAnim();
  const onsetsRel = AUDIO.items[card.id].mora_onsets_rel_ms;
  drawFix(ctx);
  const tClick = performance.now();
  let tStart = null, tFirst = null, frames = 0;
  function step(now) {
    if (now - tClick < LEAD_MS) { _raf = requestAnimationFrame(step); return; }
    if (tStart === null) tStart = now;
    const t = now - tStart;
    if (t < cutMs) {
      drawFrame(ctx, card, fadeMs, onsetsRel, t);
      if (tFirst === null) tFirst = now;
      frames++;
      _raf = requestAnimationFrame(step);
    } else {
      drawBlank(ctx);
      _raf = null;
      onDone({ ms: tFirst === null ? 0 : Math.round(now - tFirst), frames, t_start: tStart });
    }
  }
  _raf = requestAnimationFrame(step);
}

// 出題の配り方: 速さ5段階 × 打ち切り8水準 = 40セルに均等 + 統制8問(速さは均等)。札は全体で均等。
function buildMainTrials() {
  const ids = JOMO.CHECK.enabled && JOMO.CHECK.cards ? JOMO.CHECK.cards : SET.cards.map(c => c.id);
  let nGraded = JOMO.N_GRADED, nCatch = JOMO.N_CATCH;
  if (JOMO.CHECK.enabled && JOMO.CHECK.n) { nGraded = JOMO.CHECK.n; nCatch = Math.round(JOMO.CHECK.n / 9); }
  const cutPool = (JOMO.CHECK.enabled && JOMO.CHECK.cut !== null) ? [JOMO.CHECK.cut] : JOMO.CUTS_MS;
  const speedPool = (JOMO.CHECK.enabled && JOMO.CHECK.speed !== null) ? [JOMO.CHECK.speed]
                    : FADE_MS_LEVELS.map((_, k) => k);
  const cells = [];
  for (const s of speedPool) for (const c of cutPool) cells.push({ speed_idx: s, cut_ms: c });
  const graded = JOMO.dealEven(cells, nGraded);
  const catchSpeeds = JOMO.dealEven(speedPool, nCatch);
  const cards = JOMO.dealEven(ids, nGraded + nCatch);
  const out = [];
  for (let i = 0; i < nGraded + nCatch; i++) {
    const isCatch = i >= nGraded;
    const speed_idx = isCatch ? catchSpeeds[i - nGraded] : graded[i].speed_idx;
    out.push({ id: cards[i], cut_ms: isCatch ? JOMO.CATCH_MS : graded[i].cut_ms, is_catch: isCatch,
               speed_idx, fade_ms: FADE_MS_LEVELS[speed_idx] });
  }
  return JOMO.shuffle(out);
}
function buildPracticeTrials() {
  const ladder = [JOMO.CATCH_MS, 450, 200];
  const cards = JOMO.dealEven(SET.cards.map(c => c.id), JOMO.N_PRACTICE);
  return cards.map((id, i) => ({ id, cut_ms: ladder[i % ladder.length], is_catch: false, speed_idx: 2, fade_ms: FADE_MS_LEVELS[2] }));
}

function makeTrial(t, isPractice) {
  const card = SET.byId[t.id];
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `
      <div id="stim-wrap"></div>
      <div class="stim-controls">
        <button type="button" id="play-btn" class="replay-btn">▶ 準備ができたら文字をみる（またはスペースキー）</button>
      </div>
      <div class="trial-prompt">ボタンを押すと、枠の中に札の読みの<b>最初の部分だけ</b>が現れて消えます。どの札だと思うか、下の表から選んでください。</div>`,
    choices: SET.gridFlat,
    button_html: JOMO.buttonHtml(SET),
    grid_rows: SET.gridRows, grid_columns: SET.gridCols,
    on_load: () => {
      _replays = 0; _tStim = null; _tTrial = performance.now(); _actual = { ms: null, frames: 0 };
      const wrap = document.getElementById("stim-wrap");
      const canvas = newCanvas(); wrap.appendChild(canvas);
      const ctx = canvas.getContext("2d");
      drawBlank(ctx);
      const btn = document.getElementById("play-btn");
      const answers = JOMO.answerButtons();
      answers.forEach(b => { b.disabled = true; b.style.opacity = ".45"; });
      const play = () => {
        if (_raf !== null) return;                    // 提示中の連打は無視
        const first = (_tStim === null);
        if (!first) _replays += 1;
        present(ctx, card, t.fade_ms, t.cut_ms, (actual) => {
          if (first) {
            _tStim = actual.t_start;                  // 提示が始まった時刻(反応時間の起点)
            _actual = actual;
            answers.forEach(b => { b.disabled = false; b.style.opacity = ""; });
            if (btn) btn.textContent = "▶ もう一度みる";
          }
        });
      };
      if (btn) btn.addEventListener("click", play);
      _spaceHandler = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); play(); } };
      document.addEventListener("keydown", _spaceHandler);
    },
    data: { task: isPractice ? "practice" : "main", stimulus_id: t.id, cut_ms: t.cut_ms, is_catch: t.is_catch,
            speed_idx: t.speed_idx, fade_ms: t.fade_ms },
    on_finish: (data) => {
      if (_spaceHandler) { document.removeEventListener("keydown", _spaceHandler); _spaceHandler = null; }
      cancelAnim();
      data.response_char = SET.gridFlat[data.response];
      data.correct_char = t.id;
      data.correct = data.response_char === t.id;
      data.replays = _replays;
      data.rt_ms = (_tStim === null) ? data.rt : Math.round(data.rt - (_tStim - _tTrial));
      data.actual_ms = _actual.ms; data.actual_frames = _actual.frames;
      if (isPractice) return;
      data.trial_index = _trialIndex++;
      PROD.saveJomoTrial({
        task: TASK, set_id: SET.set_id, version: JOMO.VERSION, trial_index: data.trial_index,
        stimulus_id: t.id, cut_ms: t.cut_ms, is_catch: t.is_catch,
        response_char: data.response_char, correct_char: t.id, correct: data.correct,
        rt_ms: data.rt_ms, replays: data.replays, n_choices: SET.nChoices,
        speed_idx: t.speed_idx, fade_ms: t.fade_ms, actual_ms: data.actual_ms, actual_frames: data.actual_frames,
        first_mora_ms: "",
      });
    },
  };
}

function makeFeedback(isPractice) {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: () => {
      const last = jsPsych.data.get().last(1).values()[0] || {};
      const ans = last.response_char ? JOMO.cardLabel(SET, last.response_char) : "（未選択）";
      const cor = JOMO.cardLabel(SET, last.correct_char);
      const mark = last.correct ? '<span class="feedback-ok">正解</span>' : '<span class="feedback-ng">不正解</span>';
      const note = isPractice
        ? `<p style="font-size:14px;color:#555;line-height:1.8">これは練習です。答えは記録されません。<br>
           <b>難しくて当然の課題</b>です。ほとんど何も見えない問もあります。
           見えなかったと感じても空欄にせず、<b>勘で選んで</b>ください。正誤は報酬に影響しません。</p>`
        : `<p class="muted">点検モードの表示(本番では出ません)。打ち切り ${last.cut_ms} ms・速さ段階 ${last.speed_idx}(${last.fade_ms} ms)${last.is_catch ? "・統制" : ""}、実提示 ${last.actual_ms} ms / ${last.actual_frames} フレーム、反応時間 ${last.rt_ms} ms</p>`;
      return `<div style="padding:16px 8px">
        <p style="font-size:17px">あなたの答え: <b>${ans}</b></p>
        <p style="font-size:17px">正解: <b>${cor}</b> ${mark}</p>${note}</div>`;
    },
    choices: ["次へ"], trial_duration: isPractice ? 6000 : 2500,
    data: { task: isPractice ? "practice_feedback" : "check_feedback" },
  };
}

async function run() {
  try {
    SET = await JOMO.loadCards("cards_jomo.json");
    const res = await fetch("audio/cards_audio.json", { cache: "no-store" });
    if (!res.ok) throw new Error("audio/cards_audio.json " + res.status);
    AUDIO = await res.json();
    // 字形のフォントを先に読み込む(読み込み前に描くと代替フォントで出てしまう)。
    if (document.fonts && document.fonts.load) {
      await document.fonts.load(`${FONT_PX}px "BIZ UDGothic Jomo"`, "あ");
    }
  } catch (e) {
    document.body.innerHTML = '<p style="padding:40px;color:#900;">データの読み込みに失敗しました: ' + e.message + '</p>';
    return;
  }
  const practice = buildPracticeTrials();
  const mainTrials = buildMainTrials();
  const nMain = mainTrials.length;
  const minutes = Math.max(5, Math.round(nMain * 10 / 60));

  if (JOMO.CHECK.enabled) {
    const b = document.createElement("div"); b.className = "check-badge";
    b.textContent = "点検モード(記録は送信しません)"; document.body.appendChild(b);
  }
  if (PROD.enabled) {
    await new Promise((resolve) => {
      const box = document.createElement("div"); box.className = "prod-consent"; document.body.appendChild(box);
      PROD.consentScreen(box, `かるたの文字の見え方の課題（文字・約${minutes}分）`, minutes,
        () => { box.remove(); resolve(); }, false);
    });
  }
  const consent = {
    type: jsPsychInstructions,
    pages: [`<h2>かるたの文字の見え方（研究者の点検用）</h2>
      <p>上毛かるたの44札の読みが文字で現れる途中を見て、どの札かを当てる課題です。所要時間は約${minutes}分です。</p>
      <p>できればPC（パソコン）で、明るい静かな環境でお願いします。</p>
      <p>取得するデータ: 各設問への回答とその所要時間、参加識別子、端末の画面に関する技術情報。個人を特定する情報は収集しません。</p>`],
    show_clickable_nav: true, button_label_next: "同意して次へ",
  };
  const instructions = {
    type: jsPsychInstructions,
    pages: [
      `<h2>課題</h2>
       <p>上毛かるた（群馬県の郷土かるた）の<b>44枚の読み札</b>の読みを、画面の枠の中に文字で出します。
       1文字目は<b>だんだん濃くなりながら</b>現れ、2文字目以降は読み上げの速さに合わせて順に現れます。
       各問では、その<b>最初のごく短い部分だけ</b>を見せてすぐ消します（1文字目が薄いまま消えることがほとんどです）。
       見えた文字から、<b>どの札の読みか</b>を下の表（44札）から選んでください。</p>
       <p>各問は<b>自分のペース</b>で始められます。<b>[準備ができたら文字をみる]</b>（またはスペースキー）を押すと、
       枠に「+」が出て、そのすぐあとに文字が現れます。枠から目を離さないでください。
       押したあとは「もう一度みる」で<b>何度でも</b>見直せます。</p>`,
      `<h2>答え方</h2>
       <p>回答のボタンは、札の<b>先頭のかな</b>を五十音の順に並べたもので、毎回同じ並びです。
       各ボタンには読みの冒頭（4音）を小さく添えてあります。</p>
       <p>読み札はすべて先頭のかなが異なります。ただし
       <b>「ひ」の札の読みは「びゃくえ…」、「ふ」の札の読みは「ぶんぶく…」</b>です。
       「びゃ」が見えたら「ひ」、「ぶ」が見えたら「ふ」を選んでください。</p>
       <p><b>難しくて当然の課題です。</b>ほとんど何も見えない問もあります。
       見えなかったと感じたときも、<b>勘で1つを選んでください</b>。外れた答えも大切なデータです。正誤は報酬に影響しません。</p>`,
      `<h2>44枚の読み札</h2>
       <p style="font-size:13px">参考に、44札の読み札と読みを載せます（覚える必要はありません）。</p>
       ${JOMO.cardListHtml(SET)}`,
      `<h2>練習</h2>
       <p>まず ${JOMO.N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true, button_label_next: "練習を始める",
  };
  const practiceBlock = practice.flatMap(t => [makeTrial(t, true), makeFeedback(true)]);
  const mainStart = {
    type: jsPsychInstructions,
    pages: [`<h2>練習終了</h2>
      <p>続いて本番 ${nMain} 問に入ります。ここからの回答が記録されます。やり方は練習と同じです。分からない問は勘で選んでください。</p>
      <p>準備ができたら「本番を始める」を押してください。</p>`],
    show_clickable_nav: true, button_label_next: "本番を始める",
  };
  const mainBlock = mainTrials.flatMap(t =>
    (JOMO.CHECK.enabled && JOMO.CHECK.feedback) ? [makeTrial(t, false), makeFeedback(false)] : [makeTrial(t, false)]);
  const finish = {
    type: jsPsychHtmlButtonResponse,
    stimulus: () => {
      const sec = Math.round(jsPsych.getTotalTime() / 1000);
      if (PROD.enabled) return PROD.completionHTML(sec);
      const n = jsPsych.data.get().filter({ task: "main" }).count();
      const k = jsPsych.data.get().filter({ task: "main", correct: true }).count();
      return `<h2>ご協力ありがとうございました</h2>
        <p>点検モード: 本番 ${n} 問中 ${k} 問正解（${n ? Math.round(100 * k / n) : 0}%）</p>
        <p><span class="completion-code">${completionCode}</span></p>
        <p style="font-size:12px;color:#666;">参加者ID: ${participantId} ／ 所要時間: ${sec} 秒</p>
        <p><button type="button" id="dl-btn" class="replay-btn">結果JSONをダウンロード</button></p>`;
    },
    choices: ["閉じる"],
    on_load: () => {
      const b = document.getElementById("dl-btn");
      if (b) b.addEventListener("click", () => JOMO.downloadResults(jsPsych, TASK,
        { cuts_ms: JOMO.CUTS_MS, catch_ms: JOMO.CATCH_MS, n_graded: JOMO.N_GRADED, n_catch: JOMO.N_CATCH,
          fade_ms_levels: FADE_MS_LEVELS, lead_ms: LEAD_MS, font_px: FONT_PX }));
    },
  };
  const timeline = [];
  if (!PROD.enabled) timeline.push(consent);
  timeline.push(instructions, ...practiceBlock, mainStart, ...mainBlock, finish);
  jsPsych.run(timeline);
}
run();
