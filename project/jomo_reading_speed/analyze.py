#!/usr/bin/env python3.11
"""上毛かるた読み上げ音声の派生特徴量(RMS 包絡など)から、発話区間・速度・間隔・音量差を求める。

入力: features_<素材名>.json
  ブラウザ内の Web Audio API(ScriptProcessor 512 サンプル, 44.1 kHz → 約 11.6 ms ごと)で取り出した
  時刻つき特徴量。音声サンプルは含まない。
  frames: [[video.currentTime(s), rms, zcr, spectral_centroid(Hz), (1-4 kHz)/(0-1 kHz) エネルギー比(dB)], ...]

使い方:
  python3.11 analyze.py features_xxx.json [--label 名前] [--order つあい...] [--roles auto|gap|pair]
      [--first-hon 0] [--role-string hk...] [--gap-card 0.9] [--min-len 1.0] [--t-start 秒] [--t-end 秒] [--dump out.json] [--quiet]

方法の要点:
  1. RMS を dB にし、2 フレーム(約 24 ms)の移動平均で平滑化する。無音の床(10 パーセンタイル)と山(99 パーセンタイル)から
     しきい値を決め、しきい値を超える区間を 0.9 秒未満の切れ目は繋いで「1 回の読み(区間)」とする。
  2. 区間の中で、前後 0.25 秒の最大より 8 dB 以上落ち込む谷(1 フレーム以上。区間末尾 0.35 秒の減衰は除く)を「音節の切れ目」とみなし、谷で区切った断片を「句片」とする。
  3. 最後の句片は語尾の引き伸ばし(母音を長く伸ばす節回し)を含むので、
     「本体」= 区間の始まりから最後の句片の立ち上がりまで、として別に長さを出す。
     本体の速度 = (モーラ数 − 1) ÷ 本体の長さ。全体の速度 = モーラ数 ÷ 区間の長さ。
  4. 第一音の長さ = 区間の始まりから最初の谷まで(0.45 秒以内に谷があるとき)。無ければ「判別できず」。
  5. 上の句/下の句の境目 = 上の句のモーラ比率から予想した時刻に最も近い谷(予想の ±25% 以内にあるとき)。
  6. 本読み/空読みの割り当て = 隣接区間の間隔が(長, 短)と交互になっていればそれを使い(規則どおりの構造)、
     そうでなければ先頭から 2 つずつ対にする。
"""
import json, sys, argparse
import numpy as np

# 札の先頭かなとモーラ数(上の句, 下の句)。全文は書かない。
MORA = {
 'あ':(8,7),'い':(7,8),'う':(7,6),'え':(7,6),'お':(7,8),'か':(9,8),'き':(9,5),'く':(7,7),'け':(7,6),'こ':(8,8),
 'さ':(9,9),'し':(7,5),'す':(7,5),'せ':(9,5),'そ':(8,7),'た':(7,8),'ち':(7,9),'つ':(8,5),'て':(7,5),'と':(7,5),
 'な':(9,9),'に':(9,7),'ぬ':(8,7),'ね':(8,8),'の':(7,5),'は':(8,8),'ひ':(7,5),'ふ':(8,4),'へ':(6,6),'ほ':(7,6),
 'ま':(7,5),'み':(8,7),'む':(7,5),'め':(8,5),'も':(7,5),'や':(7,7),'ゆ':(7,8),'よ':(7,6),'ら':(8,7),'り':(8,7),
 'る':(8,7),'れ':(8,7),'ろ':(4,8),'わ':(7,6),
}
MEAN_UP = float(np.mean([a for a,b in MORA.values()]))
MEAN_LOW = float(np.mean([b for a,b in MORA.values()]))
MEAN_MORA = MEAN_UP + MEAN_LOW   # 44 札の平均モーラ数 (= 14.0)

