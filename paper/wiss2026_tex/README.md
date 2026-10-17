# WISS 2026 timeFont（LaTeX 版）

投稿版 v15（`timeFont_WISS2026_投稿版.docx`）を WISS 2026 のテンプレートへ移したもの。
**この時点の内容は投稿版と同一。** 査読対応の修正はこれから入れる。

## ビルド

```
export PATH=/Library/TeX/texbin:$PATH
platex timefont && platex timefont && dvipdfmx timefont
```

`latexmk` も使えるが、同梱の `jwiss.bst` が upBibTeX で警告を出すため、
参考文献は `biblio.tex` の `thebibliography` に直書きしてある（bib は使わない）。

## ファイル

| | |
|---|---|
| `timefont.tex` | 本体。表題・概要・謝辞・未来ビジョン |
| `preamble.tex` | documentclass とパッケージ |
| `body.tex` | 本文（1〜8章） |
| `biblio.tex` | 参考文献 15 件 |
| `fig/` | 図 1〜5（投稿版の docx から取り出した PNG） |
| `wiss.cls` `wissbase11.cls` `jwiss.bst` `latexmkrc` | テンプレート同梱ファイル |

## 規定（WISS 2026 登壇発表）

- 本文 **6 ページ以内**。参考文献・謝辞・未来ビジョンは含まない
- カメラレディ締切 **2026-10-30（金）**
- 現状は本文が 7 ページ目に 4 行はみ出している。修正時に調整する

## 図

| 図 | 中身 | 査読での指摘 |
|---|---|---|
| 1 | 概念図（音声と文字を同じ識別度合いで対応づける） | なし |
| 2 | 4 表示方式の見え方 | なし |
| 3 | 「あ」の正答率曲線と進行度 | 小さい・補助線がない・本文の数値と対応しない |
| 4 | 正答率と情報量の違い | 同上。(b) の凡例が (a) と同じ語で意味が違う |
| 5 | アプリ画面 | なし |
