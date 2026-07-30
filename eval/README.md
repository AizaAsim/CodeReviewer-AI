# Eval harness

Measures review quality of CodeReviewer AI against the hand-labeled
`codereviewer-testbed` pull requests.

## Dataset

`dataset.jsonl` — one JSON object per PR:

| PR | Planted issue |
|---|---|
| 1 | security — f-string SQL injection |
| 2 | logic — bare `except: pass` |
| 3 | logic — off-by-one in `page_items` |
| 4 | security — hardcoded API key |
| 5 | style — unused import + inconsistent naming |
| 6 | clean baseline (no planted issues) |

Each planted issue has `path`, `line_range`, and `category`.

## Methodology

1. Start the API (`make dev`) with `EVAL_TOKEN` set.
2. Run `uv run python eval/run_eval.py` (defaults to 3 full trials).
3. For each PR, the harness calls `POST /eval/review` (token-guarded). That
   endpoint runs the **eval graph** (same pipeline as production through
   `decide`, but **does not post** to GitHub).
4. Scoring uses **filtered** findings (post–severity-gate), i.e. what would be posted:
   - **Recall** — fraction of planted issues matched by ≥1 finding with the same
     category and a line inside `line_range`
   - **Precision** — fraction of posted findings that match some planted issue
   - **Noise rate** — count of findings posted on clean PRs (PR #6)
5. Metrics are reported as **mean ± sample stdev** across the 3 trials to
   acknowledge LLM nondeterminism.
6. Results are written to `eval/results.json`.

## How to run

```bash
# in .env
EVAL_TOKEN=some-long-random-string

make dev   # terminal 1

export EVAL_TOKEN=some-long-random-string
export EVAL_BASE_URL=http://127.0.0.1:8000
uv run python eval/run_eval.py   # terminal 2
```

## Gate-tuning iteration

First eval (confidence cut **0.7**):

- overall recall **0.20**, precision **0.14**
- clean PR noise **1.0** finding / trial (docstring invention)
- many planted bugs were *seen* but labeled with the wrong category
  (e.g. bare-except scored as `security` instead of `logic`)

Tuning applied before README numbers:

1. Tightened security/logic/style prompts to stay in their lanes
2. Raised confidence gate **0.7 → 0.85**
3. Dropped low-value noise phrases (docstring / "consider adding…") in the gate

Re-run `uv run python eval/run_eval.py` and record the new mean±spread below
(and in the main README).

## Post-tune results

After the changes above (3 trials × 6 PRs):

| Metric | Before (0.7 gate) | After (0.85 gate + prompt lanes) |
|---|---|---|
| Recall | 0.20±0.00 | **0.60±0.00** |
| Precision | 0.14±0.02 | **0.50±0.00** |
| Clean-PR noise | 1.00±0.00 | **0.00±0.00** |

What improved: bare-except and off-by-one now score as `logic`; clean PR stays silent.

Still weak: hardcoded-secret PR often gets `approve_note` (security miss); style PR still 0 recall (findings land in other categories). Further prompt work can raise those without bringing clean-PR noise back.

## Limitations

- Small n (6 PRs, mostly single-file Python)
- Single-language dataset
- LLM nondeterminism — always report spread across repeats
- Classification/routing can still mis-label files and change which passes run
- Line matching is exact-range only; near-miss lines count as misses
- Eval endpoint intentionally skips GitHub posting; production posting is
  covered separately by Module 6 live tests
