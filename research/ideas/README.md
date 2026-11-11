# Ideas

One file per research idea. Copy `TEMPLATE.md` to start a new one.

`research/INDEX.md` lists every idea and its status, and for a dead or
parked idea the newest line of its Status log. The idea file is the source
of truth; the index is generated from it on demand and is not in git. To
build it, run `python3 scripts/build_index.py`.

An idea's status follows its campaign (`research/campaigns/README.md`): it
is `exploring` while a campaign on it is active, and the campaign's
close-out sets the report's recommendation (`promising`, `parked` or
`dead`), which Gabriel accepts by approving the close-out PR.
`scripts/validate_records.py` fails on drift. Campaigns before 0005 are not
checked: their close-outs left the status to Gabriel.
