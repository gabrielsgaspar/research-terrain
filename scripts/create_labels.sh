#!/usr/bin/env bash
# Create the labels used by the agent workflow and the research notebook in
# the current repository. Safe to run twice: `--force` updates a label that
# already exists instead of failing. Needs the `gh` CLI, logged in with write
# access to the repo.
#
#   bash scripts/create_labels.sh
set -euo pipefail

label() {
  gh label create "$1" --description "$2" --color "$3" --force
}

label agent-plan "Ask the planner agent for a plan comment on this issue (read-only)" 1d76db
label agent-build "Ready for an agent to build; a human has approved the plan" 0e8a16
label needs-human "An agent stopped or is unsure; a person must decide" d93f0b
label agent-approved "The agent reviewer found nothing to fix on the current commit; a person still reviews and merges" 5319e7
label idea "A research idea under discussion" fbca04
label data "Acquiring or building a dataset" c5def5
label explore "Exploration on the exploration half" bfdadc
label campaign "Part of a campaign (research/campaigns/); filed and moved by the campaign tick" 6f42c1
label campaign-pause "On a tracking issue: the campaign tick does nothing for this campaign" fbca04
label campaign-stop "On a tracking issue: no new steps, no merges; the close-out task is filed" b60205
