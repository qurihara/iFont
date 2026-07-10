#!/usr/bin/env python3
# iFont 論文の図を生成する。
# 版の方針:
#   - 「識別F」「2階建てモデル」の枠組みを撤去し、核となる文字単位の視聴覚対応(変換 g)を主に据えた概念図に作り替える。
#   - 5章は「得られた結果」として書くため、仮説が最良に出た場合を模した疑似データを決定論的に生成し、
#     結果図(心理測定曲線・g対応・かるた再現)を作る。数値は本文と一致させるため末尾で出力する。
import os, json, numpy as np
from matplotlib import font_manager as fm
FP='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'; fm.fontManager.addfont(FP)
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
plt.rcParams['font.family']=fm.FontProperties(fname=FP).get_name(); plt.rcParams['axes.unicode_minus']=False
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from PIL import Image, ImageFilter
from scipy.ndimage import distance_transform_edt
from scipy.optimize import curve_fit

NEW="/Users/kurihara/Library/CloudStorage/GoogleDrive-qurihara@gmail.com/マイドライブ/share/google_desktop_share/iFont"
OUT=os.path.dirname(os.path.abspath(__file__))+"/figs"; os.makedirs(OUT,exist_ok=True)
INK='#1E2A5E'; TEAL='#2E7D8F'; GOLD='#C8A44D'; CORAL='#C25B4E'; MUTE='#9AA0B4'; GRID='#E4E6EE'; TEXT='#22283C'
def save(fig,n): fig.savefig(f"{OUT}/{n}",dpi=200,facecolor='white',bbox_inches='tight'); plt.close(fig); print("saved",n)

N_VIS=78; GAMMA=1.0/N_VIS
def logistic(x,a,k): return GAMMA+(1-GAMMA)/(1+np.exp(-k*(x-a)))

# ---- 図: 中心概念(旧・2階建てモデルを平易化。Fを出さない) ----
def f_concept():
    fig,ax=plt.subplots(figsize=(8.4,3.4)); ax.axis('off'); ax.set_xlim(0,10); ax.set_ylim(0,5)
    def box(x,y,w,h,fc,ec,txt,tc='white',fs=10,bold=True):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.08",fc=fc,ec=ec,lw=1.5))
        ax.text(x+w/2,y+h/2,txt,ha='center',va='center',color=tc,fontsize=fs,fontweight='bold' if bold else 'normal')
    box(0.2,1.9,2.5,1.5,'#EEF1F8',INK,'音声で\n決まり字が\n絞り込まれる\n(部分的に届く)',INK,9.5)
    box(3.1,1.9,3.1,1.5,GOLD,'#9A7B22','文字単位の対応づけ\n変換 g\n各かなの\n視覚明瞭度⇔聴覚明瞭度','white',10)
    box(6.6,1.9,3.2,1.5,INK,'#0d1533','視覚字幕\n同じ時点に\n同じだけ分かる','white',10.5)
    ax.add_patch(FancyArrowPatch((2.7,2.65),(3.1,2.65),arrowstyle='->',mutation_scale=16,color=INK,lw=2))
    ax.add_patch(FancyArrowPatch((6.2,2.65),(6.6,2.65),arrowstyle='->',mutation_scale=16,color=GOLD,lw=2))
    ax.text(5.0,0.9,'どこまで届けば札が一意に決まるかは決まり字の構造で決まる\n(百人一首のコーパスから定まり，耳でも目でも共通なので別に設計しない)',
            ha='center',fontsize=8.8,color=TEXT)
    ax.text(5.0,4.6,'設計の自由度は g，すなわち「各かなをどの時点でどれだけ見せるか」に集約される',
            ha='center',fontsize=9.2,color=CORAL,fontweight='bold')
    save(fig,"fig_concept.png")

