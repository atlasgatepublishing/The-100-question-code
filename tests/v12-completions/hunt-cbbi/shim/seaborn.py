"""Harness shim ONLY: vendored CBBI metric modules call seaborn lineplot
inside _calculate purely to draw charts. This no-op keeps the unmodified
vendored arithmetic identical while skipping chart rendering."""
def lineplot(*a, **k): return None
def scatterplot(*a, **k): return None
def color_palette(*a, **k): return []
def set_theme(*a, **k): pass
def set_style(*a, **k): pass
