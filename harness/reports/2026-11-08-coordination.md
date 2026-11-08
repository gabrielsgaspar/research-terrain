# Coordination: campaigns setup and idea 0001's validation

For Gabriel. Written by Claude Code (local session, 2026-11-08). Two tracks
had got interleaved: campaigns (track A) and the confirmation of idea 0001
(track B). This report covers both, phase by phase, in the order you set.
Every step that normally needs your OK is in `harness/AUTONOMY_LOG.md`,
under "Coordination".

## 1. In one table

| Phase | What | Links | State |
| --- | --- | --- | --- |
| 0 | Status, read only | below | done; two surprises (#236 already merged; a ruleset already existed) |
| 1 | CODEOWNERS for the registered analyses, runner, split and seal; decision 0010 accepted | #238 | merged by you |
| 2 | Your decisions on #236; validation of the registered analysis; template diff | #236 comment, run 42476480500, #243, #241 | **Reproduced: yes**; record merged by you; #241 closed |
| 3 | Ruleset `protect-main` updated in place | ruleset 26319698 | done |
| 3 | Smoke-test campaign 0001 | #244, #245, #246, #247, #249 | **report ready (#249), for you** |
| 3 | Three guard gaps found and fixed | #248, #250 | merged by you |
| — | #213 closed (branch kept) | #213 | done |
| 4 | This report, the "Before registration" draft, the log | this PR | for you |

## 2. Phase by phase

### Phase 0: status

- Main's CI passed on `7156972`.
- campaign-gate had not posted on #236 or #238. Neither had an event after
  the gate reached main (#239, 08:30Z).
- `AGENT_APP_BOT` = `terrain-agent[bot]`, the author of PR #212, and
  `CAMPAIGNS_ENABLED` = `false`.
- The three campaign labels already existed.
- Environments: `analysis` and `data-write` are main only, with no
  reviewers. `unblind` is main only, with you as a required reviewer.
- **Differences:**
  - **#236 was already merged** (by you, 08:34Z), so Phase 2 was adjusted:
    no branch update and no merge request.
  - **A ruleset already existed**: `protect-main`, with no bypass, code-owner
    review off, and only `test` required.
  - **An unpushed commit `85c192e`** in the local clone held the CODEOWNERS
    lines for Phase 1, plus a block for the split. You chose to use it.
  - **Explore run 42463317312** of `0001_registered_check` was started at
    08:31Z, before #236 was merged. It stopped at "explore/0001_registered_check.py
    does not exist on main" and **read no data**.

### Phase 1: #238 (merged by you)

- Main was merged into `campaigns/1-rules-and-code` (no rebase).
  `harness/AUTONOMY_LOG.md` conflicted only because both sides had appended;
  both texts were kept word for word.
- `85c192e` was cherry-picked; its full diff is in #238's description. On top
  of it, these were added under "The sample split, the exploration
  restriction and GCP setup":
  - `src/terrain/split.py`;
  - `src/terrain/builds/cell_outcomes.py`;
  - `pipeline/build/cell_outcomes.py`;
  - `tests/test_split.py`, `tests/test_explore.py`,
    `tests/test_build_cell_outcomes.py` and `tests/test_repo_rules.py`.

  Each one is listed with its reason in #238, and each is asserted in
  `test_repo_codeowners_protect_the_gate`.
- **Not owned, for you to decide:** the `sealed:` line of `data/catalog.yaml`
  (cell_outcomes). Owning the catalog would block every campaign that adds a
  dataset, and CODEOWNERS cannot own one line. The build would still fail at
  upload (create-only, and its account cannot read `sealed/`), but no review
  would stop the edit.
- Decision 0010: accepted, dated 2026-11-07, the day you accepted it.

### Phase 2: idea 0001 (track B)

- Your decisions (a)-(d) posted on #236 as a comment.
- **Validation, run [42476480500](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42476480500)**,
  on main at `7156972`. Verbatim:

  > Reproduced: yes. 821 numbers of run 42298466207 and 54 of run 41839642406 compared at 0.50% on the exploration half; 0 differ; largest relative difference 1.44e-14.

- Record PR #243: you asked for a lessons entry and an idea 0001 status
  line. Both were added on its branch, main was merged in, and you merged
  it. #241 is closed with a link to the run.
- The `confirm/specs/TEMPLATE.yaml` diff for (d) went to you in the session
  (`predicted_sign` gains `two_sided`; `analysis`, `pap_commit`, `params`
  added). `confirm/` was not edited; that file was read only to write the
  diff.

### Phase 3: campaigns (track A)

**Labels:** skipped, as you chose; all three exist.

**Ruleset `protect-main` (26319698), updated in place** after #238 was
merged and after the gate had posted on #244. The read-back equals the
request.

| | Before | After |
| --- | --- | --- |
| Bypass | none | Repository admin role, pull requests only |
| Code-owner review | off | on |
| Required checks | `test` (app 15368) | `test` and `campaign-gate`, both app 15368, not strict |
| Unchanged | | no deletion, no force push, PR with 0 approvals, `require_extra_approval_for_unattributed_changes: true` |

`require_extra_approval_for_unattributed_changes` is not described in
GitHub's documentation. It was `true` from the ruleset's first version
(2026-11-01), and you had merged App-authored PRs with no approval while it
was on. **The App's own merge of record PR #246 under the new ruleset
worked**, so it does not block the tick.

**Smoke test, campaign 0001** (#244, merged by you with the bypass). The
campaign file is the worked example from the `campaign-design` skill, with
kill rule k1 (`windows.1%.power < 0.8`) as written.

| # | Run | What it did |
| --- | --- | --- |
| tick 1 | [42494395444](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42494395444) | filed tracking issue #245 |
| tick 2 | [42494521026](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42494521026) | "s1: started"; explore-run [42494552921](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42494552921) for `0003_mayor_power`, campaign 0001/s1 |
| — | | record PR #246. **Its JSON equals run 42367009833's exactly.** The gate first said pending (it ran before CI ended), then success on CI's completion |
| tick 3 | [42494806321](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42494806321) | **the App merged #246** (`1d1631a`); main's CI passed |
| tick 4 | [42494916332](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42494916332) | "Verdict: **killed**", k1 observed 0.05197143596133924; close-out issue #247 filed with `agent-plan` |
| — | [42494950029](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42494950029) | **planner failed**: the Claude Code action refuses bot actors. Stop: `CAMPAIGNS_ENABLED=false`. Fixed in #248 |
| — | [42497587813](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42497587813) | after #248, `agent-plan` re-added from your account: plan with six files |
| tick 5 | [42497783440](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42497783440) | swapped #247 to `agent-build` |
| — | [42497825697](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42497825697) | build succeeded; close-out PR #249 |
| — | [42498161849](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42498161849) | **review failed**: its guard looked the App up as a collaborator. Stop: `CAMPAIGNS_ENABLED=false`. Fixed in #250 |
| — | [42502060530](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42502060530) | after #250, #249's CI re-run from your account: review **Approve** |
| tick 6 | [42502229036](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42502229036) | dispatched campaign-gate for #249 (the posted status was stale): `success` |
| tick 7 | [42502321813](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42502321813) | "@gabrielsgaspar the report is ready for you: PR #249" |

`CAMPAIGNS_ENABLED` is `true` now. The next tick, scheduled or by hand,
will post "Close-out merged" once you merge #249.

## 3. Differences from the design

`DESIGN.md` is not in the repository or anywhere this session could read.
It was presumably part of the setup package. The comparison below is with
what the repository states: decision 0010, `research/campaigns/README.md`,
the skill's worked example, and the follow-up-3 report.

1. **Guard gap 1, `agent-plan`.** The Claude Code action had no
   `allowed_bots`, so a planner started by the App failed (run 42494950029).
   Fixed in #248 (`allowed_bots: terrain-agent[bot]`).
2. **Guard gap 2, `agent-build`.** `allowed_bots` held only
   `github-actions[bot]`, so a build started by the tick's label swap would
   have failed the same way. Fixed in #248, before it was hit: build
   42497825697 ran with the App as labeler.
3. **Guard gap 3, `agent-review`.** `has_write` looked the App up as a
   collaborator and failed on the issue author; it would have failed on the
   `agent-build` labeler next (run 42498161849). Fixed in #250, accepting the
   App only when `APP_BOT` is set. #250's description traces every remaining
   step, a fix round and the re-review included.
4. **The gate never refreshes a PR after Agent review.** Its `workflow_run`
   trigger gets the review run's own branch, `main`, so it matches no PR
   (run 42498187254). The tick covers this: when its own gate verdict passes
   and the posted status lags, it dispatches the gate (tick 6). The cost is
   one extra tick per reviewed PR.
5. **The tick does not run every three hours** (decision 0010, point 2), and
   the gate's hourly sweep did not run hourly. See section 4.
6. **The planner with the App as labeler has not run.** #247's `agent-plan`
   was re-added from your account after #248, so that path is shown by the
   code only. It runs first in a real campaign.
7. **Merge and verdict take two ticks.** Tick 3 merged the record and tick 4
   posted the verdict and filed the close-out. The skill's "Expected" reads
   as one sequence; the order is as designed, but each step costs a tick.
8. **Budget counting.** The tick counts every "## Agent plan: " comment as a
   model job, including the "withheld" one from the failed planner run. The
   close-out is not limited by `max_model_jobs` (the example has 0), as the
   code intends.
9. **First gate evaluation of a record PR is pending.** It runs on
   `pull_request_target` before CI ends, then corrects itself when CI
   completes. Harmless, but the first status a reader sees is pending.

Nothing differed from the follow-up-3 report. The validation said
"Reproduced: yes", as it expected.

## 4. Schedule

**What was observed (read only).**

| Workflow | Cron | On main since | Scheduled runs |
| --- | --- | --- | --- |
| campaign-gate | `17 * * * *` | 08:30Z (#239) | one: 42497905438 at 16:03Z. The slots from 09:17 to 15:17 produced nothing before it |
| campaign-tick | `41 */3 * * *` | 08:30Z (#239) | one: 42499183552 at 16:18Z, 37 minutes after the 15:41 slot; skipped (campaigns were off). 09:41 and 12:41 produced nothing |
| zotero-sync | `17 6 * * 1` | 2026-11-03 | none; its first slot is Monday 2026-11-09 06:17Z |

GitHub does not guarantee scheduled runs. They are delayed or dropped under
load, and a newly added schedule can take hours to start. Today the tick's
schedule fired once in about eight hours, late. A campaign that relies on it
alone could wait half a day between steps, and the 24-hour grace for blocked
steps counts from a tick that may come late.

**Proposal (not applied): make the tick event-driven, with the cron as a
backup.**

```yaml
on:
  workflow_run:
    workflows: [Explore run, CI, Agent plan, Agent build, Agent review]
    types: [completed]
  schedule:
    - cron: "41 */3 * * *"   # backup only
  workflow_dispatch:
concurrency:
  group: campaign-tick     # unchanged: one tick at a time, never cancelled
  cancel-in-progress: false
```

The job keeps `if: vars.CAMPAIGNS_ENABLED == 'true' && github.ref ==
'refs/heads/main'`. It would add a cheap filter on the triggering run, for
example skipping CI runs whose branch is neither `agent/**`, `explore/**`
nor `main`.

**It must not listen to Campaign gate.** GitHub runs at most three levels of
`workflow_run` chains. CI (pull_request) starts Agent review (level 2),
which starts Campaign gate (level 3). A tick on Campaign gate would be level
4 and would silently never run, in exactly the case that matters: just
after a review. A tick on Agent review is level 3, which is allowed. The
tick's own dispatches (explore-run, campaign-gate) start new chains, so they
do not count.

**What else could go wrong:**
- **Many ticks.** CI runs twice per push, on every branch. With
  `cancel-in-progress: false`, GitHub keeps one running and one pending run
  per group and cancels older pending ones. The tick is idempotent, so lost
  pending runs are harmless, but each costs a runner start. The branch
  filter above keeps most of them away.
- **Faster pacing.** "One new step per campaign per tick" was sized for
  three-hour ticks. Event-driven ticks start the next step minutes after the
  last one ends. That means more model jobs per hour on the shared
  subscription, and less time for you to notice something before the next
  step. The budget still bounds the total. A minimum gap between steps
  (say, an hour since the last event) would restore the old pace.
- **Races.** A tick started by CI's completion can run before the gate has
  posted for the same commit. It then sees a stale status and dispatches
  the gate (difference 4). That is harmless and is how tick 6 worked, but
  the gate runs twice.
- **Loops.** The tick's own actions start the listed workflows (merging
  starts CI on main; a label swap starts agent-build), which then start a
  tick. Each loop is bounded because the tick acts only on state changes.
  A bug that acts without changing state (for example re-dispatching on
  every tick) would loop until the budget or `CAMPAIGNS_ENABLED` stops it.
  That is an argument for a test that a tick on an unchanged snapshot
  decides no actions.
- **Fork PRs.** `workflow_run` runs with secrets even for a fork's CI. The
  tick reads no PR code, but the filter should also require the triggering
  run's repository to be this one.
- **The backup cron is no more reliable than today's.** A second entry
  (`11,41 * * * *`) adds chances, not guarantees.

**Other options, for comparison:**
- **A second cron entry only:** the simplest change, still at GitHub's
  mercy.
- **An external scheduler** (a cloud routine or cron calling
  `workflow_dispatch`): reliable timing, but it needs a token outside GitHub
  with `actions: write`, which is one more secret to guard.
- **The tick re-dispatching itself while work is in flight:** no new
  secret, but an easy infinite loop. Not recommended.

A separate, smaller fix for difference 4: `agent-review`'s post job could
dispatch `campaign-gate` with `pr=<n>` after posting (the job token may
start `workflow_dispatch`). The gate would then update without waiting for
a tick.

## 5. Before registration

Run 42476480500 checked every number the registered analysis shares with
the explore runs. It did not check the new paths: `direct_adj`,
`ring2_adj`, `ring5_adj`, `direct_pre`, `direct_pre_adj`, `align` and
`balance`. No earlier run has them, so none of their numbers could be
compared.

**Proposal: issue draft 40,
`harness/issue-drafts/40-explore-registered-new-paths.md`.** It is not filed
and not run; you decide. It is a typed explore task (two files) that runs the
analysis's own functions on the exploration half at 0.50% and reports only
pass or fail and counts. It prints no slope, p-value or quantile.

The seven checks:
1. Pairs with exactly one incumbent (Z), counted per election.
2. The same cells and pairs with and without Z, with each Z term equal to
   `s` times its D term.
3. Z fixed under a re-flip.
4. Alignment kinds summing to the pairs, and components summing to D.
5. The placebo using the direct exposure.
6. No NaN or infinite values, reported as paths only.
7. Balance computed on every covariate.

A test checks that `results.json` holds no floating-point number. It never
runs at 0.25%. It changes nothing under `src/terrain/registered/`.

## 6. Still open

| Item | What it is | Why it is open |
| --- | --- | --- |
| Issue #245 | Campaign 0001's tracking issue | until the close-out is merged and a tick records it |
| Issue #247 | Campaign 0001's close-out task | closes when #249 is merged ("Closes #247") |
| PR #249 | The close-out report, ledger, lessons entry, idea 0003 status line and `status: done` | yours to read and merge |

No other issue is open. #241 was closed with its run (42476480500). #213
was closed with your comment; its branch is kept.

## 7. What is left for you

1. **Read and merge #249**, the smoke test's close-out. Agent review
   approved it, and the gate says "checks pass; @gabrielsgaspar reviews and
   merges it". It touches owned paths, so it needs your admin bypass.
2. **Merge this PR** (`harness/` is owned, so it needs the bypass).
3. **Your template PR** to `confirm/specs/TEMPLATE.yaml`, with the diff
   given in the session.
4. **Fill `registered` and `pap_commit`** in the spec
   (`harness/drafts/specs/0001-direct.yaml`) and move it to `confirm/specs/`.
5. **Registration** (plan draft, section 10). Merge the plan into
   `confirm/pap/`, record its hash, register externally, then the spec as in
   item 4. Draft 40 is there if you want the new paths checked on real data
   first.
6. **Decide** on:
   - the `data/catalog.yaml` `sealed:` line (section 2, Phase 1);
   - the schedule proposals (section 4);
   - the gate-dispatch fix (difference 4);
   - whether to leave `CAMPAIGNS_ENABLED` `true`.
