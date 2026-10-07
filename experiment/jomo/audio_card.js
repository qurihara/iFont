// =========================================================================
// 測定A: 上毛かるた 通し読みの聞き取り課題 (44択の札当て)
//   - 44札の読み上げ(VOICEVOX 東北きりたん・B3・第一音0.2秒・本体0.27秒/モーラ・語尾2秒超)を、
//     第一音の音響的開始から cut_ms だけ再生して打ち切り、どの札かを44択で問う。
//   - 打ち切りは JOMO.CUTS_MS の8点(40〜450 ms)。統制試行は 1000 ms。
//   - クリック開始(自己ペース): [音をきく] を押すと「ピッ」のあと 300 ms で音声が始まる。
//     開始時刻が予測できるので、反応時間の起点が定まる。
//   - 時間ゲートは Web Audio でサンプル精度の切り出し(audio1char.js と同方式)。
//     mp3 は復号で先頭に遅れが入るため、刺激は wav を使う。
//   - 回答は44札の先頭かなを五十音の格子に並べたボタン(固定配置)。各ボタンに読みの冒頭を添える。
//   - 記録は prod_common.js 経由で GAS に送る(kind="jomo_trial")。?prod=1 で本番、無指定で点検モード。
// =========================================================================
const TASK = "audio_card";
const FADE_MS = 8;            // 切り出しの端の立ち上がり・立ち下がり
const BEEP_HZ = 880, BEEP_MS = 80, BEEP_LEAD_MS = 300, END_GAP_MS = 500, END_BEEP_GAP_MS = 140;

const participantId = PROD.participantId;
const completionCode = PROD.completionCode;
const jsPsych = initJsPsych({ display_element: document.body, show_progress_bar: true, message_progress_bar: "進捗" });

let SET = null, AUDIO = null;
let ctx = null;
const _buf = {};
let _nodes = [], _replays = 0, _tTrial = 0, _tStim = null, _spaceHandler = null, _trialIndex = 0;

function ensureCtx() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}
async function decodeCard(id) {
  if (_buf[id]) return _buf[id];
  const res = await fetch("audio/" + AUDIO.items[id].file, { cache: "force-cache" });
  if (!res.ok) throw new Error("audio/" + AUDIO.items[id].file + " " + res.status);
  _buf[id] = await ensureCtx().decodeAudioData(await res.arrayBuffer());
  return _buf[id];
}
// 音響的開始から cut_ms だけ切り出す(両端 8 ms のコサイン窓)。
function gatedBuffer(buf, id, cutMs) {
  const sr = buf.sampleRate;
  const start = Math.round(AUDIO.items[id].acoustic_onset_ms / 1000 * sr);
  const len = Math.max(1, Math.round(cutMs / 1000 * sr));
  const src = buf.getChannelData(0);
  const ab = ctx.createBuffer(1, len, sr);
  const out = ab.getChannelData(0);
  for (let i = 0; i < len; i++) out[i] = src[start + i] || 0;
  const fade = Math.min(Math.round(sr * FADE_MS / 1000), len >> 1);
  for (let i = 0; i < fade; i++) {
    const w = 0.5 * (1 - Math.cos(Math.PI * (i + 0.5) / fade));
    out[i] *= w; out[len - 1 - i] *= w;
  }
  return ab;
}
function stopAll() { for (const n of _nodes) { try { n.stop(); } catch (e) {} } _nodes = []; }
function playBeep(when) {
  const osc = ctx.createOscillator(), g = ctx.createGain();
  osc.type = "sine"; osc.frequency.value = BEEP_HZ;
  osc.connect(g); g.connect(ctx.destination);
  g.gain.setValueAtTime(0.0001, when);
  g.gain.exponentialRampToValueAtTime(0.12, when + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, when + BEEP_MS / 1000);
  osc.start(when); osc.stop(when + BEEP_MS / 1000 + 0.02);
  _nodes.push(osc);
}
// 1問の再生: 開始の合図音 → (300 ms 後に)札の音声を cut_ms だけ → 0.5 秒後に終了の合図音2回。
function playGated(buf, id, cutMs) {
  ensureCtx(); stopAll();
  const t0 = ctx.currentTime + 0.02;
  playBeep(t0);
  const stimStart = t0 + BEEP_LEAD_MS / 1000;
  const s = ctx.createBufferSource();
  s.buffer = gatedBuffer(buf, id, cutMs);
  s.connect(ctx.destination); s.start(stimStart); _nodes.push(s);
  const endAt = stimStart + cutMs / 1000 + END_GAP_MS / 1000;
  playBeep(endAt); playBeep(endAt + END_BEEP_GAP_MS / 1000);
}

