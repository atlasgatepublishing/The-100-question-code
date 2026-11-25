import run_canslim as rc, lr_common as lr, collections
cnt = collections.Counter()
spy = rc.Series(rc.load_bars('SPY'))
sample_days, seen = [], set()
for d in spy.dates:
    if d[:7] not in seen and '2010' <= d[:4] <= '2026':
        seen.add(d[:7]); sample_days.append(d)
for t in lr.POOL:
    f = rc.load_facts_for(t)
    if f is None: continue
    fu = rc.Fund(f)
    for d in sample_days:
        cnt['eval'] += 1
        c = fu.c_pass(d); a = fu.a_pass(d)
        if c: cnt['c'] += 1
        if a: cnt['a'] += 1
        if c and a: cnt['c&a'] += 1
    del fu, f
print(cnt)
print('C %.1f%% A %.1f%% C&A %.2f%%' % (100*cnt['c']/cnt['eval'], 100*cnt['a']/cnt['eval'], 100*cnt['c&a']/cnt['eval']))
