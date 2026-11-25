import importlib.util, os, json
HERE=os.path.dirname(os.path.abspath(__file__))
spec=importlib.util.spec_from_file_location("rt", os.path.join(HERE,"run_twosleeve_constructed.py"))
R=importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
R.D=R.Data(); del R.D.px[1748790]
out={}
for name,(s,e,f) in {"FULL":("2017-01","2026-09","2026-10"),"CONTs":("2019-01","2026-09","2026-10"),"VALs":("2023-01","2026-09","2026-10")}.items():
    twins=[]
    for seed in range(1,21):
        tr=R.run_window(s,e,f,seed=seed); twins.append(tr["final"]); print(name,seed,tr["final"],flush=True)
    out[name]=twins
d=json.load(open(os.path.join(HERE,"diagnostic.json")))
ranked={k:v["final"] for k,v in d["diagnostic_windows"].items()}
for k,tw in out.items():
    d["diagnostic_windows"][k]["placebo_finals"]=tw
    d["diagnostic_windows"][k]["placebos_beaten"]=sum(1 for t in tw if ranked[k]>t)
json.dump(d, open(os.path.join(HERE,"diagnostic.json"),"w"), indent=1)
print({k:(ranked[k], sum(1 for t in v if ranked[k]>t), sorted(v)[10]) for k,v in out.items()})
