#!/usr/bin/env python3
"""Tier-2 GP extraction (lean): each 10-K R-file prints 3 fiscal years, so
5 filings per name cover FY2012-FY2025. As-filed statement tables (SEC
R-files) for extension-tag filer-years. Output data/tier2_gp.json."""
import json, urllib.request, gzip, re, time, os, sys
HERE=os.path.dirname(os.path.abspath(__file__))
hdr={"User-Agent":"AtlasGate research contact@example.com"}
def get(url):
    req=urllib.request.Request(url,headers=hdr)
    with urllib.request.urlopen(req,timeout=25) as r: data=r.read()
    if data[:2]==b"\x1f\x8b": data=gzip.decompress(data)
    return data
def rows_of(html):
    rows=[]
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S|re.I):
        cells=re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S|re.I)
        cells=[re.sub(r"<[^>]+>","",c).replace("&#160;"," ").replace("&nbsp;"," ").replace("&amp;","&").strip() for c in cells]
        cells=[re.sub(r"\s+"," ",c) for c in cells]
        if any(cells): rows.append(cells)
    return rows
def num(s):
    s=s.replace("$","").replace(",","").strip()
    if not s or s in ("-","\u2014"): return None
    neg=s.startswith("(") and s.endswith(")")
    s=s.strip("()")
    try: v=float(s)
    except ValueError: return None
    return -v if neg else v
MONTHS={"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
def parse_coldate(s):
    m=re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if not m: return None
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
def income_rfile(cik, acc_nodash):
    fs=get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/FilingSummary.xml").decode("utf-8","ignore")
    for m in re.finditer(r"<Report[^>]*>(.*?)</Report>", fs, re.S):
        blk=m.group(1)
        name=re.search(r"<ShortName>(.*?)</ShortName>", blk)
        hf=re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", blk)
        if not name or not hf: continue
        n=name.group(1)
        if re.search(r"(Statement|Statements) Of (Income|Operations|Earnings)", n, re.I) and not re.search(r"Comprehensive|Parenthetical", n, re.I):
            return hf.group(1)
    return None
CFG={
 "XOM": dict(cik=34088, rev=["Total revenues and other income","Total revenues"], cogs=["Crude oil and product purchases","Production and manufacturing expenses"]),
 "DIS": dict(cik=1744489, rev=["Total revenues","Total revenues and other income"], cogs=["Cost of services","Cost of products"]),
 "VZ":  dict(cik=732712, rev=["Total operating revenues"], cogs=["Cost of services","Cost of equipment"]),
 "T":   dict(cik=732717, rev=["Total revenues","Total operating revenues"], cogs=["Cost of services and support","Cost of equipment"]),
 "GE":  dict(cik=40545, rev=["Total revenues and other income","Total revenues"], cogs=["Cost of goods sold","Cost of services sold"]),
 "CVX": dict(cik=93410, rev=["Total revenues and other income"], cogs=["Purchased crude oil and products","Operating expenses"]),
}
def pick_10ks(cik):
    sub=json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
    rec=sub["filings"]["recent"]
    ks=[]
    for i in range(len(rec["form"])):
        if rec["form"][i]=="10-K" and rec["filingDate"][i]>="2014-01-01":
            ks.append((rec["accessionNumber"][i], rec["filingDate"][i], rec["reportDate"][i]))
    ks.sort(key=lambda x: x[1])
    return ks
def extract(ticker):
    cfg=CFG[ticker]; cik=cfg["cik"]; found={}
    for acc, filed, rd in pick_10ks(cik):
        try:
            rf=income_rfile(cik, acc.replace("-",""))
            if not rf: print(ticker, rd, "no R file", flush=True); continue
            html=get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-','')}/{rf}").decode("utf-8","ignore")
        except Exception as e:
            print(ticker, rd, "FETCH FAIL", e, flush=True); continue
        rows=rows_of(html)
        hdr_idx=None; coldates=[]
        for i,r in enumerate(rows[:12]):
            ds=[parse_coldate(c) for c in r if parse_coldate(c)]
            if len(ds)>=2: hdr_idx=i; coldates=ds; break
        if hdr_idx is None: print(ticker, rd, "no header", flush=True); continue
        ncol=len(coldates)
        def grab(labels):
            for r in rows:
                if r[0].strip().lower() in [w.lower() for w in labels]:
                    vals=[num(c) for c in r[1:] if c!=""]
                    if len(vals)>=ncol: return vals[:ncol]
            return None
        rev=grab(cfg["rev"]); parts=[]; ok=rev is not None
        if ok:
            for cl in cfg["cogs"]:
                v=grab([cl])
                if v is None: ok=False; break
                parts.append(v)
        if not ok: print(ticker, rd, "labels missing", flush=True); continue
        for j,pend in enumerate(coldates):
            if rev[j] is None or any(p[j] is None for p in parts): continue
            rec={"filed":filed,"period_end":pend,"revenue":rev[j]*1e6,
                 "cogs":sum(p[j] for p in parts)*1e6,"accn":acc,"labels":cfg["cogs"]}
            if pend not in found or filed < found[pend]["filed"]:
                found[pend]=rec
        print(ticker, rd, "ok ->", sorted(found)[-3:], flush=True)
        time.sleep(0.2)
    return sorted(found.values(), key=lambda r: r["period_end"])
if __name__=="__main__":
    names=sys.argv[1:] or list(CFG)
    out={}
    if os.path.exists(os.path.join(HERE,"data","tier2_gp.json")):
        out=json.load(open(os.path.join(HERE,"data","tier2_gp.json")))
    for t in names:
        out[t]=extract(t)
        json.dump(out, open(os.path.join(HERE,"data","tier2_gp.json"),"w"), indent=1)
        print(t, "SAVED", [(r["period_end"][:4], r["filed"]) for r in out[t]], flush=True)
