# The Procurement Desk: team robotech.ai

Rule-based agent for the Kaggle task "The Procurement Desk" (Data Sprint 2.0, Agentic AI track).
Public leaderboard score: 1.00000 (first version). The current `submission.csv` adds one fix: prices quoted
"per 100 fixtures/meals/shipments" are divided by 100 (changes T10060, T11145, T11613).

## Approach

The playbook defines a fully deterministic decision procedure, so the agent implements it directly as code.
No language model or external API is used at any stage. Labels come only from `engine.py`.

For each thread the engine:

1. Splits the thread into messages and takes the supplier's latest offer. A CORRECTION replaces the price it
   corrects. "Further X% off our previous quote" is applied to the supplier's own previous quote.
2. Normalizes the offer to INR excluding GST per category unit, with exact rational arithmetic (`fractions.Fraction`):
   currency conversion (table rates, or the supplier's contract rate), GST-inclusive prices, monthly/yearly,
   totals "for all N", dozens, packs, reams, list-price discounts, volume discounts that apply only when the quantity
   reaches the threshold, quantity tiers, "plus N free for every M", ranges (upper end), and amounts written in words.
3. Applies the decision procedure in order, first rule that fires wins:
   missing information, blacklisted supplier, prompt injection (anywhere in the thread), banned contract terms
   (latest message), price versus the concession schedule `L(r)`, approval limit.
4. Uses the numbers in force for the thread: category page, then amendments dated on or before the thread date,
   then supplier contract (price cap replaces the walk-away price, contract rate replaces the table rate).
   Suppliers on probation get `L(r)` equal to the target price in every round.

Category values, amendments and supplier status are parsed from the playbook files at run time; nothing is hard-coded
except the currency table from `policies/units-and-currency.md`.

## How to run

Requires Python 3.9+ (tested on 3.13). Standard library only, no installs.

```
python engine.py threads.csv submission.csv [playbook_dir]
```

`playbook_dir` is the folder that contains `policies/`, `categories/`, `suppliers/` and `amendments/`.
If omitted, the script searches for a `policies` folder under the directory of `threads.csv`, so extract the
competition files with the `playbook` folder next to `threads.csv`. Example layout (any depth under `data/` works):
unzip `playbook.zip` into `data/playbook/`, giving `data/playbook/playbook/policies/...`, then run
`python engine.py data/threads.csv submission.csv`.

Optional flag `--amd-by-number` builds variant B: when two amendments for the same category are both
in force, the one with the higher AMD number wins, instead of the one with the later effective date (the default).
On the competition data this changes only T11894 and T11933 (AMD-07 vs AMD-08, LED lighting).

```
python engine.py threads.csv submission_B.csv --amd-by-number
```

The output is `thread_id,label` with exactly one row per thread (2,000 rows) and labels of the form `ACTION:REASON:COUNTER_PRICE`.

## Validation

`python engine.py sample_threads.csv out.csv` reproduces `sample_answers.csv` on all 40 sample threads (40/40).
The full run on `threads.csv` reproduces `submission.csv` byte for byte, and the run with `--amd-by-number`
reproduces `submission_B.csv` (checked in a fresh folder containing only `engine.py` and `data/`).

`verify.py` is a second, independently written rule implementation (also no LLM, standard library only), used only
as a cross-check: `python verify.py data/threads.csv verify_labels.csv` agrees with `submission.csv` on all 2,000 threads.

## Files

- `engine.py`: the agent (all logic).
- `solution.ipynb`: notebook version (writes `engine.py`, runs it on `threads.csv` from `/kaggle/input` or `./data`, checks the sample).
- `submission.csv`: variant A predictions (default run).
- `submission_B.csv`: variant B predictions (`--amd-by-number`).
- `verify.py`, `verify_labels.csv`: independent cross-check, not used to produce the submissions.
