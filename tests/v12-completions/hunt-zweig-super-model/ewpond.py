def ew_pond_weekly():
    """Equal-weight pond weekly-close index (CONSTRUCTED fallback signal series
    for the Value Line Geometric Index, frozen in the Zweig specs): chained
    weekly returns = mean of available pond names' weekly returns each week.
    Returns [(week_close_date, index_value)]."""
    weekly = {}  # sym -> {weekkey: (date, close)}
    for sym in pond_symbols() + ["SPY"]:
        try: bars = load_stock(sym)
        except Exception: continue
        wk = {}
        for b in bars:
            y, m, dd = map(int, b["d"].split("-"))
            key = date(y, m, dd).isocalendar()[:2]
            wk[key] = (b["d"], b["c"])
        weekly[sym] = wk
    all_keys = sorted({k for wk in weekly.values() for k in wk})
    series = []
    idx_val = 100.0
    prev = {}
    for k in all_keys:
        rets = []
        wk_date = None
        for sym, wk in weekly.items():
            if k in wk:
                d, c = wk[k]
                wk_date = max(wk_date, d) if wk_date else d
                if sym in prev and prev[sym] > 0:
                    rets.append(c / prev[sym] - 1.0)
                prev[sym] = c
        if rets:
            idx_val *= (1.0 + statistics.mean(rets))
            series.append((wk_date, idx_val))
    return series

def four_percent_states(weekly_series):
    """Zweig Four Percent Model state machine on a weekly close series.
    Returns (targets {week_close_date: state}, events). State starts OUT with
    the low-water mark at the first close; buy when a weekly close rises
    >= +4% from the low-water mark since the sell state began; sell when a
    weekly close falls >= -4% from the high-water mark since the buy."""
    targets = {}
    events = []
    state = 0
    lo = hi = weekly_series[0][1]
    for d, v in weekly_series:
        if state == 0:
            lo = min(lo, v)
            if v >= lo * 1.04:
                state = 1; hi = v
                events.append([d, "BUY", round(v, 2)])
        else:
            hi = max(hi, v)
            if v <= hi * 0.96:
                state = 0; lo = v
                events.append([d, "SELL", round(v, 2)])
        targets[d] = state
    return targets, events

def weekly_series_of(bars):
    wk = {}
    for b in bars:
        y, m, dd = map(int, b["d"].split("-"))
        key = date(y, m, dd).isocalendar()[:2]
        wk[key] = (b["d"], b["c"])
    return [wk[k] for k in sorted(wk)]