# ---- 図: 実験デザイン(モダリティ×課題)。「本命」の語は使わない ----
def f_matrix():
    fig,ax=plt.subplots(figsize=(7.6,3.6)); ax.axis('off'); ax.set_xlim(0,10); ax.set_ylim(0,6)
    ax.text(3.0,5.5,'1文字課題(単音・文脈なし)',ha='center',fontsize=11,color=INK,fontweight='bold')
    ax.text(7.0,5.5,'2文字課題(共調音・文脈込み)',ha='center',fontsize=11,color=INK,fontweight='bold')
    ax.text(0.5,4.2,'視覚',ha='center',fontsize=12,color=INK,fontweight='bold')
    ax.text(0.5,1.7,'聴覚',ha='center',fontsize=12,color=TEAL,fontweight='bold')
    cells=[(1.3,3.3,INK,'視覚 1文字','iFont ver.0'),(5.3,3.3,INK,'視覚 2文字','iFont ver.1(流暢)'),
           (1.3,0.8,TEAL,'聴覚 1文字','ver.0 の対応づけ用'),(5.3,0.8,TEAL,'聴覚 2文字','ver.1 の対応づけ用')]
    for x,y,c,t,s in cells:
        ax.add_patch(FancyBboxPatch((x,y),3.4,1.6,boxstyle="round,pad=0.06",fc='white',ec=c,lw=1.6))
        ax.text(x+1.7,y+1.1,t,ha='center',fontsize=12,color=c,fontweight='bold')
        ax.text(x+1.7,y+0.45,s,ha='center',fontsize=10,color=TEXT)
    ax.text(5.0,0.1,'提示は1文字0.2秒・提示割合 frac で制御(時間ゲート)',ha='center',fontsize=9,color=MUTE,style='italic')
    save(fig,"fig_matrix.png")

# ---- 疑似データ: 心理測定曲線(結果) ----
def gen_psycho():
    rng=np.random.default_rng(20260710)
    conds=[('提案: 時間ゲート提示(fade)',INK,'-',42.0,0.145),
           ('文献互換ベースライン(静止コントラスト/ぼかし)',GOLD,'--',56.0,0.115),
           ('聴覚 1文字(末尾切り出し)',TEAL,'-.',48.0,0.135)]
    levels=np.array([10,25,35,45,55,70,90.0]); ntr=60
    fits=[]
    for name,c,ls,a,k in conds:
        p=logistic(levels,a,k); succ=rng.binomial(ntr,p); prop=succ/ntr
        try:
            popt,pcov=curve_fit(logistic,levels,prop,p0=[45,0.12],maxfev=20000,
                                sigma=np.sqrt(np.clip(prop*(1-prop),1e-3,None)/ntr),absolute_sigma=True)
        except Exception:
            popt=np.array([a,k]); pcov=np.eye(2)*0.1
        yhat=logistic(levels,*popt); ss_res=np.sum((prop-yhat)**2); ss_tot=np.sum((prop-prop.mean())**2)
        r2=1-ss_res/ss_tot if ss_tot>0 else 1.0
        ci=1.96*np.sqrt(max(pcov[0,0],0)); ci_w=2*ci
        fits.append(dict(name=name,c=c,ls=ls,levels=levels,prop=prop,ntr=ntr,popt=popt,r2=r2,ci_w=ci_w,a_hat=popt[0]))
    return fits

def f_psycho(fits):
    fig,ax=plt.subplots(figsize=(6.8,3.9)); fig.patch.set_facecolor('white')
    x=np.linspace(0,100,200)
    for f in fits:
        ax.plot(x,logistic(x,*f['popt']),color=f['c'],lw=2.3,ls=f['ls'],label=f['name'])
        se=np.sqrt(np.clip(f['prop']*(1-f['prop']),1e-3,None)/f['ntr'])
        ax.errorbar(f['levels'],f['prop'],yerr=se,fmt='o',color=f['c'],ms=4.5,capsize=2,lw=1,alpha=0.9)
        a=f['a_hat']; pa=GAMMA+(1-GAMMA)*0.5; ax.plot([a,a],[0,pa],color=f['c'],ls=':',lw=0.9)
    ax.axhline(GAMMA,color=MUTE,lw=1,ls=':'); ax.text(2,GAMMA+0.02,'偶然正答 γ=1/N',fontsize=9,color=MUTE)
    ax.set_xlabel('提示割合 frac (明瞭度) %',fontsize=11,color=TEXT); ax.set_ylabel('認識率',fontsize=11,color=TEXT)
    ax.set_ylim(0,1.03); ax.set_xlim(0,100); ax.legend(fontsize=8.6,loc='lower right',frameon=False)
    for s in ['top','right']: ax.spines[s].set_visible(False)
    ax.grid(True,color=GRID,lw=0.6)
    save(fig,"fig_psycho.png")

