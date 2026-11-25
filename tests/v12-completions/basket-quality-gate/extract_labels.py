import json, urllib.request, gzip, re, sys, time
hdr={"User-Agent":"AtlasGate research contact@example.com"}
def get(url):
    req=urllib.request.Request(url,headers=hdr)
    with urllib.request.urlopen(req,timeout=60) as r: data=r.read()
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
def income_rfile(cik, acc_nodash):
    fs=get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/FilingSummary.xml").decode("utf-8","ignore")
    best=None
    for m in re.finditer(r"<Report[^>]*>(.*?)</Report>", fs, re.S):
        blk=m.group(1)
        name=re.search(r"<ShortName>(.*?)</ShortName>", blk)
        hf=re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", blk)
        if not name or not hf: continue
        n=name.group(1)
        if re.search(r"(Statement|Statements) Of (Income|Operations|Earnings)", n) and "Comprehensive" not in n and "Parenthetical" not in n:
            best=hf.group(1); break
    return best
def latest_10k(cik):
    sub=json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
    rec=sub["filings"]["recent"]
    for i in range(len(rec["form"])):
        if rec["form"][i]=="10-K":
            return rec["accessionNumber"][i], rec["filingDate"][i], rec["reportDate"][i]
    return None
for name,cik in [("DIS",1744489),("VZ",732712),("T",732717),("GE",40545),("CVX",93410)]:
    acc,fd,rd=latest_10k(cik)
    rf=income_rfile(cik, acc.replace("-",""))
    print(f"\n=== {name} 10-K filed {fd} report {rd} R={rf}")
    html=get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-','')}/{rf}").decode("utf-8","ignore")
    for r in rows_of(html)[:45]:
        print(" | ".join(x for x in r if x))
    time.sleep(0.3)
