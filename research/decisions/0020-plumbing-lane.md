---
id: "0020"
title: "Two tiers of rules, and a plumbing lane agents may change"
status: accepted
date: 2026-11-23
supersedes: null
---

# 0020: Two tiers of rules, and a plumbing lane agents may change

Date: 2026-11-23. Status: accepted, drafted by Claude for Gabriel from his
choices of 2026-11-23. It changes nothing until the pull request that
implements it merges (session D for 0021, session E for 0020); that pull
request names this decision.

## The question

Every file an agent may not change today waits for Gabriel, whatever is in
it. Some of those waits are about trust: the gate, kill rules, the split.
Others are plumbing: how long the tick waits for a plan, how many times it
starts a failed run again, how the test suite is set up. A wrong time limit
stops a campaign as surely as a wrong kill rule, but it cannot make a weak
result look strong. Can agents change the plumbing inside fixed bounds,
while everything that decides what counts as a result stays Gabriel's?

## Decision

1. **Tier 1, human-only, unchanged.** Tier 1 is everything
   `.github/CODEOWNERS` owns on 2026-11-23. In any case it includes:
   - workflows (all of `.github/`) and the gate (`src/terrain/campaigns/`
     and the `campaign-gate` workflow);
   - agent roles (`harness/`), `AGENTS.md`, decisions, ideas, campaign
     files and their drafts, and fork files (decision 0015, F2);
   - kill rules and thresholds, wherever they are written: campaign files,
     `research/campaigns/kill-rule-library.yaml` and the kill criteria of
     idea files;
   - budgets, model choice, the split, sealed data, `confirm/`,
     `data/reference/`, `data/fixtures/`, `pyproject.toml` and `uv.lock`.

   "Agents never change workflows" stays true. Tier 1 changes only through
   a pull request Gabriel reviews, as today.
2. **Tier 2, the plumbing lane, is exactly three things.**
   - (a) **One new file, `ops/limits.yaml`,** holding operational limits
     only. It has exactly the eight keys in the table under point 3, each a
     whole number, and nothing else. `ops/` holds no other file. The file is
     not owned in `.github/CODEOWNERS`; the code that reads it and checks
     its bounds is.
   - (b) **`tests/conftest.py`,** for test setup only: fixtures, markers
     and per-test time limits. Never to skip, deselect or xfail a test.
     It is the only `conftest.py` in the repository. In it, these names
     never appear: `skip`, `skipif`, `xfail`, `importorskip`, `deselect`,
     `collect_ignore`, `collect_ignore_glob`, `pytest_plugins`,
     `setattr`, `monkeypatch`, and any `pytest_collection_*`,
     `pytest_ignore_collect`, `pytest_deselected`, `pytest_runtest_*`,
     `pytest_pyfunc_call` or `pytest_report_*` hook. A
     `pytest_configure` hook may only register markers
     (`config.addinivalue_line("markers", ...)`). A fixture that patches
     code belongs in the test file that uses it, not here.
   - (c) **The random seeds of synthetic-data tests in
     `tests/test_explore*.py`,** only to raise how many seeds a test passes
     on (AGENTS.md asks for at least 5). Never a tolerance or an assertion.
     A seed list is a list or tuple of whole numbers, or a `range(n)`, given
     as the values of `pytest.mark.parametrize` for an argument named
     `seed` or `seeds`, or assigned to a module-level name ending in
     `SEEDS`. A lane change may only add seeds at the end of such a list,
     keeping every old seed in its place, or raise the `n` of such a
     `range(n)`. Every other line of the file stays the same.
     `tests/test_explore.py` is owned today, so it is tier 1, not lane.
3. **Bounds.** Every key in `ops/limits.yaml` has a minimum and a maximum,
   written here and enforced by a tier-1 test that session E writes. The
   current values are the constants at the top of
   `src/terrain/campaigns/tick.py` on 2026-11-23 (main at 662f569). They
   become the file's first values. Every one lies inside its bound, so no
   bound was widened.

   | Key in `ops/limits.yaml` | Replaces in `tick.py` | Current value | Minimum | Maximum |
   | --- | --- | --- | --- | --- |
   | `plan_timeout_hours` | `PLAN_TIMEOUT` | 2 h | 1 h | 6 h |
   | `build_timeout_hours` | `BUILD_TIMEOUT` | 12 h | 6 h | 24 h |
   | `run_appear_timeout_hours` | `RUN_APPEAR_TIMEOUT` | 2 h | 1 h | 6 h |
   | `record_timeout_hours` | `RECORD_TIMEOUT` | 3 h | 1 h | 6 h |
   | `ideation_timeout_hours` | `IDEATION_TIMEOUT` | 2 h | 1 h | 6 h |
   | `fork_plan_timeout_hours` | `FORK_PLAN_TIMEOUT` | 6 h | 2 h | 12 h |
   | `max_auto_retries` | `MAX_AUTO_RETRIES` | 2 retries per step | 0 | 3 |
   | `build_restarts_per_block` | (none yet; session B adds build restarts) | session B's value | 0 | 1 |

   - The bounds live in owned code under `src/terrain/campaigns/`, next to
     the code that reads the file. The tier-1 test is a new file,
     `tests/test_ops_limits.py`, which session E adds to
     `.github/CODEOWNERS` in the same pull request. It checks that the file
     has exactly these keys, each a whole number inside its bound. It also
     checks point 2 (b) and, against main, point 2 (c).
   - The tick reads the file at the start of every tick. A missing file, a
     missing or unknown key, or a value outside its bound stops the tick
     with an error naming the key and its bound. It never falls back to a
     default.
   - A new value applies from the next tick, to work already in flight too.
     A message that names a limit (today "no plan two hours after filing",
     "no pull request twelve hours after the plan") prints the value from
     the file.
   - `BLOCK_GRACE` (24 h), `MAX_PIPELINE_RUNS_IN_FLIGHT` (3) and every other
     constant stay in code, as tier 1.