def load(path):
    d = json.load(open(path))
    fr = np.array(d['frames'], dtype=float)
    t = fr[:,0]
    # 時刻が進まないフレーム(一時停止中)は落とす
    keep = np.r_[True, np.diff(t) > 0]
    # 時刻が大きく戻る箇所(広告や巻き戻し)で分割し、最も長い連続部分を使う
    resets = np.where(np.diff(t) < -0.5)[0] + 1
    runs = np.split(np.arange(len(t)), resets)
    run = max(runs, key=len)
    idx = run[keep[run]]
    return d, fr[idx]

def smooth(x, n):
    if n <= 1: return x
    return np.convolve(x, np.ones(n)/n, mode='same')

def runmax(x, n):
    # 前後 n フレームの最大
    out = x.copy()
    for k in range(1, n+1):
        out[k:] = np.maximum(out[k:], x[:-k]); out[:-k] = np.maximum(out[:-k], x[k:])
    return out

def segments(t, db, thr, min_gap, min_len):
    on = db > thr
    segs = []; i = 0; n = len(t)
    while i < n:
        if on[i]:
            j = i
            while j+1 < n and on[j+1]: j += 1
            segs.append([t[i], t[j]]); i = j+1
        else: i += 1
    merged = []
    for s in segs:
        if merged and s[0]-merged[-1][1] < min_gap: merged[-1][1] = s[1]
        else: merged.append(list(s))
    return [tuple(s) for s in merged if s[1]-s[0] >= min_len]

def dips(t, db, s, e, frame_dt, depth=8.0, win=0.25, min_dur=0.01, end_margin=0.35):
    """区間 [s,e] 内で、前後 win 秒の最大より depth dB 以上低い状態が min_dur 秒以上続く谷を返す。
    各谷は (谷の始まり, 谷の終わり, 最小 dB)。"""
    m = (t >= s) & (t <= e)
    tt = t[m]; dd = db[m]
    if len(dd) < 5: return []
    rm = runmax(dd, int(round(win/frame_dt)))
    low = dd < rm - depth
    out = []; i = 0; n = len(dd)
    while i < n:
        if low[i]:
            j = i
            while j+1 < n and low[j+1]: j += 1
            if tt[j]-tt[i] + frame_dt >= min_dur and i > 0 and j < n-1 and tt[i] < e - end_margin:
                out.append((float(tt[i]), float(tt[j]), float(dd[i:j+1].min())))
            i = j+1
        else: i += 1
    return out

