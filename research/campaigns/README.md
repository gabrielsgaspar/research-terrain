# Campaigns

A campaign is a bounded series of agent tasks and runs that Gabriel approves
once, up front, and the agents then carry out without him: they file the
issues, the harness plans, builds and reviews, the gate checks, the tick
merges and runs, kill rules are applied by code, and a close-out report comes
back at the end. The rules are in `research/decisions/0010-campaigns.md` and
`AGENTS.md` ("Campaigns").

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
2. Merge that PR with `status: active`. The next tick (every three hours, or
   run `campaign-tick` by hand) opens the tracking issue.
3. The tick works through the steps in order, one at a time, inside the
   budget. Each step is logged as a comment on the tracking issue.
4. When nothing more can run, the tick files the close-out task. Its PR
   holds the report, the ledger, a lessons entry and a status line for the
   idea. You read it, decide, and merge it.

## Controls

| To | Do |
| --- | --- |
| Pause one campaign | Add `campaign-pause` to its tracking issue |
| Stop one campaign | Add `campaign-stop`, or close the tracking issue |
| Stop everything | Set the repository variable `CAMPAIGNS_ENABLED` to `false` |
| Unblock a step | Fix the cause and restart it as you would by hand (remove `needs-human`, re-add `agent-build`, or re-run the workflow); the next tick picks it up |
| See where it is | `uv run python scripts/campaign.py status`, and the tracking issue |
