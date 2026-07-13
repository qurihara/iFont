#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# (4)提示速度の可変化・臨界SOA実験の想定結果版の図を生成する(paper/figs/ へ)。
# fig_dur_sat.png : 単文字の露出時間D→識別率カーブ(視覚・聴覚, 飽和)
# fig_interference.png : 干渉指標 I(S)=実測2文字精度−単文字合成予測 と臨界SOA(中心図)
import os, numpy as np
from matplotlib import font_manager as fm
FP='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'; fm.fontManager.addfont(FP)
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
plt.rcParams['font.family']=fm.FontProperties(fname=FP).get_name(); plt.rcParams['axes.unicode_minus']=False

OUT=os.path.dirname(os.path.abspath(__file__))+"/figs"; os.makedirs(OUT,exist_ok=True)
INK='#1E2A5E'; TEAL='#2E7D8F'; GOLD='#C8A44D'; CORAL='#C25B4E'; MUTE='#9AA0B4'; GRID='#E4E6EE'; TEXT='#22283C'
def save(fig,n): fig.savefig(f"{OUT}/{n}",dpi=200,facecolor='white',bbox_inches='tight'); plt.close(fig); print("saved",n)

GAMMA=1/72.0; D0=40.0
def fD(D,a,tau): D=np.asarray(D,float); return np.where(D>D0, GAMMA+(a-GAMMA)*(1-np.exp(-(D-D0)/tau)), GAMMA)
grid=np.array([100,150,200,300,450,700.0])
rng=np.random.default_rng(20260710)

# 図1: 露出時間→識別率(飽和)
def f_dur():
    fig,ax=plt.subplots(figsize=(6.6,3.9)); fig.patch.set_facecolor('white')
    x=np.linspace(60,700,300)
    for a,tau,c,lab,ds in [(0.92,85,INK,'視覚',236),(0.90,100,TEAL,'聴覚',270)]:
        ax.plot(x,fD(x,a,tau),color=c,lw=2.4,label=f'{lab}(τ={tau}ms, 90%到達≈{ds}ms)')
        pts=fD(grid,a,tau); se=np.sqrt(np.clip(pts*(1-pts),1e-3,None)/1000)
        ax.errorbar(grid,pts,yerr=1.96*se,fmt='o',color=c,ms=4.5,capsize=2,lw=1)
        ax.plot([ds,ds],[0,fD(ds,a,tau)],color=c,ls=':',lw=1)
        ax.axhline(a,color=c,ls='--',lw=0.7,alpha=0.5)
    ax.axhline(GAMMA,color=MUTE,lw=1,ls=':'); ax.text(70,GAMMA+0.02,'偶然正答 γ=1/72',fontsize=9,color=MUTE)
    ax.set_xlabel('露出時間 D (ms)',fontsize=11,color=TEXT); ax.set_ylabel('識別率',fontsize=11,color=TEXT)
    ax.set_ylim(0,1.0); ax.set_xlim(60,700); ax.legend(fontsize=9,loc='lower right',frameon=False)
    for s in ['top','right']: ax.spines[s].set_visible(False)
    ax.grid(True,color=GRID,lw=0.6)
    ax.text(300,0.25,'露出とともに上昇し\n約260msで飽和\n(=系列の合成予測 f(S) の土台)',fontsize=9,color=CORAL)
    save(fig,"fig_dur_sat.png")

# 図2: 干渉指標 I(S) と臨界SOA(中心図)
def f_interf():
    fig,ax=plt.subplots(figsize=(6.8,4.0)); fig.patch.set_facecolor('white')
    S=np.linspace(100,700,300)
    def I1(S,D,lam): return -D*np.exp(-(S-100)/lam)
    def I2(S,b,Sc,w):
        v=-b*np.exp(-((S-Sc)/w)**2); return np.maximum(v,-b)  # lag-1 sparing: 最短SOAで温存(谷はSc付近)
    # char1(上書きされる先頭・後方マスク型・単調回復)
    ax.plot(S,I1(S,0.30,110)*100,color=INK,lw=2.4,label='視覚 char1(上書きされる先頭)')
    ax.plot(S,I1(S,0.30,80)*100,color=TEAL,lw=2.4,label='聴覚 char1(先頭)')
    # char2(末尾・注意の瞬き型の浅い谷)
    ax.plot(S,I2(S,0.14,280,140)*100,color=INK,lw=1.4,ls='--',label='視覚 char2(末尾・注意の瞬き)')
    ax.axhspan(-2,2,color=MUTE,alpha=0.15); ax.text(560,0.6,'等価域 ±2%',fontsize=8.5,color=MUTE)
    ax.axhline(0,color='#333',lw=0.8)
    for sstar,c,lab in [(400,INK,'視覚 S*≈400ms'),(320,TEAL,'聴覚 S*≈320ms')]:
        ax.axvline(sstar,color=c,ls=':',lw=1.4); ax.text(sstar+4,-27,lab,fontsize=8.6,color=c,rotation=90,va='bottom')
    ax.set_xlabel('文字間 SOA (ms)',fontsize=11,color=TEXT)
    ax.set_ylabel('干渉指標 I(S) (%)',fontsize=11,color=TEXT)
    ax.set_title('I(S) = 実測の2文字精度 − 単文字合成予測',fontsize=10,color=TEXT,pad=8)
    ax.set_xlim(100,700); ax.set_ylim(-32,6); ax.legend(fontsize=8.6,loc='lower right',frameon=False)
    for s in ['top','right']: ax.spines[s].set_visible(False)
    ax.grid(True,color=GRID,lw=0.6)
    save(fig,"fig_interference.png")

if __name__=="__main__":
    f_dur(); f_interf()
    print("\n== 本文引用値 ==")
    for a,tau,lab in [(0.92,85,'視覚'),(0.90,100,'聴覚')]:
        ds=D0+tau*np.log(10); print(f"  {lab}: 90%到達 D_sat≈{ds:.0f}ms, 漸近 a={a}, グリッド f(D)=",{int(d):round(float(fD(d,a,tau)),2) for d in grid})
    for lab,lam in [('視覚',110),('聴覚',80)]:
        sstar=100+lam*np.log(0.30/0.02); print(f"  {lab} char1 臨界SOA S*={sstar:.0f}ms (|I1|<2%)")