// 出題の配り方: 打ち切り8水準に均等(各8問)+統制8問。札は全体で均等(72問を44札に配ると各1〜2回)。
function buildMainTrials() {
  const ids = JOMO.CHECK.enabled && JOMO.CHECK.cards ? JOMO.CHECK.cards : SET.cards.map(c => c.id);
  let nGraded = JOMO.N_GRADED, nCatch = JOMO.N_CATCH;
  if (JOMO.CHECK.enabled && JOMO.CHECK.n) { nGraded = JOMO.CHECK.n; nCatch = Math.round(JOMO.CHECK.n / 9); }
  const cutPool = (JOMO.CHECK.enabled && JOMO.CHECK.cut !== null) ? [JOMO.CHECK.cut] : JOMO.CUTS_MS;
  const cuts = JOMO.dealEven(cutPool, nGraded);
  const cards = JOMO.dealEven(ids, nGraded + nCatch);
  const out = [];
  for (let i = 0; i < nGraded + nCatch; i++) {
    const isCatch = i >= nGraded;
    out.push({ id: cards[i], cut_ms: isCatch ? JOMO.CATCH_MS : cuts[i], is_catch: isCatch });
  }
  return JOMO.shuffle(out);
}
function buildPracticeTrials() {
  const ladder = [JOMO.CATCH_MS, 450, 200];
  const cards = JOMO.dealEven(SET.cards.map(c => c.id), JOMO.N_PRACTICE);
  return cards.map((id, i) => ({ id, cut_ms: ladder[i % ladder.length], is_catch: false }));
}

function makeTrial(t, isPractice) {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `
      <div class="stim-controls">
        <button type="button" id="play-btn" class="replay-btn">▶ 準備ができたら音をきく（またはスペースキー）</button>
      </div>
      <div class="trial-prompt">ボタンを押すと、札の読み上げの<b>最初の部分だけ</b>が流れます。どの札だと思うか、下の表から選んでください。</div>`,
    choices: SET.gridFlat,
    button_html: JOMO.buttonHtml(SET),
    grid_rows: SET.gridRows, grid_columns: SET.gridCols,
    on_load: () => {
      _replays = 0; _tStim = null; _tTrial = performance.now();
      const btn = document.getElementById("play-btn");
      const answers = JOMO.answerButtons();
      answers.forEach(b => { b.disabled = true; b.style.opacity = ".45"; });
      decodeCard(t.id).then(buf => {
        const play = () => {
          if (_tStim === null) {
            _tStim = performance.now() + BEEP_LEAD_MS + 20;     // 音声が鳴り始める時刻(反応時間の起点)
            answers.forEach(b => { b.disabled = false; b.style.opacity = ""; });
            if (btn) btn.textContent = "▶ もう一度きく";
          } else { _replays += 1; }
          playGated(buf, t.id, t.cut_ms);
        };
        if (btn) btn.addEventListener("click", play);
        _spaceHandler = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); play(); } };
        document.addEventListener("keydown", _spaceHandler);
      }).catch(err => {
        const p = document.querySelector(".trial-prompt");
        if (p) p.textContent = "音声の読み込みに失敗しました: " + err.message;
        answers.forEach(b => { b.disabled = false; b.style.opacity = ""; });
      });
    },
    data: { task: isPractice ? "practice" : "main", stimulus_id: t.id, cut_ms: t.cut_ms, is_catch: t.is_catch },
    on_finish: (data) => {
      if (_spaceHandler) { document.removeEventListener("keydown", _spaceHandler); _spaceHandler = null; }
      stopAll();
      data.response_char = SET.gridFlat[data.response];
      data.correct_char = t.id;
      data.correct = data.response_char === t.id;
      data.replays = _replays;
      data.rt_ms = (_tStim === null) ? data.rt : Math.round(data.rt - (_tStim - _tTrial));
      data.first_mora_ms = AUDIO.items[t.id].first_mora_ms;
      if (isPractice) return;
      data.trial_index = _trialIndex++;
      PROD.saveJomoTrial({
        task: TASK, set_id: SET.set_id, version: JOMO.VERSION, trial_index: data.trial_index,
        stimulus_id: t.id, cut_ms: t.cut_ms, is_catch: t.is_catch,
        response_char: data.response_char, correct_char: t.id, correct: data.correct,
        rt_ms: data.rt_ms, replays: data.replays, n_choices: SET.nChoices,
        speed_idx: "", fade_ms: "", actual_ms: "", actual_frames: "", first_mora_ms: data.first_mora_ms,
      });
    },
  };
}