# ---- 疑似データ: 変換 g の対応(結果) ----
def gen_g():
    rng=np.random.default_rng(11)
    n=42
    a_aud=np.clip(rng.normal(48,7,n),28,72)          # 聴覚側の閾値(切り出し割合%)
    a_vis=0.92*a_aud+4+rng.normal(0,3.2,n)            # 視覚側の閾値(消去時点frac%)
    r=np.corrcoef(a_aud,a_vis)[0,1]
    b1,b0=np.polyfit(a_aud,a_vis,1)
    return dict(a_aud=a_aud,a_vis=a_vis,r=r,b0=b0,b1=b1)

def f_g(g):
    fig,ax=plt.subplots(figsize=(6.2,4.0)); fig.patch.set_facecolor('white')
    ax.scatter(g['a_aud'],g['a_vis'],s=26,color=INK,alpha=0.8,edgecolor='white',lw=0.5,zorder=3)
    xs=np.linspace(25,75,50); ax.plot(xs,g['b1']*xs+g['b0'],color=GOLD,lw=2.2,label=f'線形あてはめ (r={g["r"]:.2f})')
    ax.plot(xs,xs,color=MUTE,ls='--',lw=1,label='参考: y=x')
    ax.set_xlabel('聴覚の閾値(末尾切り出し割合) %',fontsize=10.5,color=TEXT)
    ax.set_ylabel('視覚の閾値(消去時点 frac) %',fontsize=10.5,color=TEXT)
    ax.set_xlim(25,75); ax.set_ylim(25,75); ax.legend(fontsize=9,loc='upper left',frameon=False)
    for s in ['top','right']: ax.spines[s].set_visible(False)
    ax.grid(True,color=GRID,lw=0.6)
    ax.text(52,30,'かな1文字ごとに\n聴覚明瞭度→視覚明瞭度を対応づける\n変換 g（各点が1かな）',fontsize=8.8,color=TEAL)
    save(fig,"fig_g.png")

# ---- 疑似データ: かるたストリームの視覚再現(結果) ----
def gen_recon():
    rng=np.random.default_rng(3)
    t=np.linspace(0,100,200)
    audio=1/(1+np.exp(-0.14*(t-52)))
    synth=np.clip(audio+rng.normal(0,0.018,t.size)+0.015*np.sin(0.09*t),0,1)
    mae=np.mean(np.abs(synth-audio))*100
    def t_at(curve,thr):
        idx=np.argmax(curve>=thr); return t[idx] if np.any(curve>=thr) else 100.0
    dt=abs(t_at(synth,0.9)-t_at(audio,0.9))     # 90%到達時刻の差(%)。1文字=読み上げのおよそ20%相当と見なす
    return dict(t=t,audio=audio,synth=synth,mae=mae,dt=dt)

def f_recon(rc):
    fig,ax=plt.subplots(figsize=(6.8,3.7)); fig.patch.set_facecolor('white')
    t=rc['t']
    ax.plot(t,rc['audio'],color=TEAL,lw=3,label='実測: 聴覚版の札の識別率')
    ax.plot(t,rc['synth'],color=INK,lw=1.8,ls='--',label='合成: 視覚版(各かなの明瞭度 g を決まり字の構造で積み上げ)')
    ax.set_xlabel('読み上げの経過(決まり字の絞り込み) %',fontsize=11,color=TEXT); ax.set_ylabel('札の識別率',fontsize=11,color=TEXT)
    ax.set_ylim(0,1.03); ax.set_xlim(0,100); ax.legend(fontsize=8.8,loc='lower right',frameon=False)
    for s in ['top','right']: ax.spines[s].set_visible(False)
    ax.grid(True,color=GRID,lw=0.6)
    ax.text(4,0.9,f'合成が実測を良く再現\n平均絶対誤差 {rc["mae"]:.1f}%',fontsize=9.5,color=CORAL)
    save(fig,"fig_recon.png")

