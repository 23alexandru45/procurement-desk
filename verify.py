"""Independent re-implementation of the Acme playbook, used only to cross-check engine.py.

Usage: python verify.py data/threads.csv verify_labels.csv
"""
import csv
import re
import sys

CAT = {  # unit noun, period (None = not a subscription), gst, target, walkaway, R, beta, limit
    "catering": ("meal", None, .05, 280, 340, 3, 1, 600000),
    "cleaning": ("site", "month", .18, 85000, 100000, 4, 2, 900000),
    "cloud-servers": ("server", "year", .18, 96000, 115000, 5, 3, 6000000),
    "courier": ("shipment", None, .18, 160, 200, 4, 2, 500000),
    "crm-licenses": ("seat", "year", .18, 18000, 22000, 4, 2, 2500000),
    "design-software": ("seat", "year", .18, 30000, 36000, 4, 2, 1500000),
    "headsets": ("headset", None, .18, 3500, 4200, 3, 1, 400000),
    "laptops": ("laptop", None, .18, 62000, 70000, 4, 2, 4000000),
    "led-lighting": ("fixture", None, .18, 1800, 2200, 3, 1, 350000),
    "mobile-phones": ("phone", None, .18, 24000, 28000, 4, 2, 2000000),
    "monitors": ("monitor", None, .18, 14000, 16500, 3, 1, 1200000),
    "office-chairs": ("chair", None, .18, 9000, 11000, 3, 1, 700000),
    "printer-paper": ("box", None, .12, 2200, 2600, 3, 1, 250000),
    "security-guards": ("guard", "month", .18, 21000, 25000, 4, 2, 1000000),
    "training": ("participant", None, .18, 6000, 7500, 3, 1, 900000),
}
# (effective date, category, field, value)
AMD = [
    ("2026-09-22", "courier", "walkaway", 210),
    ("2026-11-11", "cloud-servers", "walkaway", 119990),
    ("2026-11-25", "mobile-phones", "walkaway", 29780),
    ("2026-09-20", "catering", "target", 270),
    ("2026-11-06", "printer-paper", "walkaway", 2780),
    ("2026-11-09", "headsets", "limit", 320000),
    ("2026-12-05", "led-lighting", "walkaway", 2360),
    ("2026-12-04", "led-lighting", "walkaway", 2330),
    ("2026-12-14", "monitors", "limit", 960000),
]
BLACK = {"GreenLeaf Facility Care", "Lumen Workspace", "Orbit Electronics"}
PROBATION = {"Banyan Guarding", "Jade Express", "Vertex Mobile", "Zephyr SaaS"}
CAPS = {("Helix CRM", "catering"): 400, ("Ivory Events Catering", "headsets"): 4400,
        ("Jupiter Devices", "monitors"): 17600, ("Kite Electricals", "office-chairs"): 11400,
        ("Monsoon Foods", "headsets"): 4500, ("Xenon Displays", "led-lighting"): 2300}
FX = {"USD": 84.5, "EUR": 91, "GBP": 106}
FX_CONTRACT = {("Arvind Office Supplies", "GBP"): 104.5, ("Aster Cleaning Co", "USD"): 84,
               ("Falcon Security Services", "GBP"): 105.5, ("Kestrel Learning", "EUR"): 90.5}

ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                      "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
SCALE = {"thousand": 1000, "lakh": 100000, "crore": 10000000}


def words_num(s):
    total, cur = 0, 0
    for w in re.split(r"[\s-]+", s.lower()):
        if w in ONES: cur += ONES[w]
        elif w in TENS: cur += TENS[w]
        elif w == "hundred": cur *= 100
        elif w in SCALE: total += cur * SCALE[w]; cur = 0
        elif w == "and": pass
        else: raise ValueError(w)
    return total + cur


CUR = r"(₹|Rs\.?|INR|USD|EUR|GBP|\$|€|£|[A-Z]{3})"
AMT = re.compile(CUR + r"\s?(\d[\d,]*(?:\.\d+)?)(k)?")
WORDNUM = r"((?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakh|crore|and)[\s-]*)+)rupees"
SYM = {"₹": "INR", "Rs.": "INR", "Rs": "INR", "$": "USD", "€": "EUR", "£": "GBP"}


class Missing(Exception):
    pass


def amounts(line, supplier):
    """All money amounts in a line, converted to INR, in order of appearance."""
    out = []
    for m in AMT.finditer(line):
        cur = SYM.get(m.group(1), m.group(1))
        v = float(m.group(2).replace(",", "")) * (1000 if m.group(3) else 1)
        if cur != "INR":
            rate = FX_CONTRACT.get((supplier, cur), FX.get(cur))
            if rate is None:
                raise Missing(cur)
            v *= rate
        out.append((m.start(), v))
    for m in re.finditer(WORDNUM, line):
        out.append((m.start(), float(words_num(m.group(1).strip()))))
    return [v for _, v in sorted(out)]


def price_line(lines):
    for l in lines:
        if AMT.search(l) or re.search(WORDNUM, l) or "previous quote" in l:
            if re.match(r"\s*(Payment terms|A \d+% upfront|\d+% advance|We need)", l):
                continue
            return l
    return None