// 練習(と点検モードの本番)のフィードバック。正解の札は端末側で分かるので表示する。
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
           <b>難しくて当然の課題</b>です。ほとんど何も聞こえない問もあります。
           聞こえなかったと感じても空欄にせず、<b>勘で選んで</b>ください。正誤は報酬に影響しません。</p>`
        : `<p class="muted">点検モードの表示(本番では出ません)。打ち切り ${last.cut_ms} ms${last.is_catch ? "・統制" : ""}、反応時間 ${last.rt_ms} ms</p>`;
      return `<div style="padding:16px 8px">
        <p style="font-size:17px">あなたの答え: <b>${ans}</b></p>
        <p style="font-size:17px">正解: <b>${cor}</b> ${mark}</p>${note}</div>`;
    },
    choices: ["次へ"], trial_duration: isPractice ? 6000 : 2500,
    data: { task: isPractice ? "practice_feedback" : "check_feedback" },
  };
}

// 44ファイルを先に読み込んで復号しておく(本番中の待ちをなくす)。
async function preloadAll(el) {
  const ids = SET.cards.map(c => c.id);
  el.innerHTML = `<div class="loading"><p>音声データを読み込んでいます（${ids.length} 札）…</p><div class="bar"><div id="pbar"></div></div><p class="muted" id="pmsg"></p></div>`;
  let done = 0;
  const bar = document.getElementById("pbar"), msg = document.getElementById("pmsg");
  for (const id of ids) {
    try { await decodeCard(id); } catch (e) { msg.textContent = "読み込みに失敗: " + e.message; throw e; }
    done++; bar.style.width = Math.round(100 * done / ids.length) + "%";
  }
}

async function run() {
  try {
    SET = await JOMO.loadCards("cards_jomo.json");
    const res = await fetch("audio/cards_audio.json", { cache: "no-store" });
    if (!res.ok) throw new Error("audio/cards_audio.json " + res.status);
    AUDIO = await res.json();
  } catch (e) {
    document.body.innerHTML = '<p style="padding:40px;color:#900;">データの読み込みに失敗しました: ' + e.message + '</p>';
    return;
  }
  const practice = buildPracticeTrials();
  const mainTrials = buildMainTrials();
  const nMain = mainTrials.length;
  const minutes = Math.max(5, Math.round(nMain * 12 / 60));

  if (JOMO.CHECK.enabled) {
    const b = document.createElement("div"); b.className = "check-badge";
    b.textContent = "点検モード(記録は送信しません)"; document.body.appendChild(b);
  }
  if (PROD.enabled) {
    await new Promise((resolve) => {
      const box = document.createElement("div"); box.className = "prod-consent"; document.body.appendChild(box);
      PROD.consentScreen(box, `かるたの読み上げの聞き取りの課題（音声・約${minutes}分）`, minutes,
        () => { box.remove(); resolve(); }, true);
    });
  }
  // 音声の復号は、ユーザー操作(同意ボタン)のあとに AudioContext を作れるようにここで行う。
  const holder = document.createElement("div"); document.body.appendChild(holder);
  try { await preloadAll(holder); } catch (e) { return; }
  holder.remove();

  const consent = {
    type: jsPsychInstructions,
    pages: [`<h2>かるたの読み上げの聞き取り（研究者の点検用）</h2>
      <p>上毛かるたの44札の読み上げを途中まで聞いて、どの札かを当てる課題です。所要時間は約${minutes}分です。</p>
      <p><b>音声を使用します。ヘッドホン・イヤホンをご用意のうえ、音量を適切に調整してください。</b></p>
      <p>取得するデータ: 各設問への回答とその所要時間、参加識別子。個人を特定する情報は収集しません。</p>`],
    show_clickable_nav: true, button_label_next: "同意して次へ",
  };
  const instructions = {
    type: jsPsychInstructions,
    pages: [
      `<h2>課題</h2>
       <p>上毛かるた（群馬県の郷土かるた）の<b>44枚の読み札</b>を、合成音声で読み上げます。
       各問では、読み上げの<b>最初のごく短い部分だけ</b>が流れます（1文字分にも満たないことがほとんどです）。
       聞こえた音から、<b>どの札の読み上げか</b>を下の表（44札）から選んでください。</p>
       <p>各問は<b>自分のペース</b>で始められます。<b>[準備ができたら音をきく]</b>（またはスペースキー）を押すと、
       「ピッ」という合図音のあと、すぐに読み上げが始まります。読み上げが終わってしばらくすると「ピッピッ」と2回鳴り、その問が終わります。
       押したあとは「もう一度きく」で<b>何度でも</b>聞き直せます。</p>`,
      `<h2>答え方</h2>
       <p>回答のボタンは、札の<b>先頭のかな</b>を五十音の順に並べたもので、毎回同じ並びです。
       各ボタンには読み上げの冒頭（4音）を小さく添えてあります。</p>
       <p>読み札はすべて先頭のかなが異なります。ただし
       <b>「ひ」の札は「びゃくえ…」、「ふ」の札は「ぶんぶく…」と濁って読まれます</b>。
       「びゃ」と聞こえたら「ひ」、「ぶ」と聞こえたら「ふ」を選んでください。</p>
       <p><b>難しくて当然の課題です。</b>ほとんど何も聞こえない問もあります。
       聞こえなかったと感じたときも、<b>勘で1つを選んでください</b>。外れた答えも大切なデータです。正誤は報酬に影響しません。</p>`,
      `<h2>44枚の読み札</h2>
       <p style="font-size:13px">参考に、44札の読み札と読みを載せます（覚える必要はありません）。</p>
       ${JOMO.cardListHtml(SET)}`,
      `<h2>練習</h2>
       <p>まず ${JOMO.N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。ここで音量を調整してください。</p>
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
        { cuts_ms: JOMO.CUTS_MS, catch_ms: JOMO.CATCH_MS, n_graded: JOMO.N_GRADED, n_catch: JOMO.N_CATCH, audio_params: AUDIO.params }));
    },
  };
  const timeline = [];
  if (!PROD.enabled) timeline.push(consent);
  timeline.push(instructions, ...practiceBlock, mainStart, ...mainBlock, finish);
  jsPsych.run(timeline);
}
run();