def analyze(path, gap_card=0.9, min_len=1.0, order=None, roles='auto', first_hon=0, floor_db=None, t_start=0.0, t_end=None, role_string=None, kana_map=None):
    d, fr = load(path)
    m = fr[:,0] >= t_start
    if t_end is not None: m &= fr[:,0] <= t_end
    fr = fr[m]
    t = fr[:,0]; rms = fr[:,1]
    frame_dt = float(np.median(np.diff(t)))
    db = 20*np.log10(np.maximum(rms, 1e-6))
    db_s = smooth(db, 2)
    floor = float(np.percentile(db_s, 10)); peak = float(np.percentile(db_s, 99))
    thr = max(floor+12, peak-32) if floor_db is None else floor_db
    segs = segments(t, db_s, thr, gap_card, min_len)
    cards = []
    for (s,e) in segs:
        m = (t>=s)&(t<=e)
        mean_db = float(np.mean(db[m])); max_db = float(np.max(db[m]))
        dp = dips(t, db_s, s, e, frame_dt)
        # 句片: 谷で区切る
        bounds = [s] + [x for dpp in dp for x in (dpp[0], dpp[1])] + [e]
        phr = [(bounds[i], bounds[i+1]) for i in range(0, len(bounds)-1, 2)]
        phr = [p for p in phr if p[1]-p[0] > 0.02]
        tail = phr[-1] if phr else (s, e)
        core_end = tail[0]
        if e - tail[0] < 0.5: core_end = None   # 語尾が切り出せない(末尾に谷が無い)ときは本体の長さを出さない
        first = None
        if dp and dp[0][0]-s <= 0.45: first = dp[0][0]-s
        cards.append(dict(start=float(s), end=float(e), dur=float(e-s), core_dur=(float(core_end-s) if core_end else None), tail_dur=(float(e-tail[0]) if core_end else None),
                          n_phr=len(phr), n_dips=len(dp), mean_db=mean_db, max_db=max_db, first_mora=first,
                          dips=[(round(a-s,3), round(b-s,3)) for a,b,_ in dp],
                          phr_db=[float(np.mean(db[(t>=a)&(t<=b)])) for a,b in phr]))
    gaps = [cards[i+1]['start']-cards[i]['end'] for i in range(len(cards)-1)]
    # 役割の割り当て
    n = len(cards)
    role = [None]*n
    mode = roles
    if roles == 'auto':
        # (長, 短) の交互構造があるか: 奇数番目と偶数番目の間隔の比
        if len(gaps) >= 4:
            a = np.median(gaps[0::2]); b = np.median(gaps[1::2])
            mode = 'gap' if max(a,b)/max(min(a,b),1e-3) > 1.8 else 'pair'
        else: mode = 'pair'
    if role_string:
        mode = 'string'
        rs = role_string.replace(' ', '')
        for i in range(n): role[i] = {'h':'hon','k':'kara','x':'other'}.get(rs[i] if i < len(rs) else 'x', 'other')
    elif mode == 'gap':
        for i,g in enumerate(gaps):
            if g >= 3.0: role[i] = role[i] or 'hon'; role[i+1] = 'kara'
            else: role[i] = role[i] or 'kara'; role[i+1] = 'hon'
    else:
        for i in range(n): role[i] = 'hon' if (i-first_hon) % 2 == 0 else 'kara'
    for i,c in enumerate(cards): c['role'] = role[i]
    # 同一クリップの検出(長さと平均音量がほぼ一致する隣接対)
    for i in range(n-1):
        cards[i]['dup_next'] = bool(abs(cards[i]['dur']-cards[i+1]['dur']) < 0.03 and abs(cards[i]['mean_db']-cards[i+1]['mean_db']) < 0.3)
    cards[-1]['dup_next'] = False
    # 札の割り当て(順序が分かるとき: 本読みの順に与える)
    if order:
        k = 0
        for i,c in enumerate(cards):
            if c['role'] == 'hon':
                c['kana'] = order[k] if k < len(order) else None; k += 1
            elif c['role'] == 'kara':
                c['kana'] = cards[i-1].get('kana') if i > 0 and cards[i-1]['role']=='hon' else None
            else:
                c['kana'] = None
    if kana_map:
        for i,c in enumerate(cards):
            if i in kana_map: c['kana'] = kana_map[i]
    # 上の句/下の句の境目と速度
    for c in cards:
        u,l = MORA.get(c.get('kana'), (MEAN_UP, MEAN_LOW))
        N = u+l
        c['rate_total'] = N/c['dur']
        c['rate_core'] = (N-1)/c['core_dur'] if c['core_dur'] and c['core_dur'] > 0.3 else None
        # 上の句の終わりの予想時刻(本体の中での比率)。本体が取れないときは全体の長さから 0.4 倍を目安にする
        base = c['core_dur'] if c['core_dur'] else c['dur']*0.6
        pred = base*u/(N-1)
        cand = [dpp for dpp in c['dips'] if abs(dpp[0]-pred) <= 0.25*base]
        if cand:
            b = min(cand, key=lambda dpp: abs(dpp[0]-pred))
            c['up_dur'] = b[0]; c['low_dur'] = c['dur']-b[1]; c['low_core_dur'] = (c['core_dur']-b[1]) if c['core_dur'] else None; c['split_gap'] = b[1]-b[0]
            s = c['start']
            c['up_db'] = float(np.mean(db[(t>=s)&(t<=s+b[0])])); c['low_db'] = float(np.mean(db[(t>=s+b[1])&(t<=c['end'])]))
            c['rate_up'] = u/b[0]
            c['rate_low_core'] = (l-1)/c['low_core_dur'] if c['low_core_dur'] and c['low_core_dur'] > 0.15 else None
        else:
            for k in ('up_dur','low_dur','low_core_dur','split_gap','up_db','low_db','rate_up','rate_low_core'): c[k] = None
    return dict(file=path, frame_dt=frame_dt, floor_db=floor, peak_db=peak, thr_db=float(thr), role_mode=mode,
                t_range=(float(t[0]), float(t[-1])), n_cards=n, cards=cards, gaps=gaps)

