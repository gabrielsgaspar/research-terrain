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
2. Merge that PR with `status: active`. The next tick opens the tracking issue. A
   tick runs after each workflow a step waits on, with an hourly backup, or
   when you run `campaign-tick` by hand.
3. The tick works through the steps in order, one at a time, inside the
   budget. Each step is logged as a comment on the tracking issue. Every
   block mentions you once, with its cause and what it needs from you, and
   the ledger records when it was unblocked. A blocked step gets 24 hours,
   counted from its newest block, before the campaign closes out.
4. When nothing more can run, the tick files the close-out task. Its PR
   holds the report, the ledger, a lessons entry and a status line for the
   idea. You read it and decide. To accept it, approve the PR (Files
   changed, then Review changes, then Approve); the next tick merges the
   commit you approved. To reject it, close the PR. Only your approval
   counts, and only on the PR's newest commit.

## Controls

| To | Do |
| --- | --- |
| Pause one campaign | Add `campaign-pause` to its tracking issue |
| Stop one campaign | Add `campaign-stop`, or close the tracking issue |
| Stop everything | Set the repository variable `CAMPAIGNS_ENABLED` to `false` |
| Unblock a step | Do what the block comment's "Needs you" says (for example remove `needs-human`, re-add `agent-plan`, or re-run the workflow); the next tick picks it up and logs "unblocked" |
| Accept the report | Approve the close-out PR (Files changed, then Review changes, then Approve); the next tick merges that commit |
| Reject the report | Close the close-out PR |
| See where it is | `uv run python scripts/campaign.py status`, and the tracking issue |
