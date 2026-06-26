#!/usr/bin/env python3
"""
百人一首（上句）かな bigram カバー率調査
=========================================

問い: 競技かるた／kikiwake が実際に読み上げる「百人一首・上句」のかな2連接(bigram)は、
      一般日本語のかな bigram をどれだけカバーするか。
      → ある程度カバーするなら、kikiwake 実読みデータを使った2文字課題(C1→C2)の射程が広い。

データ
  HI(numerator) : Kikiwake mfa_v3/modern_kana_kamigoku.json (100首の上句・現代かな)
  一般日本語    : Tatoeba 日本語文 248,758文 (CC-BY 2.0 FR) を fugashi+UniDic(NINJAL) で
                  読み(カタカナ)化 → ひらがな化 → 連続読みのかな bigram 頻度分布。

単位
  char  : 隣接かな2文字 (「かな2連接」の文字どおり) … 主指標
  mora  : 拗音(ゃゅょ・小書き母音・ゎ)を直前かなに結合した1モーラ単位 … 従指標

連鎖の作り方
  各文/各歌の読みを連結し、ひらがな以外(漢字無読み・長音符ー・記号・英数)で連鎖を分断。
  分断された各セグメント内で隣接ペアを bigram とする(語境界はまたぐ=連続読み相当)。
  HI の上句は空白(5-7-5の区切り)を除去して連続1チェーン扱い。

指標
  type coverage  = |HI ∩ Corpus| / |Corpus|        (日本語 bigram 種の何%をHIが持つか)
  token coverage = Σ_{b∈HI} freq(b) / Σ_all freq    (実テキスト bigram 出現の何%がHIにもある連接か)
  reverse        = |HI ∩ Corpus| / |HI|             (HI bigram の何%が一般日本語で観測されるか=妥当性)
"""
import json, sys, os, bz2, collections, unicodedata, pickle
import fugashi, jaconv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ifont_common as ic

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
KAMIGOKU = "/Users/kurihara/Dropbox/dev/Kikiwake-tmp/mfa_v3/modern_kana_kamigoku.json"
TATOEBA = os.path.join(HERE, "jpn_sentences.tsv")
OUT_JSON = os.path.join(HERE, "bigram_coverage_result.json")

# ひらがな小書き(拗音・促音以外で前のモーラに結合するもの)
SMALL_COMBINING = set("ゃゅょぁぃぅぇぉゎ")  # っ は単独モーラ扱い
HIRA_START, HIRA_END = 0x3041, 0x3096  # ぁ..ゖ
def is_kana_char(c):
    return HIRA_START <= ord(c) <= HIRA_END  # ー(30FC) や記号は除外

def to_hira(s):
    return jaconv.kata2hira(s)

def kana_segments(reading_hira):
    """ひらがな読み文字列を、非かな(ー含む)で分断したかなセグメントのリストに。"""
    segs, cur = [], []
    for c in reading_hira:
        if is_kana_char(c):
            cur.append(c)
        else:
            if cur: segs.append("".join(cur)); cur=[]
    if cur: segs.append("".join(cur))
    return segs

def to_morae(seg):
    """かなセグメント -> モーラ列 (拗音/小書き母音/ゎ を直前に結合)。"""
    morae=[]
    for c in seg:
        if c in SMALL_COMBINING and morae:
            morae[-1]+=c
        else:
            morae.append(c)
    return morae

def char_bigrams(seg):
    return [(seg[i], seg[i+1]) for i in range(len(seg)-1)]

def mora_bigrams(seg):
    m=to_morae(seg)
    return [(m[i], m[i+1]) for i in range(len(m)-1)]

# ---------- HI 上句 ----------
def hi_bigrams():
    d=json.load(open(KAMIGOKU))
    char_set=set(); mora_set=set()
    n_mora_total=0
    for k,v in d.items():
        reading=to_hira(v.replace(" ","").replace("　",""))
        for seg in kana_segments(reading):
            char_set.update(char_bigrams(seg))
            mora_set.update(mora_bigrams(seg))
            n_mora_total+=len(to_morae(seg))
    return char_set, mora_set, n_mora_total

# ---------- 一般日本語コーパス ----------
def corpus_bigrams(limit=None):
    tagger=fugashi.Tagger()
    char_freq=collections.Counter(); mora_freq=collections.Counter()
    n_sent=0
    src = TATOEBA if os.path.exists(TATOEBA) else None
    opener = open
    if src is None and os.path.exists(TATOEBA+".bz2"):
        src, opener = TATOEBA+".bz2", lambda p,**k: bz2.open(p, "rt", encoding="utf-8")
    elif src is None:
        sys.exit("コーパスが無い: jpn_sentences.tsv(.bz2) を bigram_coverage/ に置く "
                 "(https://downloads.tatoeba.org/exports/per_language/jpn/jpn_sentences.tsv.bz2)")
    with opener(src, encoding="utf-8") as f:
        for line in f:
            parts=line.rstrip("\n").split("\t")
            if len(parts)<3: continue
            text=parts[2]
            # 各文の読みを連結
            reading=[]
            for w in tagger(text):
                k=getattr(w.feature,"kana",None)
                reading.append(to_hira(k) if k else "\x00")  # 読み無し=分断マーカ
            reading="".join(reading)
            for seg in kana_segments(reading):
                for b in char_bigrams(seg): char_freq[b]+=1
                for b in mora_bigrams(seg): mora_freq[b]+=1
            n_sent+=1
            if limit and n_sent>=limit: break
            if n_sent % 50000 == 0:
                print(f"  ...{n_sent} sentences", file=sys.stderr)
    return char_freq, mora_freq, n_sent

