"""Campaigns: a bounded, pre-approved series of agent tasks and runs.

A campaign file (`research/campaigns/NNNN-slug/campaign.md`) lists the steps
Gabriel approved, their kill rules and the budget. The tick
(`scripts/campaign.py decide`) advances each active campaign one step at a
time through the existing harness; the gate (`scripts/campaign.py gate`)
decides whether an agent pull request may be merged. Decision 0010
(`research/decisions/0010-campaigns.md`) is the rule set.

Everything here is plain code: no model, no network in the pure modules.
`terrain.campaigns.github` is the only module that talks to GitHub.
"""
