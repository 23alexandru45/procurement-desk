"""Reproduce every number claimed in README section 7.

Run: python check.py [data_dir]      (default data_dir = data)
Needs threads.csv, sample_threads.csv, sample_answers.csv and the playbook under data_dir.
"""
import csv, io, math, sys
from fractions import Fraction as F
from pathlib import Path

import engine, verify

data = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
root = next(p.parent for p in data.resolve().rglob("policies"))
cats, amds, sups = engine.load_playbook(root)
read = lambda p: list(csv.DictReader(open(p, encoding="utf-8", newline="")))
threads = read(data / "threads.csv")

# 1. sample: engine labels vs the official worked answers
sample = read(data / "sample_threads.csv")
answers = {r["thread_id"]: r["label"] for r in read(data / "sample_answers.csv")}
ok = sum(engine.decide(r, cats, amds, sups) == answers[r["thread_id"]] for r in sample)
print(f"sample answers matched: {ok}/{len(sample)}")

# 2. full run is byte-identical to the submitted file
buf = io.StringIO()
w = csv.writer(buf, lineterminator="\n")
w.writerow(["thread_id", "label"])
for r in threads:
    w.writerow([r["thread_id"], engine.decide(r, cats, amds, sups)])
same = buf.getvalue().encode("utf-8") == Path("submission.csv").read_bytes()
print(f"engine output identical to submission.csv: {same}")

# 3. the buyer's own previous counter in each thread equals L(r-1) from our schedule
def counter_check(amd_list):
    hit = tot = 0
    for r in threads:
        if not r["our_last_counter"].strip():
            continue
        sup = sups.get(r["supplier"], dict(status="APPROVED", rates={}, caps={}))
        c = engine.limits(r["category"], cats[r["category"]], amd_list, r["date"], sup["caps"].get(r["category"]))
        prev = int(r["round"]) - 1
        L = c["target"] if sup["status"] == "PROBATION" else c["target"] + (c["walk"] - c["target"]) * F(prev - 1, c["R"] - 1) ** c["beta"]
        tot += 1
        hit += math.floor(L + F(1, 2)) == F(r["our_last_counter"])
    return hit, tot

print("our_last_counter == L(r-1), amendments by effective date (used): %d/%d" % counter_check(amds))
print("our_last_counter == L(r-1), amendments by AMD number (variant B): %d/%d" % counter_check(sorted(amds, key=lambda a: a[1])))

# 4. second implementation (verify.py) agrees with the submission
sub = {r["thread_id"]: r["label"] for r in read("submission.csv")}
agree = sum(verify.label(r) == sub[r["thread_id"]] for r in threads)
print(f"verify.py agrees with submission.csv: {agree}/{len(threads)}")
