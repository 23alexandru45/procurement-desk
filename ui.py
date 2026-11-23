"""Local demo UI for the Procurement Desk engine (standard library only, no LLM).

Run: python ui.py [threads.csv] [playbook_dir]   then open http://127.0.0.1:8765
Pick a thread (or edit the fields / paste a new message) and press Decide. Labels come only from engine.decide().
"""
import csv, json, sys
from fractions import Fraction as F
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import engine

HERE = Path(__file__).resolve().parent
THREADS = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "data" / "threads.csv"
ROOT = Path(sys.argv[2]) if len(sys.argv) > 2 else next(p.parent for p in THREADS.resolve().parent.rglob("policies"))
CATS, AMDS, SUPS = engine.load_playbook(ROOT)
ROWS = list(csv.DictReader(open(THREADS, encoding="utf-8", newline="")))
BYID = {r["thread_id"]: r for r in ROWS}
SUB = HERE / "submission.csv"
SUBMITTED = {r["thread_id"]: r["label"] for r in csv.DictReader(open(SUB, encoding="utf-8"))} if SUB.exists() else {}

WHY = {
    "MISSING_INFO": "No usable price (or billing period) in the latest message: escalate.",
    "BLACKLISTED_SUPPLIER": "Supplier is blacklisted: reject.",
    "PROMPT_INJECTION": "Message tries to instruct the AI agent: escalate to a human.",
    "BANNED_TERM": "Latest message has a banned contract term (auto-renewal, unlimited liability, exclusivity, >30% advance): escalate.",
    "ABOVE_WALKAWAY": "Price is above the allowed level on the final round: reject.",
    "COUNTER_OFFER": "Price is above the allowed level L(r): counter at L(r).",
    "OVER_APPROVAL_LIMIT": "Price is fine but price x quantity exceeds the approval limit: escalate.",
    "ACCEPTABLE_PRICE": "Price is within L(r) and within the approval limit: accept.",
}


def run(row):
    label = engine.decide(row, CATS, AMDS, SUPS)
    action, reason, price = label.split(":")
    steps = []
    cat0, sup = CATS[row["category"]], SUPS.get(row["supplier"], dict(status="APPROVED", rates={}, caps={}))
    qty, r = int(row["quantity"]), int(row["round"])
    blocks = engine.split_thread(row["supplier_message"])
    latest = [b for b in blocks if b[0] == "Latest"][-1][2]
    prev = [b[2] for b in blocks if b[0] == "Earlier" and b[1] != "Acme Procurement"]
    try:
        p = engine.offer(latest, qty, cat0, sup["rates"], prev[-1] if prev else None)
        steps.append(f"Normalized offer: INR {float(p):,.2f} per {row['category']} unit, excl. GST")
    except engine.Missing:
        p = None
        steps.append("Normalized offer: none found")
    steps.append(f"Supplier status: {sup['status']}")
    c = engine.limits(row["category"], cat0, AMDS, row["date"], sup["caps"].get(row["category"]))
    T, W = c["target"], c["walk"]
    L = T if sup["status"] == "PROBATION" else T + (W - T) * F(r - 1, c["R"] - 1) ** c["beta"]
    steps.append(f"Round {r} of {c['R']}: target {float(T):,.0f}, walk-away {float(W):,.0f}, allowed L(r) = {float(L):,.2f}")
    if p is not None:
        steps.append(f"Order value: {float(p * qty):,.0f} vs approval limit {float(c['limit']):,.0f}")
    return dict(label=label, action=action, reason=reason, price=price, why=WHY[reason], steps=steps)


