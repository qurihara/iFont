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
 *   replays, rt_ms, is_catch
 *
 * One shared ANSWER_KEY serves both pools. Visual entries carry
 * {font, mode:"f1", k_index, k, r}; audio (truncation) entries carry
 * {modality:"audio", voice, mode:"f1_audio_trunc", frac_index, frac}.
 * The handler logs whichever level fields are present (k* for visual,
 * frac* for audio) and leaves the other blank.
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

    const stim = answerKey[body.stimulus_id];
    if (!stim) {
      return out({status: "error", reason: "unknown stimulus_id"});
    }
    const correct = body.response_char === stim.answer;
    const modality = stim.modality || "visual";
    // visual entries store the font under "font"; audio entries the voice.
    const fontVoice = stim.font || stim.voice || "";
    // Level fields: visual uses k* (k=null means ∞/catch); audio uses frac*.
    // Log whichever the entry has; leave the other column blank.
    const hasK = (stim.k_index !== undefined);
    const kIdx = hasK ? stim.k_index : "";
    const kVal = !hasK ? "" : (stim.k === null ? "Inf" : stim.k);
    const rVal = hasK ? stim.r : "";
    const hasFrac = (stim.frac_index !== undefined);
    const fracIdx = hasFrac ? stim.frac_index : "";
    const fracVal = hasFrac ? stim.frac : "";

    const sheet = SpreadsheetApp.openById(sheetId);
    let trials = sheet.getSheetByName(SHEET_TRIALS);
    if (!trials) {
      trials = sheet.insertSheet(SHEET_TRIALS);
      trials.appendRow([
        "ts", "participant_id", "worker_id", "completion_code",
        "stimulus_id", "response_char", "correct_char", "correct",
        "modality", "q_set", "k_index", "k", "r", "frac_index", "frac",
        "n_choices", "font_voice", "mode", "replays", "rt_ms", "is_catch",
      ]);
    }
    trials.appendRow([
      new Date(body.ts || Date.now()),
      body.participant_id || "",
      body.worker_id || "",
      body.completion_code || "",
      body.stimulus_id,
      body.response_char,
      stim.answer,
      correct,
      modality,
      stim.q_set,
      kIdx,
      kVal,
      rVal,
      fracIdx,
      fracVal,
      body.n_choices,
      fontVoice,
      stim.mode,
      (body.replays === undefined ? "" : body.replays),
      body.rt_ms,
      !!body.is_catch,
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