def stat(xs):
    xs = [x for x in xs if x is not None and np.isfinite(x)]
    if not xs: return None
    return dict(n=len(xs), mean=float(np.mean(xs)), sd=float(np.std(xs)), min=float(np.min(xs)), max=float(np.max(xs)), median=float(np.median(xs)))

def summarize(res, label='', only_kana=False):
    cards = res['cards']; gaps = res['gaps']
    sel = (lambda c: bool(c.get('kana'))) if only_kana else (lambda c: True)
    hon = [c for c in cards if c['role']=='hon' and sel(c)]; kara = [c for c in cards if c['role']=='kara' and sel(c)]
    o = dict(label=label, role_mode=res['role_mode'], n_segments=len(cards), n_hon=len(hon), n_kara=len(kara),
             n_dup_pairs=sum(1 for c in cards if c.get('dup_next')))
    for nm, grp in (('hon',hon),('kara',kara)):
        o[nm+'_dur'] = stat([c['dur'] for c in grp]); o[nm+'_core_dur'] = stat([c['core_dur'] for c in grp])
        o[nm+'_tail_dur'] = stat([c['tail_dur'] for c in grp])
        o[nm+'_rate_total'] = stat([c['rate_total'] for c in grp]); o[nm+'_rate_core'] = stat([c['rate_core'] for c in grp])
        o[nm+'_rate_up'] = stat([c['rate_up'] for c in grp]); o[nm+'_rate_low_core'] = stat([c['rate_low_core'] for c in grp])
        o[nm+'_up_dur'] = stat([c['up_dur'] for c in grp]); o[nm+'_split_gap'] = stat([c['split_gap'] for c in grp])
        o[nm+'_first_mora'] = stat([c['first_mora'] for c in grp]); o[nm+'_first_undetected'] = sum(1 for c in grp if c['first_mora'] is None)
        o[nm+'_mean_db'] = stat([c['mean_db'] for c in grp]); o[nm+'_max_db'] = stat([c['max_db'] for c in grp])
        o[nm+'_up_minus_low_db'] = stat([c['up_db']-c['low_db'] for c in grp if c['up_db'] is not None])
        o[nm+'_n_phr'] = stat([c['n_phr'] for c in grp])
    g_hk = [g for i,g in enumerate(gaps) if cards[i]['role']=='hon' and cards[i+1]['role']=='kara']
    g_kh = [g for i,g in enumerate(gaps) if cards[i]['role']=='kara' and cards[i+1]['role']=='hon']
    o['gap_hon_to_kara'] = stat(g_hk); o['gap_kara_to_hon'] = stat(g_kh)
    hs = [c['start'] for c in hon]; o['hon_period'] = stat(list(np.diff(hs))) if len(hs) > 1 else None
    # 本読みと空読みの音量差(対ごと)
    diffs = []
    for i in range(len(cards)-1):
        if cards[i]['role']=='hon' and cards[i+1]['role']=='kara': diffs.append(cards[i]['mean_db']-cards[i+1]['mean_db'])
    o['hon_minus_kara_db'] = stat(diffs)
    return o

def fmt(s, unit='', nd=2):
    if not s: return '—'
    return f"{s['mean']:.{nd}f}±{s['sd']:.{nd}f}{unit} (n={s['n']}, {s['min']:.{nd}f}〜{s['max']:.{nd}f}, 中央値 {s['median']:.{nd}f})"