PAGE = r"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Procurement Desk</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1b1f24;--mut:#667;--line:#dde1e6;--acc:#1f5fbf}
@media(prefers-color-scheme:dark){:root{--bg:#14171b;--card:#1d2127;--ink:#e8eaed;--mut:#9aa;--line:#2f353d;--acc:#6aa5ff}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px system-ui,sans-serif;padding:20px}
main{max-width:1000px;margin:auto;display:grid;gap:16px;grid-template-columns:1fr 1fr}
@media(max-width:800px){main{grid-template-columns:1fr}}
h1{grid-column:1/-1;margin:0;font-size:22px}h1 small{color:var(--mut);font-weight:400;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
label{display:block;font-size:12px;color:var(--mut);margin:10px 0 3px}
input,select,textarea{width:100%;box-sizing:border-box;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:7px;font:inherit}
textarea{height:230px;font:13px ui-monospace,monospace}
.row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
button{margin-top:14px;background:var(--acc);color:#fff;border:0;border-radius:6px;padding:10px 18px;font:600 15px system-ui;cursor:pointer}
.act{font-size:28px;font-weight:700}.ACCEPT{color:#1a8a3c}.COUNTER{color:#b8730a}.REJECT{color:#c62828}.ESCALATE{color:#7b3fc4}
.lab{font:14px ui-monospace,monospace;background:var(--bg);padding:6px 8px;border-radius:6px;display:inline-block;margin:6px 0}
ul{padding-left:18px;margin:8px 0}li{margin:4px 0}.mut{color:var(--mut);font-size:13px}
</style>
<main>
<h1>Procurement Desk <small>rule-based agent, no LLM &middot; team robotech.ai</small></h1>
<section class=card>
<label>Load thread</label><select id=tid></select>
<div class=row><div><label>Supplier</label><input id=supplier></div><div><label>Category</label><input id=category></div><div><label>Date</label><input id=date></div></div>
<div class=row><div><label>Quantity</label><input id=quantity></div><div><label>Round</label><input id=round></div><div></div></div>
<label>Supplier message</label><textarea id=msg></textarea>
<button id=go>Decide</button>
</section>
<section class=card id=out><div class=mut>Choose a thread and press Decide.</div></section>
</main>
<script>
const $=i=>document.getElementById(i),F=["supplier","category","date","quantity","round"];
async function j(u,o){return (await fetch(u,o)).json()}
function esc(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
async function load(){const t=await j("/api/thread?id="+$("tid").value);F.forEach(f=>$(f).value=t[f]);$("msg").value=t.supplier_message;go()}
async function go(){
  const b={thread_id:$("tid").value};F.forEach(f=>b[f]=$(f).value);b.supplier_message=$("msg").value;
  const r=await j("/api/decide",{method:"POST",body:JSON.stringify(b)});
  if(r.error){$("out").innerHTML="<b>Error:</b> "+esc(r.error);return}
  let m="";if(r.submitted)m=r.submitted===r.label?"<div class=mut>Matches submitted label for this thread.</div>":"<div class=mut>Differs from submitted label ("+esc(r.submitted)+") because the input was edited.</div>";
  $("out").innerHTML=`<div class="act ${r.action}">${r.action}${r.price?" at ₹"+r.price:""}</div><div class=lab>${esc(r.label)}</div><p>${esc(r.why)}</p><ul>${r.steps.map(s=>"<li>"+esc(s)+"</li>").join("")}</ul>${m}`}
(async()=>{const ids=await j("/api/ids");$("tid").innerHTML=ids.map(i=>`<option>${i}</option>`).join("");$("tid").onchange=load;$("go").onclick=go;load()})();
</script>"""


class H(BaseHTTPRequestHandler):
    def send(self, body, ctype="application/json"):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/ids": return self.send(json.dumps(list(BYID)))
        if u.path == "/api/thread": return self.send(json.dumps(BYID.get(parse_qs(u.query).get("id", [""])[0], {})))
        self.send(PAGE, "text/html")

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            out = run(d)
            out["submitted"] = SUBMITTED.get(d.get("thread_id"), "")
        except Exception as e:  # bad user input must not kill the server
            out = dict(error=f"{type(e).__name__}: {e}")
        self.send(json.dumps(out))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Procurement Desk UI: http://127.0.0.1:8765  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", 8765), H).serve_forever()
