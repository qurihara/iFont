// =========================================================================
// 上毛かるた測定ページの共通部品 (audio_card.js / visual_card.js から使う)
//   - 札セット(cards_jomo.json)の読み込み
//   - 44札の回答ボタン(五十音の格子・固定配置)
//   - 打ち切り時点の設計値、試行の配り方、端末環境の記録
//   - 点検モード(?prod なし)の URL パラメータ
//
// 使い方: prod_common.js のあと、各課題スクリプトより前に読み込む。
//   <script src="../prod_common.js"></script>
//   <script src="jomo_common.js"></script>
// =========================================================================
(function (global) {
  "use strict";
  const P = new URLSearchParams(location.search);

  // 打ち切り時点(第一音の音響的開始からのミリ秒)。1モーラ目(約0.2秒)と2モーラ目にまたがる8点。
  // 札ごとにロジスティック曲線を当てはめるので、1モーラ目の中に6点、2モーラ目に2点を置く。
  const CUTS_MS = [40, 80, 120, 160, 200, 260, 340, 450];
  // 統制試行(catch)の打ち切り。3モーラ目まで聞こえる(見える)ので、まじめに答えればほぼ正解する。
  const CATCH_MS = 1000;
  // 1人あたりの本番試行数。8時点 × 8 = 64 の段階つき試行と、8 の統制試行。
  const N_GRADED = 64;
  const N_CATCH = 8;
  const N_PRACTICE = 3;
  const VERSION = "jomo-2026-10-08";

  // 端末環境(prod_common.js が送信本文に載せる)。
  const ENV = { ua: navigator.userAgent, dpr: window.devicePixelRatio || 1,
    screen: `${window.screen.width}x${window.screen.height}`,
    touch: (navigator.maxTouchPoints || 0) > 0, refreshHz: null };
  (function measureRefresh() {
    let n = 0; const t0 = performance.now();
    function f(now) { n++; if (n < 40) requestAnimationFrame(f); else ENV.refreshHz = Math.round(1000 / ((now - t0) / n)); }
    requestAnimationFrame(f);
  })();
  if (global.PROD) global.PROD.setEnv(ENV);

  // 点検モードのパラメータ(本番 ?prod=1 では無視する)。
  //   ?cut=120        打ち切りを1つに固定する
  //   ?card=あ,か      出題する札を限る
  //   ?n=10           本番の試行数を変える
  //   ?feedback=0     各問のあとの正解表示を止める
  //   ?speed=2        (文字課題) 速さの段階を固定する(0=最も遅い … 4=最も速い)
  const CHECK = {
    enabled: !(global.PROD && global.PROD.enabled),
    cut: P.has("cut") ? Number(P.get("cut")) : null,
    cards: P.has("card") ? P.get("card").split(",").filter(Boolean) : null,
    n: P.has("n") ? Number(P.get("n")) : null,
    feedback: P.get("feedback") !== "0",
    speed: P.has("speed") ? Number(P.get("speed")) : null,
  };

  async function loadCards(url) {
    const res = await fetch(url || "cards_jomo.json", { cache: "no-store" });
    if (!res.ok) throw new Error("cards_jomo.json の読み込みに失敗: " + res.status);
    const set = await res.json();
    set.byId = {};
    for (const c of set.cards) set.byId[c.id] = c;
    set.gridFlat = set.grid.flat();
    set.gridRows = set.grid.length;
    set.gridCols = set.grid[0].length;
    set.nChoices = set.gridFlat.filter(x => x !== "").length;
    return set;
  }

  // 回答ボタン。札のかなを大きく、読みの冒頭(4モーラ)を小さく添える。
  // 読みが札のかなと違う札(ひ=びゃくえ、ふ=ぶんぶく)でも、音から札を引けるようにするため。
  function buttonHtml(set) {
    return (choice) => {
      if (choice === "") return '<button class="jspsych-btn grid-spacer" disabled tabindex="-1"></button>';
      const c = set.byId[choice];
      const head = c ? c.moras.slice(0, 4).join("") : "";
      return `<button class="jspsych-btn grid-card"><span class="k">${choice}</span><span class="r">${head}</span></button>`;
    };
  }
  function answerButtons() {
    const group = document.querySelector("#jspsych-html-button-response-btngroup, .jspsych-html-button-response-btngroup");
    if (!group) return [];
    return Array.from(group.querySelectorAll("button")).filter(b => !b.disabled);
  }

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  }
  // 混ぜた一組を順に配り、尽きたら混ぜ直して配り続ける(どの要素も出現数の差は高々1)。
  function dealEven(items, n) {
    const out = [];
    while (out.length < n) out.push(...shuffle([...items]));
    return out.slice(0, n);
  }

  // 44札の一覧表(教示に載せる)。
  function cardListHtml(set) {
    const rows = set.cards.map(c =>
      `<tr><td class="k">${c.kana}</td><td>${c.text}</td><td class="r">${c.reading}</td></tr>`).join("");
    return `<table class="card-list"><thead><tr><th>札</th><th>読み札</th><th>読み</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function cardLabel(set, id) {
    const c = set.byId[id];
    return c ? `${c.kana}（${c.text}）` : id;
  }

  // 点検モードの結果ダウンロード(JSON)。
  function downloadResults(jsPsych, task, config) {
    const payload = { task, version: VERSION, config, env: ENV,
      trials: jsPsych.data.get().filter({ task: "main" }).values() };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${task}_${Date.now()}.json`;
    a.click();
  }

  global.JOMO = { CUTS_MS, CATCH_MS, N_GRADED, N_CATCH, N_PRACTICE, VERSION, ENV, CHECK,
    loadCards, buttonHtml, answerButtons, shuffle, dealEven, cardListHtml, cardLabel, downloadResults };
})(window);
