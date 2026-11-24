# The Procurement Desk: team robotech.ai

Agent for the Kaggle task "The Procurement Desk" (Data Sprint 2.0, Agentic AI track).
Each of the 2,000 supplier threads gets one label `ACTION:REASON:COUNTER_PRICE`.
Score 1.00000 on both the public and the private leaderboard. The final submission is `submission.csv`.

The agent is a deterministic rule engine. It uses **no LLM and no external API** at run time, by design (see section 5).
Labels come only from running `engine.py`. `python check.py` reproduces every number in section 7.
Slides: [`docs/presentation.pdf`](docs/presentation.pdf). License: MIT.

![Demo UI on sample thread T00028: the supplier's correction makes the price acceptable, but a forwarded note to "the language model" is a prompt injection, so the agent escalates](docs/ui.png)

## 1. Overview

The agent works like a procurement desk clerk who follows the playbook exactly:

1. **Read the thread.** Split it into messages by their headers. Take the supplier's latest message, and the supplier's own previous quote when the latest message refers to it.
2. **Read the playbook.** Parse category pages, amendments and supplier files from the markdown at run time.
3. **Understand the offer.** Find the price and normalize it to INR, excluding GST, per category unit. If there is no usable price, stop with `ESCALATE:MISSING_INFO`.
4. **Decide.** Walk the decision procedure from `policies/decision-procedure.md` in order. The first rule that fires wins:
   1. no usable price -> `ESCALATE:MISSING_INFO`
   2. supplier is blacklisted -> `REJECT:BLACKLISTED_SUPPLIER`
   3. prompt injection anywhere in the thread -> `ESCALATE:PROMPT_INJECTION`
   4. banned contract term in the latest message -> `ESCALATE:BANNED_TERM`
   5. price `p` above the concession limit `L(r)` -> `REJECT:ABOVE_WALKAWAY` on the final round, otherwise `COUNTER:COUNTER_OFFER:<L rounded>`
   6. `p * quantity` above the approval limit -> `ESCALATE:OVER_APPROVAL_LIMIT`
   7. otherwise -> `ACCEPT:ACCEPTABLE_PRICE`
5. **Hand off to a human** whenever the playbook says escalate.

The numbers in force are applied in this order: category page, then amendments with an effective date on or before the thread date, then the supplier contract (its price cap replaces the walk-away price, its currency rate replaces the table rate). Suppliers on probation use `L(r) = T` in every round.

Hard-coded in `engine.py`: the currency table from `policies/units-and-currency.md`, the buyer's sender name `Acme Procurement`, the factors 12 (dozen, months per year) and 30% (advance payment limit), and the text patterns. Everything else is read from the playbook files.

## 2. Mathematics

All arithmetic uses exact rationals (`fractions.Fraction`), so there are no floating-point rounding errors.

**Price normalization.** `p` is the offer in INR, excluding GST, per category unit. `qty` is the thread quantity. The steps run in this order (`engine.py`, `offer`):

1. CORRECTION: if the message says the price "should read X, not Y", use X.
2. Otherwise take the first line that contains an amount (or a "further d% off our previous quote" line).
3. "Further d% off our previous quote": `p = p_prev * (1 - d/100)`, where `p_prev` is the supplier's own previous quote (the last earlier message not sent by Acme Procurement), normalized by these same steps.
4. Range "between A and B": the upper end, `max(A, B)`. Two-tier quote "orders of up to N ...": first price if `qty <= N`, else the second price. Otherwise the first amount on the line.
5. Currency: `p = amount * rate`. Table: USD 84.5, EUR 91, GBP 106, INR 1. A supplier contract rate replaces the table rate. Any other currency gives `MISSING_INFO`.
6. "d% discount on our list price": `p = p * (1 - d/100)`.
7. Volume discount "further d% off for orders of N": only if `qty >= N`, `p = p * (1 - d/100)`.
8. Free units "plus f free ... for every m": `p = p * m / (m + f)`.
9. "In total for all N": `p = p / N`.
10. Dozen: `p = p / 12`. Pack: "per pack of N" gives `p / N`, "per pack" gives `p / pack_size` from the category page. Otherwise "per N <units>" gives `p / N`.
11. "Per ream": `p = p * reams_per_unit` from the category page.
12. GST inclusive: `p = p / (1 + gst)`, with `gst` from the category page.
13. Billing period (subscription categories only): monthly to yearly is `p * 12`, yearly to monthly is `p / 12`. A subscription price with no period gives `MISSING_INFO`.

Amounts are read with `₹ Rs $ € £` or a three-letter code, with optional `k`, `lakh` or `crore` suffixes. Amounts in words are read when followed by "rupees" (units up to lakh).

**Concession schedule.** With target `T`, walk-away `W`, rounds `R`, exponent `beta`, current round `r`:

```
L(r) = T + (W - T) * ((r - 1) / (R - 1)) ** beta
```

`L(1) = T` and `L(R) = W`. The buyer allows a higher price in later rounds. Probation suppliers use `L(r) = T`.

**Counter rounding.** `counter = floor(L(r) + 1/2)`, rounding half up to whole rupees.

**Final round.** If `p > L(r)` and `r >= R`, the label is `REJECT:ABOVE_WALKAWAY`. Otherwise it is a `COUNTER` at `L(r)` rounded.

**Approval limit.** Checked only when `p <= L(r)`. Escalate if `p * qty > limit`, where `p` is per unit in INR excluding GST (for subscriptions, one billing period) and `limit` is the category approval limit, possibly changed by an amendment.

**Example (thread T00033, sample data).** Laptops: `T = 62000`, `W = 70000`, `R = 4`, `beta = 2`, round `r = 2`.
`L(2) = 62000 + 8000 * (1/3)^2 = 62888.89`. The quote is INR 71,900 per laptop, above `L(2)`, and round 2 is not final, so the label is `COUNTER:COUNTER_OFFER:62889`.

## 3. Architecture diagram

```mermaid
flowchart TD
    A[threads.csv<br/>2000 threads] --> B[split_thread<br/>earlier / latest messages]
    P[playbook files<br/>categories, amendments, suppliers] --> L[load_playbook<br/>regex parse]
    B --> C[offer<br/>parse + normalize to INR excl. GST per unit]
    C -->|no usable price| M[ESCALATE:MISSING_INFO]
    C --> D{supplier BLACKLISTED?}
    D -->|yes| R1[REJECT:BLACKLISTED_SUPPLIER]
    D -->|no| E{INJECTION regex<br/>in whole thread?}
    E -->|yes| X1[ESCALATE:PROMPT_INJECTION]
    E -->|no| F{banned_term<br/>in latest message?}
    F -->|yes| X2[ESCALATE:BANNED_TERM]
    F -->|no| G[limits<br/>category + amendments by date + contract cap]
    L --> G
    G --> H{"p above L(r) ?"}
    H -->|yes, last round| R2[REJECT:ABOVE_WALKAWAY]
    H -->|yes, earlier round| K["COUNTER:COUNTER_OFFER:round L(r)"]
    H -->|no| I{"p x qty above approval limit?"}
    I -->|yes| X3[ESCALATE:OVER_APPROVAL_LIMIT]
    I -->|no| Z[ACCEPT:ACCEPTABLE_PRICE]
    M --> O[submission.csv]
    R1 --> O
    X1 --> O
    X2 --> O
    R2 --> O
    K --> O
    X3 --> O
    Z --> O
```

## 4. Implementation

Everything is rule-based Python code. **No part uses an LLM.**

`engine.py` (197 lines, standard library only) produces the submission:

| Function | Role |
|---|---|
| `load_playbook(root)` | Parses categories (target, walk-away, rounds, exponent, approval limit, GST, unit, pack and ream sizes), amendments (effective date, field, value) and suppliers (status, contract rates, price caps) from the markdown files. |
| `split_thread(msg)` | Splits a thread into `Earlier` and `Latest` messages by their headers. |
| `amounts(line)` / `words_to_num` | Finds amounts with currency symbols or codes, `k`/`lakh`/`crore` suffixes, and amounts in words ending in "rupees". |
| `offer(...)` | Normalizes the supplier's offer to INR excluding GST per category unit (section 2). Raises `Missing` if no usable price exists. |
| `INJECTION` | Regex of prompt-injection phrases, matched against the whole thread. |
| `banned_term(text)` | Detects auto-renewal, unlimited liability, exclusivity, and advance payment above 30% or "half". |
| `limits(...)` | Applies amendments dated on or before the thread date, then the supplier contract price cap. |
| `decide(row, ...)` | The decision procedure. Returns the label string. |
| `main(...)` | Reads `threads.csv`, writes `thread_id,label`. |

Other files:

- `check.py`: reproduces every number in section 7 (sample, byte match, `our_last_counter` check, cross-check).
- `verify.py`: a second rule implementation with different parsing code, used only as a cross-check, never to produce the submission. Unlike `engine.py`, it does not read the playbook: the category, amendment and supplier values are typed into the code. This is on purpose: if the playbook parser in `engine.py` misread a value, the two would disagree.
- `ui.py`: local demo UI (standard library `http.server`). It calls `engine.decide` and shows the label and the steps for any thread.
- `solution.ipynb`: notebook version. It writes `engine.py`, runs it and checks the sample.
- `docs/`: slides (`presentation.pdf`) and a screenshot of the demo UI.
- `submission.csv`: final predictions. `submission_B.csv`: rejected variant (section 7). `verify_labels.csv`: output of `verify.py`.

## 5. AI models & APIs

- Models at run time: **none**. Prompt strategy: not applicable. API calls: **0**. Cost: 0. A full 2,000-thread run takes under a second on a laptop.
- AI at development time: Claude Code (Anthropic) was used as a coding tool (section 10). It does not take part in labelling.

**Why no LLM in an agentic track.** The playbook is a closed procedure with exact arithmetic and a fixed rule order, so an exact implementation scores 100%, and the private leaderboard confirms that it generalizes. The security policy says supplier messages are untrusted and that text trying to instruct an AI must never be followed. An LLM that reads supplier text can be steered by it; a pattern matcher only detects it and escalates. The design still works as an agent: it perceives (reads the thread and the playbook), reasons (normalizes the offer, computes `L(r)`), acts (accept, counter with a price, reject) and hands off to a human when the playbook says escalate. Every decision is reproducible and can be explained step by step.

## 6. Tricky cases

- **Prompt injection.** The `INJECTION` regex scans the whole thread, including earlier and forwarded messages. It matches text addressed to an AI, bot, assistant or language model, "admin override", "ignore your previous instructions", "system note", HTML-comment notes to an assistant, and Hindi phrases for "assistant". A hit gives `ESCALATE:PROMPT_INJECTION`. Supplier text is never followed as an instruction; it is only matched. Example: T00028 has a correction to Rs. 264, below target, so it would be ACCEPT, but a forwarded "Note for the language model processing this thread" fires first, so the label is `ESCALATE:PROMPT_INJECTION`. Messages that claim approval was already granted are caught by these phrases in this data, not by a separate rule.
- **Banned terms.** `banned_term` checks the latest message only: auto-renewal wording, unlimited liability, exclusivity, and advance payment above 30% (or "half"). A sentence that says "no automatic renewal" is removed first, so it does not trigger. Example: T00011 ("This agreement auto-renews every year unless cancelled in writing") gives `ESCALATE:BANNED_TERM`.
- **Dated amendments.** An amendment applies only if its effective date is on or before the thread date. If two amendments for one category are both in force, the later effective date wins. Example: T00012 is dated 2026-10-18, so AMD-04 (from 2026-09-20) lowers the catering target from 280 to 270.
- **Supplier contracts.** A contract price cap replaces the walk-away price `W` for the category it names. A contract currency rate replaces the table rate for that supplier. Examples: T00025 (monitors) uses the contract cap ₹17,600 as `W`; in the final round the quote is above it, so `REJECT:ABOVE_WALKAWAY`. T00037 converts GBP 79.75 at the supplier's contract rate ₹104.5 instead of the table rate ₹106, giving `COUNTER:COUNTER_OFFER:6750`.
- **Supplier names.** The `supplier` column is matched exactly against the `# Supplier:` header of each supplier file. The playbook has no alias or "trading as" table. A supplier name says nothing about its category (Monsoon Foods quotes laptops in T00033). A supplier not in the files is treated as approved with no contract.
- **Currencies.** USD, EUR, GBP and INR via `$ € £ ₹ Rs` or three-letter codes. Any other currency gives `MISSING_INFO`.
- **Corrections.** A message that says the price "should read X, not Y" uses X (T00028).
- **Multi-price messages.** Ranges use the upper end. Two-tier quotes use the tier for the thread quantity. Otherwise the first amount on the first priced line is used. "Further d% off our previous quote" is applied to the supplier's previous quote. Examples: T00002 quotes "between Rs. 1,506 and ₹1,638", so 1,638 is used. T00025 quotes Rs. 20,208 for orders up to 200 and ₹18,995 above; the quantity is 20, so 20,208 is used. T00017 says "a further 10% off our previous quote" and gets `COUNTER:COUNTER_OFFER:9000`.
- **Probation.** T00012: supplier on probation, quote ₹315 per meal incl. 5% GST, so `p = 315 / 1.05 = 300`. `L = T = 270`, so the label is `COUNTER:COUNTER_OFFER:270`.

## 7. Evaluation

Run `python check.py` to reproduce all of these:

| Check | Result |
|---|---|
| Sample threads vs official `sample_answers.csv` | **40 / 40** |
| `engine.py` output vs `submission.csv` | byte-identical |
| Buyer's own earlier counter `our_last_counter` equals our `L(r-1)` | **1423 / 1423** threads that have one |
| Same check with variant B amendment order | 1416 / 1423 |
| `verify.py` (second implementation) vs `submission.csv` | **2000 / 2000** |
| Kaggle public and private leaderboard | **1.00000** |

The `our_last_counter` check uses data the engine never reads for its decision, so it independently confirms the concession schedule, the rounding and the amendment order on 1423 threads.

Label counts in `submission.csv`: COUNTER 627, ACCEPT 359, OVER_APPROVAL_LIMIT 286, ABOVE_WALKAWAY 227, PROMPT_INJECTION 160, BANNED_TERM 144, BLACKLISTED_SUPPLIER 105, MISSING_INFO 92.

**Worked examples** (sample threads, engine output equals the official answer):

| Thread | What happens | Label |
|---|---|---|
| T00033 | Laptops, round 2 of 4, `beta = 2`. Quote INR 71,900 > `L(2) = 62888.89`. | `COUNTER:COUNTER_OFFER:62889` |
| T00012 | Probation supplier, AMD-04 target 270, ₹315 incl. 5% GST = 300 > 270. | `COUNTER:COUNTER_OFFER:270` |
| T00028 | Correction to Rs. 264 (below target), but a forwarded note to "the language model". Injection is checked first. | `ESCALATE:PROMPT_INJECTION:` |

**What changed between submissions:**

1. First submission: all rules, without the "per N units" case.
2. Final submission (`submission.csv`): prices quoted "per 100 fixtures/meals/shipments" are divided by 100. This changes T10060, T11145 and T11613. Nothing else changed. Both scored 1.00000 on the public leaderboard.

**Rejected variant B** (`python engine.py data/threads.csv submission_B.csv --amd-by-number`): when two amendments are both in force, the higher AMD number wins instead of the later effective date. It changes only T11894 and T11933. It matches `our_last_counter` on only 1416/1423 threads (the 7 failures expect 2080 and get 2065), so it was never submitted.

**Error analysis.** No known errors on the sample, the public or the private part. The rules that needed the most care were the amendment order (settled by the `our_last_counter` check), "per N units" pricing, and the rule order when a thread has both a correction and an injection.

## 8. Real-world application

A procurement team could use the agent as a first-pass desk: it reads each supplier reply, normalizes the quote, and returns accept, counter with a number, reject, or escalate to a person, together with the rule that fired (`ui.py` shows these steps). Because it is rule-based, every decision can be explained and audited, and supplier text cannot instruct it.

To deploy it safely:

- Keep a human on every `ESCALATE` and review a sample of `ACCEPT` and `COUNTER` decisions.
- Load category, amendment and supplier data from the system of record, and keep the currency table current.
- Log the input, the rule that fired and the playbook version for every decision.
- Require a human approval step before any counter is actually sent.
- Add a test (like `check.py`) for each new quote format before trusting it.
- Treat a new phrasing that no pattern covers as a reason to escalate, not to guess.

## 9. Drawbacks & limitations

- **Regex parsing.** A price phrased in a way no pattern covers becomes `MISSING_INFO` or is read from the wrong amount. With several prices on one line and no range or tier wording, the first amount is used. Only two-tier quotes are supported.
- **Injection detection is a phrase list.** A new wording can be missed and then falls through to the normal price rules. Ordinary text can be flagged: the Hindi word for "assistant" matches anywhere, even as a job title.
- **Banned terms** are keyword based and checked only in the latest message. Explicit negation removal exists only for renewal ("no automatic renewal"). For exclusivity, the common wording "not asking for exclusivity" (118 threads) does not match the patterns, so it is not flagged, but a negated sentence that contains "exclusive supplier" or "exclusively" would be. Advance payment in words is recognized only as "half".
- **Playbook format.** The parsers expect this playbook's markdown wording. A change in wording breaks them; `engine.py` then fails with an error instead of guessing. If no `policies` folder is found under the data folder, it stops with a `StopIteration` error.
- **Scope.** English messages only (plus a few Hindi injection phrases). No memory beyond the supplier's previous quote. `precedents/` is not read; its cases are covered by the patterns.
- Safe use needs the human review described in section 8.

## 10. Original work & disclosures

- Author: Alexandru Ilies (team robotech.ai, single member on Kaggle).
- The code (`engine.py`, `verify.py`, `check.py`, `ui.py`, the notebook) was written with **Claude Code (Anthropic)**, an AI coding tool, under my direction. I chose the approach (exact rules instead of an LLM), checked the rules against the playbook, ran every check and made the submissions. Labels are produced only by running the code, never typed by hand.
- Libraries: Python standard library only (`csv`, `re`, `math`, `fractions`, `pathlib`, `sys`, `io`, `json`, `http.server`, `urllib.parse`). No external packages, templates or third-party code.
- Data: only the competition files. No code or labels were shared with other teams. Competition data is not included in this repository.
- License: MIT (`LICENSE`).

## 11. How to run

Requires Python 3.9 or newer (tested on 3.13). No installs needed (`requirements.txt` lists no packages).

1. Download the competition files from Kaggle and unzip them into `data/`. The result looks like this (the playbook is already a folder inside the download):

   ```
   data/threads.csv
   data/sample_threads.csv
   data/sample_answers.csv
   data/playbook/playbook/policies/ ... categories/ ... suppliers/ ... amendments/ ...
   ```

2. Reproduce the final CSV:

   ```
   python engine.py data/threads.csv submission_out.csv
   ```

   The playbook folder is found automatically (the folder that contains `policies/`, anywhere under the folder of `threads.csv`). You can also pass it as a third argument: `python engine.py data/threads.csv submission_out.csv data/playbook/playbook`.

3. Check it matches the submitted file (identical bytes):

   ```
   fc /b submission_out.csv submission.csv        (Windows)
   cmp submission_out.csv submission.csv          (Linux / macOS)
   ```

4. Reproduce all evaluation numbers (sample 40/40, byte match, 1423/1423, 2000/2000):

   ```
   python check.py
   ```

5. Optional: run the second implementation alone: `python verify.py data/threads.csv verify_out.csv`.
6. Optional demo UI: `python ui.py [threads.csv] [playbook_dir]` (defaults: `data/threads.csv`, playbook found automatically), then open http://127.0.0.1:8765.

The output has the header `thread_id,label` and 2,000 rows.