def normalize(line, cat, qty, supplier, prev):
    unit, period, gst = CAT[cat][0], CAT[cat][1], CAT[cat][2]
    m = re.search(r"a further (\d+(?:\.\d+)?)% off our previous quote", line)
    if m:
        if prev is None:
            raise Missing("no previous quote")
        return prev * (1 - float(m.group(1)) / 100)
    a = amounts(line, supplier)
    if not a:
        raise Missing("no number")
    if "CORRECTION" in line:
        p = a[0]  # "should read X, not Y"
    elif "between" in line:
        p = max(a[0], a[1])
    elif re.search(r"discount on our list price", line):
        d = float(re.search(r"(\d+(?:\.\d+)?)% discount", line).group(1))
        p = a[0] * (1 - d / 100)
    elif "for larger orders" in line:
        n = int(re.search(r"orders of up to (\d+)", line).group(1))
        p = a[0] if qty <= n else a[1]
    else:
        p = a[0]
    m = re.search(r"in total for all (\d+)", line)
    if m:
        p /= int(m.group(1))
    # unit conversions
    if re.search(r"per dozen", line): p /= 12
    m = re.search(r"per pack of (\d+)", line) or re.search(r"per (\d+) \w+", line)
    if m: p /= int(m.group(1))
    if re.search(r"per ream", line): p *= 10
    if re.search(r"GST\)|incl\. GST|including GST|inclusive of GST|GST included", line):
        p /= 1 + gst
    # billing period
    has = "month" if re.search(r"per month", line) else "year" if re.search(r"per year", line) else None
    if period:
        if has is None:
            raise Missing("no period")
        if has != period:
            p = p * 12 if period == "year" else p / 12
    # volume discount / free units
    m = re.search(r"a further (\d+(?:\.\d+)?)% off for orders of (\d+)", line)
    if m and qty >= int(m.group(2)):
        p *= 1 - float(m.group(1)) / 100
    m = re.search(r"plus (\d+) free \w+ for every (\d+) you pay for", line)
    if m:
        f, n = int(m.group(1)), int(m.group(2))
        p = p * n / (n + f)
    return p


INJ = re.compile(r"language model|\bAI AGENT\b|\bbot\b|admin override|<!--|automated system is reading|"
                 r"Ignore your previous instructions|reviewing assistant|AI सहायक", re.I)
BANNED = re.compile(r"auto-renew|renews on its own|from year to year|year to year unless|"
                    r"unlimited|exclusive supplier|only from us|half the order value upfront", re.I)


def advance_over_30(text):
    for m in re.finditer(r"(\d+)% (?:advance|upfront)|(\d+)% of the order value upfront|A (\d+)% upfront", text):
        v = int(next(g for g in m.groups() if g))
        if v > 30:
            return True
    return False


def split(msg):
    """Return (earlier supplier sections [list of lines], latest section lines)."""
    parts = re.split(r"^\[(Earlier|Latest) message — ([^\]]*)\]\s*$", msg, flags=re.M)
    if len(parts) == 1:
        return [], msg.split("\n")
    earlier, latest = [], None
    for i in range(1, len(parts), 3):
        kind, who, body = parts[i], parts[i + 1], parts[i + 2]
        if kind == "Latest":
            latest = body.split("\n")
        elif not who.startswith("Acme"):
            earlier.append(body.split("\n"))
    return earlier, latest


def values(cat, d, supplier):
    _, _, _, T, W, R, beta, lim = CAT[cat]
    v = {"target": T, "walkaway": W, "limit": lim}
    for eff, c, f, val in sorted(AMD):
        if c == cat and eff <= d:
            v[f] = val
    if (supplier, cat) in CAPS:
        v["walkaway"] = CAPS[(supplier, cat)]
    return v["target"], v["walkaway"], R, beta, v["limit"]


def label(row):
    msg, sup, cat = row["supplier_message"], row["supplier"], row["category"]
    qty, r, d = int(row["quantity"]), int(row["round"]), row["date"]
    earlier, latest = split(msg)
    # 1 missing info
    try:
        prev = None
        for sec in earlier:  # most recent supplier quote
            pl = price_line(sec)
            if pl:
                try:
                    prev = normalize(pl, cat, qty, sup, prev)
                except Missing:
                    pass
        pl = price_line(latest)
        if pl is None:
            raise Missing("no price line")
        p = normalize(pl, cat, qty, sup, prev)
    except Missing:
        return "ESCALATE:MISSING_INFO:"
    if sup in BLACK:
        return "REJECT:BLACKLISTED_SUPPLIER:"
    if INJ.search(msg):
        return "ESCALATE:PROMPT_INJECTION:"
    last = "\n".join(latest)
    if BANNED.search(last) or advance_over_30(last):
        return "ESCALATE:BANNED_TERM:"
    T, W, R, beta, lim = values(cat, d, sup)
    L = T if sup in PROBATION else T + (W - T) * ((r - 1) / (R - 1)) ** beta
    if p > L:
        if r >= R:
            return "REJECT:ABOVE_WALKAWAY:"
        return f"COUNTER:COUNTER_OFFER:{int(L + 0.5)}"
    if p * qty > lim:
        return "ESCALATE:OVER_APPROVAL_LIMIT:"
    return "ACCEPT:ACCEPTABLE_PRICE:"


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["thread_id", "label"])
        for row in rows:
            w.writerow([row["thread_id"], label(row)])
