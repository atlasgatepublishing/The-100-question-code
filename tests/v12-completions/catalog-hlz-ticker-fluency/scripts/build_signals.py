#!/usr/bin/env python3
"""CONSTRUCTED ticker-fluency score — CONSTRUCTION-SPEC.md.
Score: +2 if ticker is an English word (system dictionary), +1 if
pronounceable (has a vowel, no 3+ consonant cluster, vowel share
0.2-0.65), minus 0.1 per letter beyond 3. Static per ticker."""
import json, os
FAM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
W04=os.path.join(FAM,'..','..','v11-native-rules','_w04_broad_data')
cand={int(k):v for k,v in json.load(open(os.path.join(W04,'candidates.json'))).items()}
words=set()
for p in ('/usr/share/dict/words','/usr/share/dict/american-english'):
    if os.path.exists(p):
        words={w.strip().upper() for w in open(p,errors='ignore')}; break
print('dict words',len(words))
V=set('AEIOU')
def score(t):
    t=''.join(ch for ch in t.upper() if ch.isalpha())
    if not t: return -9
    sc=0.0
    if t in words: sc+=2.0
    vow=sum(1 for ch in t if ch in V); share=vow/len(t) if t else 0
    cluster=False; run=0
    for ch in t:
        run=run+1 if ch not in V else 0
        if run>=3: cluster=True
    if vow>=1 and not cluster and 0.2<=share<=0.65: sc+=1.0
    sc-=0.1*max(0,len(t)-3)
    return round(sc,3)
vals={}
for cik,info in cand.items():
    vals[str(cik)]=score(info['ticker'])
signals={'TickerFluency':{'dir':'high','values':{str(F):dict(vals) for F in range(2016,2026)}}}
json.dump({'signals':signals},open(os.path.join(FAM,'signals.json'),'w'))
import collections
print(collections.Counter(vals.values()))
print('saved')
