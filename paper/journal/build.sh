#!/bin/bash
# 情報処理学会論文誌の原稿を組む。
#   ./build.sh draft   下書き版（未来日記の段落を青で組み、先頭に札を付ける）
#   ./build.sh final   投稿版（done でない印か _synthetic の図が残っていれば止まる）
set -e
cd "$(dirname "$0")"
MODE=${1:-draft}
NAME=timefont_journal
export PATH=$PATH:/Users/kurihara/Library/TinyTeX/bin/universal-darwin

if [ "$MODE" = "final" ]; then
  python3 fd_status.py $NAME.tex --gate
  echo "\\FDfinaltrue" > fdmode.tex
else
  python3 fd_status.py $NAME.tex
  echo "\\FDfinalfalse" > fdmode.tex
fi

platex -interaction=nonstopmode -halt-on-error $NAME.tex > build_platex1.log 2>&1 || { tail -40 build_platex1.log; exit 1; }
platex -interaction=nonstopmode -halt-on-error $NAME.tex > build_platex2.log 2>&1 || { tail -40 build_platex2.log; exit 1; }
platex -interaction=nonstopmode -halt-on-error $NAME.tex > build_platex3.log 2>&1 || { tail -40 build_platex3.log; exit 1; }
dvipdfmx -q $NAME.dvi
if [ "$MODE" = "final" ]; then
  cp $NAME.pdf ${NAME}_final.pdf
  echo "投稿版: $(pwd)/${NAME}_final.pdf"
else
  cp $NAME.pdf ${NAME}_draft.pdf
  echo "下書き版: $(pwd)/${NAME}_draft.pdf"
fi
grep -c "Overfull" $NAME.log | sed 's/^/Overfull の数: /' || true