def coverage(hi_set, corp_freq):
    total_tok=sum(corp_freq.values())
    corp_types=set(corp_freq)
    inter=hi_set & corp_types
    type_cov=len(inter)/len(corp_types) if corp_types else 0
    token_cov=sum(corp_freq[b] for b in inter)/total_tok if total_tok else 0
    reverse=len(inter)/len(hi_set) if hi_set else 0
    hi_only=hi_set - corp_types  # HIにあるが一般コーパスに無い(古語的)
    missed=[(b,corp_freq[b]) for b in corp_types - hi_set]
    missed.sort(key=lambda x:-x[1])
    return dict(corp_types=len(corp_types), hi_types=len(hi_set),
                intersection=len(inter), type_cov=type_cov, token_cov=token_cov,
                reverse=reverse, total_tokens=total_tok,
                hi_only=sorted("".join(b) for b in hi_only),
                top_missed=[("".join(b),c) for b,c in missed[:40]])

def coverage_restricted(hi_set, corp_freq, charset):
    """bigram の両文字が charset に含まれるものだけに限定した被覆率。
    音声/視覚の2文字課題で実際に出題しうる連接だけを分母にする。"""
    cs=set(charset)
    def ok(b): return b[0] in cs and b[1] in cs
    corp={b:f for b,f in corp_freq.items() if ok(b)}
    hi={b for b in hi_set if ok(b)}
    total=sum(corp.values()); types=set(corp); inter=hi&types
    missed=sorted(((b,corp[b]) for b in types-hi), key=lambda x:-x[1])
    return dict(charset_size=len(cs), corp_types=len(types), hi_types=len(hi),
                intersection=len(inter),
                type_cov=len(inter)/len(types) if types else 0,
                token_cov=sum(corp[b] for b in inter)/total if total else 0,
                total_tokens=total,
                top_missed=[("".join(b),c) for b,c in missed[:25]])

def main():
    limit=int(sys.argv[1]) if len(sys.argv)>1 else None
    print("HI 上句 bigram 抽出...", file=sys.stderr)
    hi_char, hi_mora, hi_n_mora = hi_bigrams()
    print(f"  HI: char-bigram種={len(hi_char)}, mora-bigram種={len(hi_mora)}, 総モーラ={hi_n_mora}", file=sys.stderr)
    print("コーパス解析中(数分)...", file=sys.stderr)
    corp_char, corp_mora, n_sent = corpus_bigrams(limit)
    result=dict(
        meta=dict(corpus="Tatoeba jpn_sentences (CC-BY 2.0 FR)", n_sentences=n_sent,
                  dict="UniDic-lite (NINJAL) via fugashi",
                  hi_source="Kikiwake modern_kana_kamigoku.json (100首上句)",
                  hi_total_morae=hi_n_mora),
        char=coverage(hi_char, corp_char),
        mora=coverage(hi_mora, corp_mora),
        restricted=dict(
            audio_all=coverage_restricted(hi_char, corp_char, ic.AUDIO_ALL),
            audio_karuta=coverage_restricted(hi_char, corp_char, ic.AUDIO_KARUTA),
            visual_all=coverage_restricted(hi_char, corp_char, ic.VISUAL_ALL),
        ),
    )
    json.dump(result, open(OUT_JSON,"w"), ensure_ascii=False, indent=1)
    pickle.dump(dict(corp_char=corp_char, corp_mora=corp_mora,
                     hi_char=hi_char, hi_mora=hi_mora),
                open(os.path.join(HERE,"freq.pkl"),"wb"))
    # サマリ表示
    for unit in ("char","mora"):
        r=result[unit]
        print(f"\n===== {unit} 単位 =====")
        print(f"  一般日本語 bigram種(Tatoeba): {r['corp_types']:,}  総出現: {r['total_tokens']:,}")
        print(f"  HI上句 bigram種            : {r['hi_types']:,}")
        print(f"  交差(HIが持つ日本語bigram種): {r['intersection']:,}")
        print(f"  type coverage  (種の被覆)   : {r['type_cov']*100:.1f}%")
        print(f"  token coverage (出現の被覆) : {r['token_cov']*100:.1f}%")
        print(f"  reverse (HI bigramの妥当性) : {r['reverse']*100:.1f}%  (一般語に無いHI連接 {len(r['hi_only'])}種)")
    print("\n===== 文字セット限定 (両文字がセット内の連接のみ) =====")
    for name,rr in result["restricted"].items():
        print(f"  [{name} {rr['charset_size']}字]  日本語bigram種={rr['corp_types']}  HI種={rr['hi_types']}  "
              f"type={rr['type_cov']*100:.1f}%  token={rr['token_cov']*100:.1f}%")
    print(f"\n結果: {OUT_JSON}")

if __name__=="__main__":
    main()
