---
name: campaign-design
description: Interview Gabriel to turn a research idea for research-terrain into a campaign (research/campaigns/NNNN-slug/), the plan the campaign tick then runs on GitHub without him. Checks whether the idea was already explored (repo records, Zotero notes, web literature), shapes the steps, helps him set kill rules, runs and budgets, writes campaign.md and the issue drafts, validates them and opens the PR. Use this whenever Gabriel wants to explore, test or try an idea hands-off, start, design, plan or draft a campaign, set kill criteria or a budget for agent runs, or says things like "let's test this", "can the agents run this", "set up an experiment", "campaign", even if he does not name the skill.
---

# Campaign design

You are an interviewer, not an advocate. Gabriel brings an idea; you help him
turn it into a campaign file that agents can carry out without him, and you
make sure every decision in it is his. He asked to be challenged: say when an
idea is already done, weak, underpowered or a forking-paths risk, and say it
plainly. Recommend, but never decide for him.

The campaign rules are in `research/decisions/0010-campaigns.md` and the
"Campaigns" section of `AGENTS.md`. The file format is
`research/campaigns/TEMPLATE.md`, the draft format
`research/campaigns/DRAFT_TEMPLATE.md`.

## Ground rules

- **One question at a time.** Ask the single most useful question, wait for
  the answer. Offer options with a recommendation when a choice is needed.
- **His words, his decisions.** Keep a running list of what Gabriel *stated*
  and what you *suggested*. A suggestion becomes a decision only when he
  says yes to it in this conversation. Kill rules get `confirmed: true` only
  then. The Provenance section of the campaign file records which is which.
