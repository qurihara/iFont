#!/usr/bin/env python3
"""未来日記の印を LaTeX 原稿から集め、未解決の一覧を書き出す。

印の書式:
  \\begin{fd}{id}{status}{owner}{desc} ... \\end{fd}
  \\fdcaption{id}{status}{owner}{desc}{caption}

使い方:
  python3 fd_status.py timefont_journal.tex                 # 一覧を future_diary_status.md に書く
  python3 fd_status.py timefont_journal.tex --gate          # done でない印が残っていれば終了コード 1
"""
import re
import sys
from pathlib import Path

FD_ENV = re.compile(r'\\begin\{fd\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}')
FD_CAP = re.compile(r'\\fdcaption\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}')
SEC = re.compile(r'\\(section|subsection|subsubsection)\*?\{([^}]*)\}')
SYN = re.compile(r'\\includegraphics[^{]*\{([^}]*_synthetic[^}]*)\}')


def collect(tex_path):
    text = Path(tex_path).read_text(encoding='utf-8')
    entries = []
    chapter = ''
    section = ''
    lines = text.split('\n')
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('%'):
            continue
        m = SEC.search(line)
        if m:
            if m.group(1) == 'section':
                chapter = m.group(2)
                section = ''
            else:
                section = m.group(2)
        for kind, rx in (('para', FD_ENV), ('caption', FD_CAP)):
            for m2 in rx.finditer(line):
                head = ''
                for j in range(i + 1 if kind == 'para' else i, min(i + 6, len(lines))):
                    t = lines[j].strip()
                    if t and not t.startswith('%') and not t.startswith('\\begin{fd}'):
                        head = re.sub(r'\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})*', '', t)[:40]
                        break
                entries.append(dict(id=m2.group(1), status=m2.group(2), owner=m2.group(3),
                                    desc=m2.group(4), chapter=chapter, section=section,
                                    line=i + 1, kind=kind, head=head))
    synthetic = SYN.findall(text)
    return entries, synthetic


def write_status(entries, synthetic, out_path):
    left = [e for e in entries if e['status'] != 'done']
    rows = ['# 未来日記の状況', '',
            f'印の総数 {len(entries)}、未解決 {len(left)}、仮想データの図 {len(synthetic)}', '',
            '| id | 状態 | 章 | 節 | 担当 | 何をすれば事実になるか | 本文の書き出し |',
            '|---|---|---|---|---|---|---|']
    for e in entries:
        rows.append('| {id} | {status} | {chapter} | {section} | {owner} | {desc} | {head} |'.format(**e))
    rows.append('')
    rows.append('## 仮想データの図')
    rows.append('')
    for s in synthetic:
        rows.append(f'- {s}')
    Path(out_path).write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return left


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    tex = sys.argv[1]
    gate = '--gate' in sys.argv
    entries, synthetic = collect(tex)
    out = Path(tex).with_name('future_diary_status.md')
    left = write_status(entries, synthetic, out)
    print(f'印の総数 {len(entries)}、未解決 {len(left)}、仮想データの図 {len(synthetic)} -> {out}')
    if gate:
        bad = False
        if left:
            bad = True
            print('投稿版は作れない。まだ事実になっていない記述が残っている。', file=sys.stderr)
            for e in left:
                print('  [{id}] {chapter} {section} / 担当 {owner} / {desc}'.format(**e), file=sys.stderr)
        if synthetic:
            bad = True
            print('投稿版は作れない。仮想データの図が本文に埋め込まれている。', file=sys.stderr)
            for s in synthetic:
                print('  ' + s, file=sys.stderr)
        if bad:
            sys.exit(1)


if __name__ == '__main__':
    main()