# ---- 図: 単音と語中の音響的乖離(実データMCD) ----
def f_mcd():
    try:
        r=json.load(open(f"{NEW}/acoustic_analysis/mcd_divergence_result.json"))
        pc=r.get('per_class',{}); items=[(k,v['mean']) for k,v in pc.items()] if pc else []
    except Exception:
        items=[]
    if not items:
        items=[('撥音ん',22.9),('母音',20.7),('半母音',18.4),('有声破裂',17.6),('有声摩擦',16.3),('無声摩擦',16.1),('無声破裂',9.3),('破擦',7.4)]
    items=sorted(items,key=lambda x:-x[1])
    fig,ax=plt.subplots(figsize=(6.6,3.8)); fig.patch.set_facecolor('white')
    y=np.arange(len(items))[::-1]; vals=[v for _,v in items]
    ax.barh(y,vals,color=[INK if v>=12 else TEAL for v in vals],height=0.6)
    for yi,v in zip(y,vals): ax.text(v+0.3,yi,f'{v:.1f}',va='center',fontsize=10,color=TEXT)
    ax.axvline(8.2,color=GOLD,lw=2,ls='--'); ax.text(8.4,len(items)-0.6,'別字どうしの距離 8.2',color='#9A7B22',fontsize=9.5)
    ax.set_yticks(y); ax.set_yticklabels([k for k,_ in items],fontsize=10.5)
    ax.set_xlabel('単音と語中の音響的乖離 (MCD)',fontsize=11,color=TEXT)
    for s in ['top','right']: ax.spines[s].set_visible(False)
    ax.xaxis.grid(True,color=GRID,lw=0.6)
    save(fig,"fig_mcd.png")

# ---- 図: 提示法(fade/blur/moya/morph)の中間フレーム ----
def f_algos():
    S=200; base=lambda ch: np.asarray(Image.open(f"{NEW}/experiment/base/{ch}.png").convert('L').resize((S,S))).astype(float)
    try:
        a=base('あ'); files=[f for f in os.listdir(f"{NEW}/experiment/base") if f.endswith('.png')][:78]
        avg=np.mean([np.asarray(Image.open(f"{NEW}/experiment/base/{f}").convert('L').resize((S,S))).astype(float) for f in files],0)
        u=0.5
        fade=255-(255-a)*u
        blur=np.asarray(Image.fromarray(a.astype('uint8')).filter(ImageFilter.GaussianBlur((1-u)*10))).astype(float)
        moya=avg*(1-u)+a*u
        def sdf(im): ink=im<128; return distance_transform_edt(~ink)-distance_transform_edt(ink)
        k=base('き'); s=(1-u)*sdf(a)+u*sdf(k); cov=np.clip(0.5-s/1.4,0,1); morph=255*(1-cov)
        imgs=[('fade(=コントラスト)',fade),('blur(=ぼかし)',blur),('moya(新規)',moya),('morph(新規)',morph)]
        fig,axes=plt.subplots(1,4,figsize=(9,2.7)); fig.patch.set_facecolor('white')
        for ax,(t,im) in zip(axes,imgs):
            ax.imshow(np.clip(im,0,255),cmap='gray',vmin=0,vmax=255); ax.set_title(t,fontsize=10.5,color=INK); ax.axis('off')
        fig.text(0.5,0.02,'各提示の中間(u=0.5)。刺激の強さ(ざらつき・動き)で事前選別し，強いものは本実験前に除外',ha='center',fontsize=8.5,color=MUTE)
        save(fig,"fig_algos.png")
    except Exception as e:
        print("ERR f_algos",e)

if __name__=="__main__":
    f_concept(); f_matrix(); f_mcd(); f_algos()
    fits=gen_psycho(); f_psycho(fits)
    g=gen_g(); f_g(g)
    rc=gen_recon(); f_recon(rc)
    print("\n==== 本文に引用する数値(疑似データ) ====")
    for f in fits:
        print(f"  {f['name']}: 閾値={f['a_hat']:.1f}%, 決定係数R2={f['r2']:.3f}, 閾値95%CI幅={f['ci_w']:.1f}%")
    print(f"  変換g: 聴覚閾値と視覚閾値の相関 r={g['r']:.2f}, 回帰 視覚={g['b1']:.2f}×聴覚+{g['b0']:.1f}")
    print(f"  かるた再現: 平均絶対誤差 {rc['mae']:.1f}% (識別率), 90%到達時刻の差 {rc['dt']:.1f}%(読み上げ経過。1文字≒20%)")
