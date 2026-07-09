#!/usr/bin/env python3
import os, json, numpy as np
from matplotlib import font_manager as fm
FP='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'; fm.fontManager.addfont(FP)
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
plt.rcParams['font.family']=fm.FontProperties(fname=FP).get_name(); plt.rcParams['axes.unicode_minus']=False
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from PIL import Image, ImageFilter
from scipy.ndimage import distance_transform_edt

NEW="/Users/kurihara/Library/CloudStorage/GoogleDrive-qurihara@gmail.com/マイドライブ/share/google_desktop_share/iFont"
OUT=os.path.dirname(os.path.abspath(__file__))+"/paper_figs"; os.makedirs(OUT,exist_ok=True)
INK='#1E2A5E'; TEAL='#2E7D8F'; GOLD='#C8A44D'; CORAL='#C25B4E'; MUTE='#9AA0B4'; GRID='#E4E6EE'; TEXT='#22283C'
def save(fig,n): fig.savefig(f"{OUT}/{n}",dpi=200,facecolor='white',bbox_inches='tight'); plt.close(fig); print("saved",n)

# 図1 2階建てモデル
def f_model():
    fig,ax=plt.subplots(figsize=(8.2,3.6)); ax.axis('off'); ax.set_xlim(0,10); ax.set_ylim(0,5)
    def box(x,y,w,h,fc,ec,txt,tc='white',fs=11,bold=True):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.08",fc=fc,ec=ec,lw=1.5))
        ax.text(x+w/2,y+h/2,txt,ha='center',va='center',color=tc,fontsize=fs,fontweight='bold' if bold else 'normal')
    box(0.3,3.0,2.6,1.4,'#EEF1F8',INK,'音声かるた\nストリーム\n(部分的に届く)',INK,10)
    box(3.4,3.4,2.3,1.0,GOLD,'#9A7B22','g\n文字レベルの変換','white',12)
    box(3.4,1.2,2.3,1.0,TEAL,'#1d5563','F\n系列レベルの識別','white',12)
    box(6.4,3.0,3.2,1.4,INK,'#0d1533','合成: f_visual_karuta(t)\n= F( g(音声) )\n≒ 実測 f_audio_karuta(t)','white',10)
    ax.add_patch(FancyArrowPatch((2.9,3.7),(3.4,3.9),arrowstyle='->',mutation_scale=16,color=INK,lw=2))
    ax.add_patch(FancyArrowPatch((5.7,3.9),(6.4,3.8),arrowstyle='->',mutation_scale=16,color=GOLD,lw=2))
    ax.add_patch(FancyArrowPatch((4.55,3.4),(4.55,2.2),arrowstyle='<->',mutation_scale=13,color=MUTE,lw=1.4,ls='--'))
    ax.text(4.75,2.8,'各かなの\n視覚明瞭度\np=g(τ)',fontsize=8.5,color=TEXT,va='center')
    ax.text(5.75,1.6,'決まり字の組合せ論\n(コーパスから計算,\nモダリティ非依存)',fontsize=8.5,color=TEXT,va='center')
    save(fig,"fig_model.png")

# 図2 実験デザイン(モダリティ×課題)
def f_matrix():
    fig,ax=plt.subplots(figsize=(7.6,3.6)); ax.axis('off'); ax.set_xlim(0,10); ax.set_ylim(0,6)
    ax.text(3.0,5.5,'1文字課題(単音・文脈なし)',ha='center',fontsize=11,color=INK,fontweight='bold')
    ax.text(7.0,5.5,'2文字課題(共調音・文脈込み)',ha='center',fontsize=11,color=INK,fontweight='bold')
    ax.text(0.5,4.2,'視覚',ha='center',fontsize=12,color=INK,fontweight='bold')
    ax.text(0.5,1.7,'聴覚',ha='center',fontsize=12,color=TEAL,fontweight='bold')
    cells=[(1.3,3.3,INK,'視覚 1文字','iFont ver.0'),(5.3,3.3,INK,'視覚 2文字','iFont ver.1(本命)'),
           (1.3,0.8,TEAL,'聴覚 1文字','ver.0 の対応づけ用'),(5.3,0.8,TEAL,'聴覚 2文字','ver.1 の対応づけ用')]
    for x,y,c,t,s in cells:
        ax.add_patch(FancyBboxPatch((x,y),3.4,1.6,boxstyle="round,pad=0.06",fc='white',ec=c,lw=1.6))
        ax.text(x+1.7,y+1.1,t,ha='center',fontsize=12,color=c,fontweight='bold')
        ax.text(x+1.7,y+0.45,s,ha='center',fontsize=10,color=TEXT)
    ax.text(5.0,0.1,'提示は1文字0.2秒・frac%で消去(時間ゲート)',ha='center',fontsize=9,color=MUTE,style='italic')
    save(fig,"fig_matrix.png")