4. **Who changes the lane.** A pull request that touches only lane paths,
   labelled `plumbing`, passes CI and an agent review. Its body names each
   change (key, old value, new value; or the test and seeds added) and the
   run or issue that shows the need. Once session E lands, the tick may
   merge it under the gate like any campaign pull request: CI's `test`
   passes on the head commit, the agent review approves that commit, and
   every file is a lane path. A pull request that touches any other path is
   not a lane change, and only Gabriel merges it. Until session E lands,
   Gabriel merges every lane change.
5. **Never through the lane:** anything that decides what may merge, what
   a check accepts, what a kill rule reads, which model runs, or a budget.
   If a change to a lane path would do one of these (for example, a
   fixture in `conftest.py` that changes what a test checks), it is out of
   the lane, and the reviewer says so as a must-fix item.
6. **Record.** Every lane change is listed on the status page (issue #350),
   in a "Plumbing changes" list: pull request, merge date, and what
   changed. It is also listed in the "Plumbing changes" list of the next
   close-out of every campaign that was active when it merged. The tick
   writes that list, as it writes "Checks not run", and the close-out
   copies it as is.
7. **Review.** Gabriel can revert any lane change. 30 days after session E
   merges, the status page asks him once, in "Waiting on you", whether to
   keep, widen or narrow the lane, next to the list of lane changes so
   far. The line shows for 7 days, then goes away. Keeping the lane needs
   nothing. Widening or narrowing it is a new decision, which is tier 1.

## What stays

Everything in tier 1, and every check in CI, verify, the gate and the agent
review. The tick's closed list of actions gains nothing but the gate merge
of a lane pull request. Budgets cap work as today. Local sessions never
merge, and Gabriel merges everything that is not a lane change or a
campaign pull request that passes the gate.

## Risks and how they are handled

- **A lane change hides a failing test.** `conftest.py` cannot name a skip,
  an xfail, a deselect, a collection hook or a patch; the tier-1 test reads
  it with Python's `ast` module. A seed change can only add seeds, and an
  extra seed makes a test harder to pass, not easier. Removing a seed that
  fails is not allowed.
- **A longer limit hides a hung job.** The maxima cap it: a build waits at
  most 24 h, a plan, run or record at most 6 h, before the tick says so.
- **A shorter limit stops good work early.** The minima are 1 h for a
  plan, a run to appear, a record and an ideation job, 2 h for a fork plan
  and 6 h for a build. A plan, build, run or record past its limit blocks
  the step and says so; it never passes. An ideation job or fork plan past
  its limit means "no forks at this point" (decision 0015), so a shorter
  limit there can cost forks but never a check.
- **More retries spend more runs.** `max_pipeline_runs` counts each started
  pipeline step once, not each retry (`tick.py`, the `used` table), so a
  retry is not counted in the budget. The maximum of 3 allows at most one
  run more per failing pipeline step than today, and the limits on runs in
  flight still apply.
- **A pull request slips a tier-1 path in with lane paths.** It is then not
  a lane change: the gate refuses it, and `.github/CODEOWNERS` still asks
  for Gabriel's review.
- **The bounds themselves are changed.** They are in owned code and in the
  owned test, so only Gabriel changes them.
- **Agents change the lane often and nobody notices.** Every change is on
  the status page and in the next close-out of each active campaign, and
  Gabriel is asked once, at 30 days, whether to keep the lane.
- **Per-test time limits need a package.** `pytest-timeout` is not in
  `uv.lock` on 2026-11-23. A time limit in `conftest.py` waits until
  Gabriel adds it, as for any dependency.

Amended 2026-11-24 (point 3): the key `build_restarts_per_block` (0 to 1) becomes `max_auto_build_restarts_per_step`, value 2, bounds 0 to 2. It caps the tick's automatic restarts of a stalled build per step, counted from the ledger's restart events; restarts from Gabriel's unblocks (removing `needs-human`, or an `Unblocks #<issue>` pull request) and the one main-related restart per red episode (decision 0021, amended) do not count. When the cap is reached, the next stall blocks with "the build stalled again after <n> automatic restarts".

Amended 2026-11-24: the tick's merge of lane pull requests (point 4), the Plumbing changes lists (point 6) and the 30-day review (point 7) come in a later session, with the agent that opens plumbing pull requests. Until then Gabriel merges every lane change.
