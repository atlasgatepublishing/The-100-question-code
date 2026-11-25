import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
for slug in E.STRATS: E.main(slug)
print("ALL DONE", flush=True)