# 図3 心理測定曲線 + 文献互換ベースライン
def f_psycho():
    fig,ax=plt.subplots(figsize=(6.6,3.8)); fig.patch.set_facecolor('white')
    x=np.linspace(0,100,200); g=1/78
    def L(a,b): z=b*(x-a); return g+(1-g)/(1+np.exp(-z))
    ax.plot(x,L(45,0.12),color=INK,lw=2.5,label='提案: 時間ゲート提示(fade/blur/moya)')
    ax.plot(x,L(58,0.10),color=GOLD,lw=2.5,ls='--',label='文献互換ベースライン(静止コントラスト/ぼかし)')
    for a,c in [(45,INK),(58,GOLD)]:
        pa=g+(1-g)*0.5; ax.plot(a,pa,'o',color=c,ms=8); ax.plot([a,a],[0,pa],color=c,ls=':',lw=1)
    ax.set_xlabel('明瞭度(frac または 劣化水準) %',fontsize=11,color=TEXT)
    ax.set_ylabel('認識率',fontsize=11,color=TEXT); ax.set_ylim(0,1.02); ax.set_xlim(0,100)
    ax.axhline(g,color=MUTE,lw=1,ls=':'); ax.text(2,g+0.02,'偶然正答 γ=1/N',fontsize=9,color=MUTE)
    ax.legend(fontsize=9,loc='lower right',frameon=False)
    for s in ['top','right']: ax.spines[s].set_visible(False)
    ax.text(46,0.03,'閾値 α',fontsize=9,color=INK); ax.grid(True,color=GRID,lw=0.6)
    save(fig,"fig_psycho.png")

# 図6 期待される再現
def f_recon():
    fig,ax=plt.subplots(figsize=(6.8,3.6)); fig.patch.set_facecolor('white')
    t=np.linspace(0,1,200)
    audio=1/(1+np.exp(-8*(t-0.55)))
    rng=np.random.default_rng(3); synth=np.clip(audio+0.03*np.sin(12*t)+rng.normal(0,0.012,t.size),0,1)
    ax.plot(t*100,audio,color=TEAL,lw=3,label='実測 f_audio_karuta(t)  (Kikiwake)')
    ax.plot(t*100,synth,color=INK,lw=1.8,ls='--',label='合成 f_visual_karuta(t)=F(g(音声))')
    ax.set_xlabel('読み上げの経過(系列の蓄積) %',fontsize=11,color=TEXT); ax.set_ylabel('識別率',fontsize=11,color=TEXT)
    ax.set_ylim(0,1.02); ax.legend(fontsize=9.5,loc='lower right',frameon=False)
    for s in ['top','right']: ax.spines[s].set_visible(False);
    ax.grid(True,color=GRID,lw=0.6)
    ax.text(5,0.9,'仮説: 合成が実測を良く再現する\n=インクルーシブ字幕の設計目標',fontsize=9.5,color=CORAL)
    save(fig,"fig_recon.png")

# 図5 MCD(音素クラス別)
def f_mcd():
    r=json.load(open(f"{NEW}/acoustic_analysis/mcd_divergence_result.json"))
    pc=r.get('per_class',{}); items=[(k,v['mean']) for k,v in pc.items()] if pc else []
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

# 図4 提示法(fade/blur/moya/morph) 中間フレーム
def f_algos():
    S=200; base=lambda ch: np.asarray(Image.open(f"{NEW}/experiment/base/{ch}.png").convert('L').resize((S,S))).astype(float)
    a=base('あ'); files=[f for f in os.listdir(f"{NEW}/experiment/base") if f.endswith('.png')][:78]
    avg=np.mean([np.asarray(Image.open(f"{NEW}/experiment/base/{f}").convert('L').resize((S,S))).astype(float) for f in files],0)
    u=0.5
    fade=255-(255-a)*u
    blur=np.asarray(Image.fromarray(a.astype('uint8')).filter(ImageFilter.GaussianBlur((1-u)*10))).astype(float)
    moya=avg*(1-u)+a*u
    # morph あ->き (SDF)
    def sdf(im): ink=im<128; return distance_transform_edt(~ink)-distance_transform_edt(ink)
    k=base('き'); s=(1-u)*sdf(a)+u*sdf(k); cov=np.clip(0.5-s/1.4,0,1); morph=255*(1-cov)
    imgs=[('fade(=コントラスト)',fade),('blur(=ぼかし)',blur),('moya(新規)',moya),('morph(新規)',morph)]
    fig,axes=plt.subplots(1,4,figsize=(9,2.7)); fig.patch.set_facecolor('white')
    for ax,(t,im) in zip(axes,imgs):
        ax.imshow(np.clip(im,0,255),cmap='gray',vmin=0,vmax=255); ax.set_title(t,fontsize=10.5,color=INK); ax.axis('off')
    fig.text(0.5,0.02,'各提示の中間(u=0.5)。刺激の強さ(1/f逸脱・動き)で事前選別し,強いものは本実験前に除外',ha='center',fontsize=8.5,color=MUTE)
    save(fig,"fig_algos.png")

for fn in [f_model,f_matrix,f_psycho,f_recon,f_mcd,f_algos]:
    try: fn()
    except Exception as e: print("ERR",fn.__name__,e)
print("figs in",OUT)