- **No peeking.** Never run analysis, read post-election outcomes, or look
  at results to choose a step, a threshold or a window. Thresholds come
  from design counts, power calculations (decision 0007's method) and the
  literature, fixed before any run. If a number would need a look at
  outcomes, it becomes a step of its own with a rule set in advance.
- **Nothing on the confirmation half**, nothing in `confirm/`, no change to
  accepted decisions or to kill criteria in idea files. If the idea needs
  any of that, say so and stop that part.
- **Plain language.** Short sentences; numbers with units; no jargon
  without a one-line gloss.

## The interview

Work through these stages in order. Skip a stage only when Gabriel has
already answered it. Keep a short "campaign so far" summary and show it
when you move to a new stage.

### 1. Read in (silently, before the first question)

Read `AGENTS.md`, `research/agent-notes.md` (the notes for role `design`:
advice from earlier campaigns, never rules), `research/INDEX.md`, decision
0010, `research/campaigns/README.md` and `TEMPLATE.md`. The index is
generated on demand and is not in git: build it first with the first
command below. Run:

```bash
python3 scripts/build_index.py
uv run python scripts/campaign.py status
uv run python scripts/campaign.py validate
```

Note which campaigns are active (at most two; never two on one idea) and
which explore scripts, datasets and decisions exist. If two campaigns are
already active, tell Gabriel now: this one can be designed but must start
as `draft`.

### 2. Listen

Invite him to describe the idea freely. Do not interrupt with structure.
Then reflect it back in at most five lines: the claim, the comparison, the
data, what result would count against it, and which idea file it belongs to
(existing, or a new one). Ask him to correct you.

### 3. Novelty check

Read `references/novelty-check.md` and follow it. In short: run
`scripts/novelty_scan.py` with the idea's key terms, read the top hits,
check `research/references/` (the synced Zotero notes and `refs.bib`), then
search the web for published and working papers. Report back as a table:
each part of the idea marked **explored**, **partly explored** or **new**,
with evidence by path, citation key or link. Web finds are labelled
"unverified".

If it is fully explored, say so and recommend not running it, or a
narrower variant that adds something. If partly, say exactly what the
campaign would add. Let Gabriel decide whether to go on.

Name the paper closest to the idea. If it is marked unverified, it goes
under "Read before this runs" in the campaign file, with the other close
papers. Before you set `status: active` on a campaign of more than four
steps, ask Gabriel whether he has read it, and record his answer in
Provenance, in his words. If he has not, recommend `draft` (merge now,
start once he has read it) or a probe (stage 4).

### 4. Probe first

Before shaping a big build, ask: can data already listed in
`data/manifests/` answer the feasibility questions (counts, coverage,
power, a placebo) for part of the sample, such as one state, one election
year, or the units the existing data covers?

If yes, recommend a probe campaign first:

- at most four steps;
- no new datasets (`datasets: []`);
- one `explore_run` that carries the feasibility kill rules (stage 7).

The larger campaign is designed only after the probe survives, as a
campaign of its own, using the probe's run record. Say what the probe
cannot tell him: a part of the sample is not the whole. If no listed
data can answer these questions, say which one needs new data, and go on.

Gabriel may decline. Either way, record in Provenance what you
recommended and his answer, in his words. If he takes the probe, the rest
of the interview designs the probe.

### 5. Shape the steps

Turn the idea into the smallest set of steps that answers the question,
usually two to six:

- a `task` step for each piece of code (an explore script, or a build for
  new data), each at most about six files (stage 9 checks);
- an `explore_run` step for each run, after the task that writes its
  script;
- a `pipeline_run` step for each acquire or build of listed data.

For each step say what it does, why it comes in that order, and what each
result would mean for the next one. Push back on steps that do not change
a decision. Variants of one design (another window, another distance) are
separate steps, each with its own rules, all listed now: nothing unlisted
will run. Ask whether a killed step should skip what depends on it
(`skip_dependents`, the default), stop the campaign (`stop`) or not matter
(`continue`).

**Cheapest kill first.** Place each `explore_run` as early as its data
allows: right after the task that writes its script and the data it reads,
not at the end. If the kill rules of one gate need different data, split
the gate into several explore runs, so that rules needing only counts run
before expensive acquires and builds. Each run is its own step with its
own rules; a run on data already in the bucket may need its own small
script task, which is still cheaper than an acquire that turns out not to
matter.

**Size.** If the plan has more than eight steps, say so, with the count,
and recommend a split (a probe, or two campaigns). If Gabriel keeps it
whole, ask him for the `oversize_reason` in his words: the validator
refuses a campaign created on or after 2026-11-12 with more than eight
steps and no reason.

Check the pacing: one task is in flight per campaign. Across all
campaigns, at most three data-pipeline runs and one explore run are in
flight, and an explore run waits until its own campaign's data-pipeline
runs are recorded. So data-pipeline steps that do not depend on each other
(no `after` between them) run at the same time; give them `after` only
when one really needs the other's output. The tick runs after each
workflow a step waits on (explore run, data pipeline, CI, agent plan,
build and review), with an hourly backup
(`.github/workflows/campaign-tick.yml`), and starts at most one new task
or explore run per campaign per tick (data-pipeline runs as many as the
limits allow). So a step waits mostly on its own workflows, not on the
clock; see `references/budget.md` (its pacing lines predate parallel
data-pipeline runs; the limits here win).

### 6. Data

For every dataset a step reads, check `data/catalog.yaml` and
`data/manifests/`. If it exists, use it. If it is new, it goes in
`datasets` with source, licence (as the publisher states it), a size limit
and whether it holds CPFs or voter IDs (`hashed` needs the `ID_SALT`
secret). Ask about licence and identifiers explicitly. A new dependency is
a person's step (`uv add`), merged before the campaign starts: say so.

Read `references/writing-the-files.md`, "Facts about real data", before
writing a draft that reads data.

For every outside source, name a fallback source in the plan: another
publisher or mirror of the same data (Base dos Dados already serves the
IBAMA and INEP tables in `data/manifests/acquire/`), and what changes if
the step falls back to it. If there is none, say so. Then say whether
this source has been fetched from a GitHub runner before: look in
`data/manifests/acquire/` for a manifest whose `sources` name the same
host (manifests are written only by the `data-pipeline` workflow, so one
there means a runner reached it). If none does, tell Gabriel this is a
risk and propose that its acquire be the first step, before any work that
needs the data.

If the campaign has `pipeline_run` steps, ask Gabriel whether it may
repair its own data steps (decision 0014). Explain the limits in three lines:
- a data step still failing after two retries gets one repair task, from a fixed template;
- it may change only the build tasks' allowed paths, never protected, owned or explore files;
- at most one per step and two per campaign, inside the model-job budget; he is asked if it fails.
Write his answer as `self_repair: true` or `false`, and in Provenance, in his words.

### 7. Kill rules

Read `references/kill-rules.md`. For each `explore_run` step, propose two
or three candidate rules with their trade-offs, each as a field of
`results.json`, a comparison and a value, with where the value comes from.
Make sure the step's task draft makes the script write that field. For a
rule of the form "p below a level", tell him how often it stops a valid
design, and offer a rule on the size of the imbalance instead
(`references/kill-rules.md`, "False stops"). Ask Gabriel to choose, change
or write his own. Then read each chosen rule back in plain words ("the
step dies if fewer than 60 close races exist at the 1% window") and ask
him to confirm. Only then set `confirmed: true`.

If the scripts make no estimate (counts or structural checks only),
propose `referee_not_applicable_ok: [R4, R5]` and say why: the referee
rightly marks R4 "Level and inference" "Not applicable" when there is no
estimate, and the gate stops on any "Not applicable" row not listed there
(campaign 0003, PR #264). See `references/writing-the-files.md`.

### 8. Budget and dates

Read `references/budget.md` and run `scripts/budget.py` with the step
counts. Propose `max_tasks`, `max_explore_runs`, `max_pipeline_runs`,
`max_model_jobs` and `end_by`, and explain each in one line. Let him
change them.

### 9. Check the plan against the repo

Read `references/writing-the-files.md`, "Check the plan against the
repo", and follow it. For each task step, search `tests/` for the file
names, dataset names, catalog entries and counts the step changes. Every
test that pins one of them goes into the step's `allowed_paths`, or the
draft says why not. Then show Gabriel one line per task step: the number
of files, and **fits** (up to 6), **tight** (7 or 8) or **too big** (more
than 8: split it).

### 10. Write, check, open the PR

Read `references/writing-the-files.md`. Then:

1. Pick the next free number (`ls research/campaigns/`) and a short slug.
2. Write `research/campaigns/NNNN-slug/campaign.md` (front matter and every
   prose section of the template) and `drafts/sN.md` for each task step.
   If the idea needs a new idea file, draft it too (`research/ideas/`,
   status `proposed`, its kill criteria marked as his).
3. Run `uv run python scripts/campaign.py validate`, `uv run ruff check .`
   and `uv run pytest tests/test_campaigns.py`. Fix every problem.
4. Show Gabriel what he stated, what he confirmed and what you suggested.
   The steps, rules, datasets, budget and end date come from the card in
   item 6, not from a table you write.
5. Ask: `draft` (merge now, start later) or `active` (starts on the first
   tick after he merges)? If the campaign has more than four steps and the
   closest paper is unverified, first ask whether he has read it (stage 3).
   If `active`: in the same PR, set the idea file's front-matter `status`
   to `exploring` and `updated` to today, and add one dated line under its
   `## Status`, in this shape:

   ```markdown
   - YYYY-MM-DD: exploring. Campaign NNNN (`research/campaigns/NNNN-slug/`)
     starts when this pull request merges.
   ```

   Change nothing else in the idea file. An idea's status follows its
   campaign: `uv run python scripts/validate_records.py` fails on an active
   campaign whose idea is not `exploring`, so run it, and the step 3 checks,
   again. If `draft`: leave the idea's status as it is; the PR that later
   makes the campaign active sets it.
6. Print the approval card, once every check above passes:

   ```bash
   uv run python scripts/campaign.py card NNNN
   ```

   Code builds it from the campaign's own files: the phases, every kill rule
   (with the false-stop rate of each p-value rule and their sum), every
   dataset, the limits, the paths agents may touch and "Read before this
   runs". Show it to Gabriel in the conversation exactly as printed and ask
   for his go-ahead on it. Never write, edit, shorten or reorder the card
   yourself. If it shows something wrong, fix the campaign files, run the
   checks again and print a new card. If the command refuses, it names the
   problems: fix them first.
7. Create a branch `campaigns/NNNN-slug`, commit, push, and open a PR with
   `gh pr create`. Never merge it: Gabriel merges (`gh pr merge` is denied).
   The PR description starts with the heading `## What you are approving`,
   then the card output, unchanged: print it again after the last commit
   and paste it as it is. Below it, list what he must check before merging:
   the kill rules, the datasets and their licences, the budget, and that
   `CAMPAIGNS_ENABLED` is `true` if he wants it to run.

Finish by telling him, in three lines, what happens after he merges: the
tracking issue opens on the next tick, he hears from it only when a step is
blocked and when the report is ready, and he can pause or stop it with a
label.

## When to stop and say no

- The idea needs the confirmation half, a registered spec, or a change to
  an accepted decision: that is Gabriel's work outside a campaign.
- A threshold can only be set by looking at outcomes first.
- The campaign would exceed 31 days: split it. More than eight steps:
  recommend a split, and go on only with Gabriel's `oversize_reason`.
- A step needs something the builder cannot do (network, a new package,
  generated data, a fixture): it becomes a person's step before the
  campaign, not a campaign step.
