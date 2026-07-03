/**
 * Google Apps Script backend for the iFont visual-Kikiwake experiment.
 *
 * Setup (one-time):
 *   1. Create a Google Sheet. Note its ID (from the URL).
 *   2. Tools → Script editor → paste this file.
 *   3. Project Settings → Script Properties:
 *        SPREADSHEET_ID = <your sheet id>
 *        ANSWER_KEY     = (paste the entire contents of answer_key.json)
 *   4. Deploy → New deployment → Web app:
 *        Execute as: Me
 *        Who has access: Anyone
 *      → copy the /exec URL into experiment.js → SUBMIT_URL.
 *   5. The first request you make will trigger an authorization prompt.
 *
 * Schema appended to the "trials" sheet:
 *   ts, participant_id, worker_id, completion_code, stimulus_id,
 *   response_char, correct_char, correct, modality, q_set,
 *   k_index, k, r, frac_index, frac, n_choices, font_voice, mode,
 *   replays, rt_ms, is_catch, c1, algo, pitch_scheme, bigram_freq
 *
 * One shared ANSWER_KEY serves the pre-rendered pools. Visual entries carry
 * {font, mode:"f1", k_index, k, r}; audio (truncation) entries carry
 * {modality:"audio", voice, mode:"f1_audio_trunc", frac_index, frac}.
 * The handler logs whichever level fields are present (k* for visual,
 * frac* for audio) and leaves the other blank.
 *
 * 2文字課題 / 1文字課題 (2026-07-02 設計改訂):
 *   - audio2char: answer_key_2char.json のエントリは "audio2char|<id>" を鍵に
 *     {c1, c2, target, f0_c1_hz, f0_c2_hz, corrected, bigram_freq} を持つ。
 *     正解は entry.target。client は pitch_scheme ("B3-E4") と frac を送る。
 *   - audio1char: answer_key_1char.json のエントリは "audio1char|<id>" を鍵に
 *     {char, target, f0_hz, corrected} を持つ。正解は entry.target。
 *     client は pitch_scheme ("B3") と frac を送る。C1=∅ (発話先頭) の特殊ケース。
 *   - visual2char / visual1char: 刺激はブラウザ側で合成するため answer_key が無い。
 *     client が target_char (正解) を申告し、サーバはそれで採点・記録する。
 *     申告ベースであることは全課題共通のチート耐性方針 (catch 試行 + RT フィルタ)
 *     の範囲内。algo (提示アルゴリズム) と font も記録する。
 *   複数の answer_key ファイル (answer_key.json / _2char / _1char) は、本番デプロイ時に
 *   マージして GAS の ANSWER_KEY プロパティに貼る (鍵の接頭辞で衝突しない)。
 *
 * Notes:
 *   - Client posts with mode: "no-cors", so the response body is not read
 *     by the client; we still return text/plain for diagnostic via curl.
 *   - One row per trial. Aggregate (catch accuracy, exclusions) in the sheet
 *     or downstream analysis.
 *   - ANSWER_KEY is held as a Script Property and parsed on each request.
 *     ~100KB JSON parses in <50ms; cache via CacheService if traffic grows.
 */

const SHEET_TRIALS = "trials";

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    const props = PropertiesService.getScriptProperties();
    const sheetId = props.getProperty("SPREADSHEET_ID");
    if (!sheetId) throw new Error("SPREADSHEET_ID property not set");

    const answerKeyJson = props.getProperty("ANSWER_KEY");
    if (!answerKeyJson) throw new Error("ANSWER_KEY property not set");
    const answerKey = JSON.parse(answerKeyJson);

    // 素の id → 見つからなければ modality 接頭辞つきの鍵 (2文字課題の answer_key)。
    let stim = answerKey[body.stimulus_id];
    if (!stim && body.modality) {
      stim = answerKey[body.modality + "|" + body.stimulus_id];
    }
    let correctChar;
    if (stim) {
      // 事前レンダリング系: 正解は answer_key 側。旧形式は answer、2文字課題は target。
      correctChar = (stim.answer !== undefined) ? stim.answer : stim.target;
    } else if (body.modality === "visual2char" || body.modality === "visual1char") {
      // ブラウザ側合成のため answer_key が無い。client 申告の正解で採点する。
      if (!body.target_char) {
        return out({status: "error", reason: body.modality + " requires target_char"});
      }
      stim = {};
      correctChar = body.target_char;
    } else {
      return out({status: "error", reason: "unknown stimulus_id"});
    }
    const correct = body.response_char === correctChar;
    const modality = body.modality || stim.modality || "visual";
    // visual entries store the font under "font"; audio entries the voice.
    // visual2char は client が font を送る。
    const fontVoice = stim.font || stim.voice || body.font || "";
    // Level fields: visual uses k* (k=null means ∞/catch); audio uses frac*.
    // Log whichever the entry has; leave the other column blank.
    // 2文字課題の frac は client が試行ごとに決めるため body 側から取る。
    const hasK = (stim.k_index !== undefined);
    const kIdx = hasK ? stim.k_index : "";
    const kVal = !hasK ? "" : (stim.k === null ? "Inf" : stim.k);
    const rVal = hasK ? stim.r : "";
    const hasFrac = (stim.frac_index !== undefined) || (body.frac !== undefined);
    const fracIdx = (stim.frac_index !== undefined) ? stim.frac_index : "";
    const fracVal = (stim.frac !== undefined) ? stim.frac
                  : (body.frac !== undefined ? body.frac : "");
    // 2文字課題の追加列。c1 は answer_key (audio2char) か client 申告 (visual2char)。
    const c1Char = stim.c1 || body.c1 || "";
    const algo = body.algo || "";
    const pitchScheme = body.pitch_scheme || "";
    const bigramFreq = (stim.bigram_freq !== undefined) ? stim.bigram_freq : "";

    const sheet = SpreadsheetApp.openById(sheetId);
    let trials = sheet.getSheetByName(SHEET_TRIALS);
    if (!trials) {
      trials = sheet.insertSheet(SHEET_TRIALS);
      trials.appendRow([
        "ts", "participant_id", "worker_id", "completion_code",
        "stimulus_id", "response_char", "correct_char", "correct",
        "modality", "q_set", "k_index", "k", "r", "frac_index", "frac",
        "n_choices", "font_voice", "mode", "replays", "rt_ms", "is_catch",
        "c1", "algo", "pitch_scheme", "bigram_freq",
      ]);
    }
    trials.appendRow([
      new Date(body.ts || Date.now()),
      body.participant_id || "",
      body.worker_id || "",
      body.completion_code || "",
      body.stimulus_id,
      body.response_char,
      correctChar,
      correct,
      modality,
      (stim.q_set !== undefined ? stim.q_set : (body.q_set || "")),
      kIdx,
      kVal,
      rVal,
      fracIdx,
      fracVal,
      body.n_choices,
      fontVoice,
      stim.mode || "",
      (body.replays === undefined ? "" : body.replays),
      body.rt_ms,
      !!body.is_catch,
      c1Char,
      algo,
      pitchScheme,
      bigramFreq,
    ]);

    return out({status: "ok", correct: correct});
  } catch (err) {
    return out({status: "error", reason: String(err)});
  }
}

function doGet(e) {
  // Health check.
  return out({status: "ok", message: "iFont experiment endpoint"});
}

function out(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
