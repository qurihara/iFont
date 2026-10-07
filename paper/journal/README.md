# timeFont 論文誌原稿（未来日記方式）

情報処理学会論文誌に投稿する原稿「認識率の曲線に合わせて文字が現れる動的フォント timeFont による聞く人と見る人の公平なかるた対戦：上毛かるたへの適用と評価」を，未来日記方式（理想的な結果が得られたと仮定して先に書き，実測で後追いする方式）で書いたものである．著者は栗原一貴（筆頭）と丸山礼華．作成日 2026-10-08．

## 重要な注意

**この原稿の 6 章・7 章・8 章の数値は，まだ実測していない想定の値である．** 本文では `\begin{fd}...\end{fd}`（段落）と `\fdcaption`（図表）の印で区別してあり，下書き版の PDF では青い文字と赤い札「［未来日記 id・planned］」で表示される．図は `_synthetic` を末尾に持つファイルで，図の中に「仮想データ」と描き込んである．

投稿版（`./build.sh final`）は，印が 1 つでも `done` 以外のまま残っているか，`_synthetic` の図が本文に埋め込まれていれば，組み立てを止める．この関門は外さない．

## ファイル

| ファイル | 内容 |
|---|---|
| `timefont_journal.tex` | 原稿（1 ファイル。参考文献は `thebibliography` で本文に含む） |
| `timefont_journal_draft.pdf` | 下書き版の PDF（印の段落を青で組んである） |
| `facts_ledger.md` | 事実台帳。執筆時に参照する唯一の出典。ここに無いことは印を付けずに書かない |
| `future_diary_plan.md` | 未来日記の設計。節ごとに何を置くか，想定の数値の一覧 |
| `future_diary_status.md` | 印の一覧（`fd_status.py` が生成）。未解決の印がそのまま作業の待ち行列になる |
| `fd_status.py` | 印を集めて一覧を書き，`--gate` で投稿版の関門を通す |
| `build.sh` | `draft` または `final` で組む |
| `make_figs.py` | 模式図と仮想データの図を作る（乱数の種は固定） |
| `figs/` | 図。`fig_wiss_*.png` と `fig_beta1_forest.png` は実測の図（再掲）。`fig_*_schematic.png` は模式図。`*_synthetic.png` は仮想データ |
| `ipsj.cls`, `ipsjsort.bst`, `ipsjunsrt.bst` | 情報処理学会論文誌のクラスファイル（ipsj_v4-1，2025-02-05 版。https://www.ipsj.or.jp/journal/submit/style.html から取得） |

## 組み方

TeX 処理系は，この機械では利用者領域に導入した TinyTeX（`/Users/kurihara/Library/TinyTeX/bin/universal-darwin`）の platex と dvipdfmx を用いる．`build.sh` が PATH に加える．

```
cd /Users/kurihara/Desktop/claude-work/iFont-paper/paper/journal
./build.sh draft    # 下書き版 timefont_journal_draft.pdf
./build.sh final    # 投稿版（未解決の印が残っていれば止まる）
python3.11 make_figs.py   # 図を作り直す
```

TinyTeX を別の機械に入れるには，`curl -sL https://yihui.org/tinytex/install-bin-unix.sh | sh` のあと `tlmgr install collection-langjapanese latexmk` を行う．

## 実測に置き換える手順

1. `future_diary_status.md` の未解決の印から 1 つ選び，`desc` に書かれた作業を行う．
2. 本文の数値を実測値に書き換える．先に置いた値に合わせて実験してはならない．
3. 図は `make_figs.py` の入力を実測値に差し替え，「仮想データ」の描き込みを消し，ファイル名から `_synthetic` を外し，`_synthetic` のファイルをその場で消す．
4. 印の `status` を `done` にする．
5. `./build.sh draft` で確かめ，全部が `done` になったら `./build.sh final` を通す．

## 推敲

paper-style スキルの `style_check.py --all-positions`，`hihouwa_check.py`，`katakana_check.py`，`kunyomi_check.py` を掛けて裁定した（2026-10-08）．裁定の要点は次のとおりである．

- 否定から書き始める段落（癖1）: 2 件を肯定形に直した（概要の第 1 文，一対比較の結果の文）．
- 経緯の語・比喩（癖2・4）: 「基礎として用い」「測定の面では」「ことが分かった」など 5 件を直した．「その結果」（章の内容の指示）は残した．
- 非飽和名詞の書き出し（癖10）: 10 件すべてに「何の」を補った（「取りの判定」「候補版を作成する手順」「対戦の条件」など）．検査では 0 件になった．
- 訓読みの動詞（癖7）: 149 件から 93 件に減らした．直したのは，測る・確かめる・選ぶ・合わせる（$x_0$ の操作）・決まる・収まる・要る・作る・使う・広げる・埋める・動く・上げる・近づく・済む・崩れる・効く・劣る・知る など．残したのは，聞く人・見る人・読む・押す・触れる・現れる・分かる・当てる（かるたの体験の描写と，主張の平易さを担う語），打ち切る・読み上げる・作り直す・測り直す（複合動詞），仮定を置く・事前分布を置く・割合を占める（学術の慣用），「速さに合わせて設計する」（timeFont の定義の文言）である．
- 否定で終わる文（癖6）: 427 文中 18 文（4.2%）．残したのは限界と設計の明言である．
- 全称: 「すべての札が第一音で確定する」「44 枚すべての先頭字が異なる」は上毛かるたの事実，「任意のスケジュール」は方向 2 の主張の引用なので残した．
- カタカナ語: 1 万字あたり 132 件で，避けすぎの語は見当たらなかった．
