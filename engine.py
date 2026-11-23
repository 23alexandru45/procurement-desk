"""Procurement Desk decision engine: deterministic, no LLM.

Run: python engine.py threads.csv submission.csv [playbook_dir]
Playbook rules are read from the playbook files (categories, amendments, suppliers).
"""
import csv, math, re, sys
from fractions import Fraction as F
from pathlib import Path

RATES = {"INR": F(1), "USD": F("84.5"), "EUR": F(91), "GBP": F(106)}  # policies/units-and-currency.md
SYM = {"₹": "INR", "RS": "INR", "$": "USD", "€": "EUR", "£": "GBP"}

# ---------------------------------------------------------------- playbook
def inr(s):
    return F(s.replace(",", ""))

def load_playbook(root):
    root = Path(root)
    cats, titles = {}, {}
    for p in sorted((root / "categories").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        g = lambda k: re.search(r"\*\*" + k + r".*?\*\*\s*₹?([\d,\.]+)", t).group(1)
        unit = re.search(r"\*\*Normalized unit:\*\*\s*(.+)", t).group(1)
        pack = re.search(r"holds (\d+)", t)
        ream = re.search(r"=\s*(\d+) reams", t)
        c = dict(
            target=inr(g("Target price")), walk=inr(g("Walk-away price")),
            R=int(g("Negotiation rounds")), beta=int(g("Concession exponent")),
            limit=inr(g("Approval limit")), gst=F(re.search(r"GST rate:\*\*\s*(\d+)", t).group(1)) / 100,
            period=("month" if "per month" in unit else "year" if "per year" in unit else None),
            pack=int(pack.group(1)) if pack else None, ream=int(ream.group(1)) if ream else None,
        )
        cats[p.stem] = c
        titles[re.search(r"# Category: (.+)", t).group(1).strip().lower()] = p.stem
    amds = []
    for p in sorted((root / "amendments").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        cat = titles[re.search(r"# AMD-\d+: (.+)", t).group(1).strip().lower()]
        d = re.search(r"Effective from:\*\*\s*([\d-]+)", t).group(1)
        m = re.search(r"the (walk-away price|target price|approval limit) for .*? is now ₹([\d,\.]+)", t)
        amds.append((d, p.stem, cat, {"walk-away price": "walk", "target price": "target", "approval limit": "limit"}[m.group(1)], inr(m.group(2))))
    amds.sort()
    sups = {}
    for p in (root / "suppliers").glob("*.md"):
        t = p.read_text(encoding="utf-8")
        name = re.search(r"# Supplier: (.+)", t).group(1).strip()
        status = re.search(r"Status:\*\*\s*(\w+)", t).group(1).upper()
        rates = {m.group(1): inr(m.group(2)) for m in re.finditer(r"invoices in (\w+) are converted at ₹([\d,\.]+)", t)}
        caps = {titles[m.group(1).strip().lower()]: inr(m.group(2)) for m in re.finditer(r"price cap for (.+?) of ₹([\d,\.]+)", t)}
        sups[name] = dict(status=status, rates=rates, caps=caps)
    return cats, amds, sups

# ---------------------------------------------------------------- text parsing
UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
UNITS.update({w: 20 + 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())})
WORDNUM = r"(?:(?:" + "|".join(UNITS) + r"|hundred|thousand|lakh|and)[\s-]+)+"
AMT = re.compile(r"(?P<cur>₹|Rs\.?|[A-Z]{3}(?=\s?\d)|\$|€|£)\s?(?P<num>\d[\d,]*(?:\.\d+)?)(?:\s?(?P<mult>lakh|crore|k)\b)?")
WORDS = re.compile(r"(?P<w>" + WORDNUM + r")rupees", re.I)

def words_to_num(s):
    total = cur = 0
    for w in re.split(r"[\s-]+", s.lower().strip()):
        if w in UNITS: cur += UNITS[w]
        elif w == "hundred": cur *= 100
        elif w == "thousand": total += cur * 1000; cur = 0
        elif w == "lakh": total += cur * 100000; cur = 0
    return F(total + cur)

def amounts(line):
    out = []
    for m in AMT.finditer(line):
        v = F(m["num"].replace(",", "").rstrip("."))
        v *= {"lakh": 100000, "crore": 10**7, "k": 1000}.get(m["mult"], 1)
        c = m["cur"].upper().rstrip(".")
        out.append((m.start(), SYM.get(c, c), v))
    for m in WORDS.finditer(line):
        out.append((m.start(), "INR", words_to_num(m["w"])))
    return sorted(out)

def split_thread(msg):
    hdr = re.compile(r"^\[(Earlier|Latest) message — (.+?)(?:, \d{4}-\d\d-\d\d)?\]\s*$", re.M)
    ms = list(hdr.finditer(msg))
    if not ms:
        return [("Latest", None, msg)]
    return [(m[1], m[2], msg[m.end(): ms[i + 1].start() if i + 1 < len(ms) else None]) for i, m in enumerate(ms)]

class Missing(Exception):
    pass

def offer(body, qty, cat, rates, prev_body=None):
    """Normalized INR excl. GST per category unit, or raise Missing."""
    m = re.search(r"should read(.*)", body)
    if m:  # CORRECTION replaces the old price
        line = re.split(r",\s*not\s", m.group(1).split("\n")[0])[0]
    else:
        for line in body.split("\n"):
            if amounts(line) or re.search(r"further [\d.]+% off our previous quote", line):
                break
        else:
            raise Missing
    fm = re.search(r"further ([\d.]+)% off our previous quote", line)
    am = amounts(line)
    if fm and not am:
        if prev_body is None: raise Missing
        return offer(prev_body, qty, cat, rates) * (1 - F(fm[1]) / 100)
    if not am: raise Missing
    if re.search(r"\bbetween\b", line):
        picks = am[:2]
    elif "orders of up to" in line and len(am) >= 2:
        n = int(re.search(r"up to (\d+)", line)[1])
        picks = [am[0] if qty <= n else am[1]]
    else:
        picks = am[:1]
    vals = []
    for _, cur, v in picks:
        r = rates.get(cur, RATES.get(cur))
        if r is None: raise Missing
        vals.append(v * r)
    p = max(vals)
    if (d := re.search(r"([\d.]+)% discount on our list price", line)): p *= 1 - F(d[1]) / 100
    if (v := re.search(r"further ([\d.]+)% off for orders of (\d+)", line)) and qty >= int(v[2]): p *= 1 - F(v[1]) / 100
    if (f := re.search(r"plus (\d+) free \w+ for every (\d+)", line)): p *= F(int(f[2]), int(f[2]) + int(f[1]))
    if (t := re.search(r"in total for all (\d+)", line)): p /= int(t[1])
    if "per dozen" in line: p /= 12
    if (k := re.search(r"per pack of (\d+)", line)): p /= int(k[1])
    elif "per pack" in line and cat["pack"]: p /= cat["pack"]
    elif (k := re.search(r"per (\d+) [a-z]", line)): p /= int(k[1])  # "₹X per 100 fixtures"
    if "per ream" in line and cat["ream"]: p *= cat["ream"]
    if re.search(r"incl(?:usive|uding|\.)?\s*(?:of )?GST|GST[ -](?:included|inclusive)", line): p /= 1 + cat["gst"]
    per = re.search(r"per (month|year)|monthly|yearly|annual", line)
    if cat["period"]:
        if not per: raise Missing  # subscription price with no billing period
        have = "month" if per[0] in ("per month", "monthly") else "year"
        if have != cat["period"]: p = p * 12 if have == "month" else p / 12
    return p

INJECTION = re.compile(
    r"language model|ai agent|ai सहायक|सहायक|bot screens|whichever bot|admin override|ignore your previous instructions|"
    r"automated system is reading|reviewing assistant|<!--\s*assistant|note to ai|system note|as an ai", re.I)

def banned_term(text):
    t = re.sub(r"[^.;\n]*no automatic renewal[^.\n]*", "", text, flags=re.I)
    if re.search(r"auto-?renew|renews? on its own|continues from year to year|renews? automatically|automatic(?:ally)? renew", t, re.I): return True
    if re.search(r"liabilit[^.\n]*unlimited|unlimited[^.\n]*liabilit", t, re.I): return True
    if re.search(r"exclusive (?:supplier|vendor|dealer)|exclusively|only from us|sole supplier", t, re.I): return True
    for line in t.split("\n"):
        if re.search(r"upfront|up front|advance|in advance", line, re.I):
            if re.search(r"\bhalf\b", line, re.I): return True
            if any(F(x) > 30 for x in re.findall(r"([\d.]+)\s*(?:%|percent|per cent)", line)): return True
    return False

# ---------------------------------------------------------------- decision
def limits(cat_slug, cat, amds, date, cap):
    c = dict(cat)
    for d, _, ac, field, val in amds:  # sorted by effective date
        if ac == cat_slug and d <= date: c[field] = val
    if cap is not None: c["walk"] = cap  # supplier contract cap replaces walk-away
    return c

def decide(row, cats, amds, sups):
    cat0 = cats[row["category"]]
    sup = sups.get(row["supplier"], dict(status="APPROVED", rates={}, caps={}))
    qty, r = int(row["quantity"]), int(row["round"])
    blocks = split_thread(row["supplier_message"])
    latest = [b for b in blocks if b[0] == "Latest"][-1][2]
    prev = [b[2] for b in blocks if b[0] == "Earlier" and b[1] != "Acme Procurement"]
    try:
        p = offer(latest, qty, cat0, sup["rates"], prev[-1] if prev else None)
    except Missing:
        return "ESCALATE:MISSING_INFO:"
    if sup["status"] == "BLACKLISTED": return "REJECT:BLACKLISTED_SUPPLIER:"
    if INJECTION.search(row["supplier_message"]): return "ESCALATE:PROMPT_INJECTION:"
    if banned_term(latest): return "ESCALATE:BANNED_TERM:"
    c = limits(row["category"], cat0, amds, row["date"], sup["caps"].get(row["category"]))
    T, W = c["target"], c["walk"]
    L = T if sup["status"] == "PROBATION" else T + (W - T) * F(r - 1, c["R"] - 1) ** c["beta"]
    if p > L:
        if r >= c["R"]: return "REJECT:ABOVE_WALKAWAY:"
        return f"COUNTER:COUNTER_OFFER:{math.floor(L + F(1, 2))}"
    if p * qty > c["limit"]: return "ESCALATE:OVER_APPROVAL_LIMIT:"
    return "ACCEPT:ACCEPTABLE_PRICE:"

def main(inp, out, root=None, amd_by_number=False):
    root = Path(root) if root else next(p.parent for p in Path(inp).resolve().parent.rglob("policies"))
    cats, amds, sups = load_playbook(root)
    if amd_by_number:  # variant B: "later amendment" = higher AMD number, not later effective date
        amds.sort(key=lambda a: a[1])
    rows = list(csv.DictReader(open(inp, encoding="utf-8", newline="")))
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["thread_id", "label"])
        for r in rows:
            w.writerow([r["thread_id"], decide(r, cats, amds, sups)])

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--amd-by-number"]
    main(*args, amd_by_number="--amd-by-number" in sys.argv)