def report(res, s):
    print(f"file={res['file']} frame_dt={res['frame_dt']*1000:.1f}ms 範囲={res['t_range'][0]:.1f}〜{res['t_range'][1]:.1f}s floor={res['floor_db']:.1f}dB peak={res['peak_db']:.1f}dB thr={res['thr_db']:.1f}dB 役割判定={res['role_mode']}")
    print(f"区間数={s['n_segments']} 本読み={s['n_hon']} 空読み={s['n_kara']} 同一クリップの対={s['n_dup_pairs']}")
    for nm,jp in (('hon','本読み'),('kara','空読み')):
        print(f"[{jp}]")
        print('  発話時間(全体) [s]        :', fmt(s[nm+'_dur'],'s'))
        print('  本体(語尾の伸ばしを除く)[s]:', fmt(s[nm+'_core_dur'],'s'), ' 語尾', fmt(s[nm+'_tail_dur'],'s'))
        print('  モーラ速度(全体) [mora/s]  :', fmt(s[nm+'_rate_total']))
        print('  モーラ速度(本体) [mora/s]  :', fmt(s[nm+'_rate_core']))
        print('  上の句の速度 [mora/s]      :', fmt(s[nm+'_rate_up']), ' 上の句の長さ', fmt(s[nm+'_up_dur'],'s'))
        print('  下の句の速度(本体)[mora/s] :', fmt(s[nm+'_rate_low_core']), ' 句間の切れ目', fmt(s[nm+'_split_gap'],'s'))
        print('  第一音 [s]                 :', fmt(s[nm+'_first_mora'],'s',3), ' 判別できず', s[nm+'_first_undetected'])
        print('  平均音量 [dB]              :', fmt(s[nm+'_mean_db'],'dB',1), ' 最大', fmt(s[nm+'_max_db'],'dB',1))
        print('  上の句−下の句 [dB]          :', fmt(s[nm+'_up_minus_low_db'],'dB',1))
        print('  句片の数                    :', fmt(s[nm+'_n_phr'],'',1))
    print('本読み→空読み 間隔 [s]  :', fmt(s['gap_hon_to_kara'],'s'))
    print('空読み→本読み 間隔 [s]  :', fmt(s['gap_kara_to_hon'],'s'))
    print('本読み周期 [s]          :', fmt(s['hon_period'],'s'))
    print('本読み−空読み 音量 [dB] :', fmt(s['hon_minus_kara_db'],'dB',1))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('path'); ap.add_argument('--label', default=''); ap.add_argument('--order')
    ap.add_argument('--roles', default='auto'); ap.add_argument('--first-hon', type=int, default=0)
    ap.add_argument('--gap-card', type=float, default=0.9); ap.add_argument('--min-len', type=float, default=1.0)
    ap.add_argument('--floor-db', type=float); ap.add_argument('--dump'); ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--t-start', type=float, default=0.0); ap.add_argument('--t-end', type=float)
    ap.add_argument('--role-string', help='区間ごとの役割を h(本読み)/k(空読み)/x(除外) の文字列で明示する')
    ap.add_argument('--kana-map', help='区間番号と札の先頭かなの対応。例 "13=か,14=か,15=き"')
    ap.add_argument('--only-kana', action='store_true', help='札が特定できた区間だけを集計する')
    a = ap.parse_args()
    kana_map = {int(k): v for k, v in (kv.split('=') for kv in a.kana_map.split(','))} if a.kana_map else None
    res = analyze(a.path, a.gap_card, a.min_len, list(a.order) if a.order else None, a.roles, a.first_hon, a.floor_db, a.t_start, a.t_end, a.role_string, kana_map)
    s = summarize(res, a.label, a.only_kana)
    report(res, s)
    if a.dump: json.dump({'summary':s,'result':res}, open(a.dump,'w'), ensure_ascii=False, indent=1)
    if not a.quiet:
        for i,c in enumerate(res['cards']):
            g = res['gaps'][i] if i < len(res['gaps']) else float('nan')
            print(f"{i:3d} {c['role']:5s} {c.get('kana') or '':2s} {c['start']:7.2f}-{c['end']:7.2f} dur={c['dur']:.2f} core={c['core_dur'] or 0:.2f} tail={c['tail_dur'] or 0:.2f} up={c['up_dur'] if c['up_dur'] is None else round(c['up_dur'],2)} phr={c['n_phr']} db={c['mean_db']:.1f} fm={c['first_mora'] if c['first_mora'] is None else round(c['first_mora'],3)} dup={int(c['dup_next'])} next_gap={g:.2f}")
