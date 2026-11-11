# Campaigns

A campaign is a bounded series of agent tasks and runs that Gabriel approves
once, up front, and the agents then carry out without him: they file the
issues, the harness plans, builds and reviews, the gate checks, the tick
merges and runs, kill rules are applied by code, and a close-out report comes
back at the end. The rules are in `research/decisions/0010-campaigns.md` and
`AGENTS.md` ("Campaigns"); decision 0012 changes how the close-out is
accepted.

## Layout

```
research/campaigns/
  TEMPLATE.md             the campaign file, with every field explained
  DRAFT_TEMPLATE.md       an issue draft for a task step
  NNNN-slug/
    campaign.md           the plan: steps, kill rules, budget, datasets (owned)
    drafts/sN.md          one issue draft per task step (owned)
    ledger.md             written by the close-out task
    report.md             written by the close-out task
```

`campaign.md` and `drafts/` are owned in `.github/CODEOWNERS`, so no agent
can change a campaign while it runs.

## Life of a campaign

1. Design it with the `campaign-design` skill in Claude Code. The skill
   checks what is already known, interviews you, and opens a PR with the
   campaign folder.
2. Merge that PR with `status: active`; the same PR sets the idea's status to
   `exploring` (the validator refuses an active campaign whose idea is not
   exploring). The next tick opens the tracking issue. A
   tick runs after each workflow a step waits on, with an hourly backup, or
   when you run `campaign-tick` by hand.
3. The tick works through the steps in order, inside the budget: one task
   at a time per campaign. Independent data-pipeline runs go at the same
   time, at most three across all campaigns; explore runs go one at a time
   across all campaigns, and only once their campaign's data-pipeline runs
   are recorded. Each step is logged as a comment on the tracking issue. Every
   block mentions you once, with its cause and what it needs from you, and
   the ledger records when it was unblocked. A blocked step gets 24 hours,
   counted from its newest block, before the campaign closes out.
4. A run that ends 'failure' or 'timed_out' is started again by the tick on main, at most
   twice per step and only within the run limits of item 3, with one ledger line each. A
   cancelled run is never retried. After both retries a failure blocks, "Retried 2 times."
5. The circuit breaker: when 3 step blocks posted in the last 24 hours still hold, the
   tick starts nothing new in that campaign (no step, no retry, no repair) and mentions
   you once in the ledger. Work in flight and merges through the gate go on. It lifts
   by itself, with one ledger line, once fewer than 3 such blocks remain: when they are
   older than 24 hours or you clear them.
6. When nothing more can run, the tick files the close-out task. Its PR
   holds the report, the ledger, a lessons entry and the idea's new status:
   the report's recommendation (`promising`, `parked` or `dead`), with a
   status line saying so. You read it and decide. To accept it, approve the PR (Files
   changed, then Review changes, then Approve); that also accepts the
   idea's new status, and the next tick merges the commit you approved. To reject it, close the PR. Only your approval
   counts, and only on the PR's newest commit.
7. The report carries the friction facts the tick counted (blocks, extra plans and fix rounds, repeated runs, long gaps) and a section "Checks not run": every step that did not finish, every kill rule never applied, and every referee row a review marked "Not applicable", from a list the tick builds; it says "None" only when that list is empty. From the friction facts the close-out adds at most three notes and one Scoreboard row to `research/agent-notes.md` (decision 0013).
8. Every agent reads those notes as advice for its role, never as rules; checks in code are only proposed in the report, for you to batch into tasks later.
9. The close-out may not touch the harness, the workflows, `AGENTS.md` or the skills, and the notes file changes only in a close-out you approve.

## The approval card

`uv run python scripts/campaign.py card NNNN` prints one page, built by code from the campaign's files and never by a model: phases, every kill rule, new data, limits, paths and papers to read first.
The `campaign-design` skill shows it to you before you say go, and puts it unchanged at the top of the campaign PR under "What you are approving".
p-value kill rules carry their false-stop rate, and the card adds them up for the campaign; if the card looks wrong, the plan is wrong.

## Self-repair of data steps

A campaign file may say `self_repair: true` (decision 0014; the default is
false). Then a `pipeline_run` step whose run still fails after both retries
gets one repair task: the tick files an issue from a fixed template, with
the failed job's last log lines as data and, as the only files it may
change, the allowed paths of the build tasks the step comes after (never a
protected or owned path, never explore code). The planner, builder and
reviewer work it like any task, the gate checks it against the template,
and the tick merges it and runs the step once more. You are asked only if
the repair blocks or the run after it fails ("Retried 2 times, repaired
once."). At most one repair per step and two per campaign; their model jobs
count against the budget, and the close-out lists each one. Explore runs
are never repaired. A log cut to fit says so on its first line, for example
"(cut: the last 59 of 412 lines)". The planner and builder read the log;
the agent review of the repair gets the issue with the log replaced by one
line, so text printed by an outside server never reaches the agent that
judges the fix.

## The status page

One issue, titled "Research Terrain: status", shows on one page where every
campaign stands. The tick keeps it up to date in plain code, with no model:
it renders the page from the same facts it acts on and rewrites the issue
only when the page changes, so a tick with nothing new leaves it alone. The
page has five parts, in this order:

1. Waiting on you: every step whose block still holds (its cause and what
   to do), every close-out PR that is ready for your approval, every
   paused campaign and every campaign held by the circuit breaker.
   "Nothing" when nothing waits.
2. Running: each active campaign, its steps done, what is in progress,
   the last ledger event, model jobs used and the end date.
3. Handled without you: the newest 10 automatic retries, repairs and
   unblocked steps, across campaigns.
4. Recently closed: the 5 campaigns that finished last, how each ended and
   its report.
5. Loose ends, from the files on main: ideas still `proposed` or
   `exploring` after their campaigns finished, and decisions still
   `proposed`.

Times on the page are those of ledger comments. A list cut to keep the page
under 20,000 characters ends with how many items were left out. Keep the
issue open and its `campaign` label on; if it is closed, the tick files a
new one. To read the page locally without waiting for a tick:
`GH_TOKEN=$(gh auth token) uv run python scripts/campaign.py page`.

## Controls

| To | Do |
| --- | --- |
| Pause one campaign | Add `campaign-pause` to its tracking issue |
| Stop one campaign | Add `campaign-stop`, or close the tracking issue |
| Stop everything | Set the repository variable `CAMPAIGNS_ENABLED` to `false` |
| Unblock a step | Do what the block comment's "Needs you" says (for example remove `needs-human` or re-add `agent-plan`); the next tick picks it up and logs "unblocked". For a failed run: if the cause was outside the code (a server error, a timeout, an export still running), open the run and choose Re-run failed jobs. If a fix was merged since the run started, a re-run would use the old code: open the Actions tab, choose the workflow, choose Run workflow on main, and enter the values the block comment gives |
| Accept the report | Approve the close-out PR (Files changed, then Review changes, then Approve); the next tick merges that commit |
| Reject the report | Close the close-out PR |
| See where it is | The issue "Research Terrain: status"; for one campaign, its tracking issue and `uv run python scripts/campaign.py status` |
