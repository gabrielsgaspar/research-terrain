# Novelty check

Goal: before any design work, tell Gabriel what is already known about the
idea, in three tiers, each reported separately so he can see where every
claim comes from. Spend proportionate effort: a variant of a running idea
needs mostly tier 1; a new research question needs all three.

## Tier 1: this repository (authoritative)

Run the scan with four to eight key terms (nouns, dataset names, methods,
the idea id if known), in English and, where the data uses them,
Portuguese:

```bash
uv run python .claude/skills/campaign-design/scripts/novelty_scan.py mayor prefeito "close race" runoff 0003
```

It ranks files by how many terms they match and prints the matching lines.
Then read, in this order: the idea files it points to (front matter status
and kill criteria first), their `## Status` logs, the lessons entries, the
explore-run records (the `.md` summary, then the `.json` if a number
matters), decisions, other campaigns and their reports, and
`research/questions.md`. Check `explore/` for scripts on the same question.

What to look for:

- an idea file on the same claim, and its status (dead ideas are results:
  say why it died);
- explore runs that already computed the quantity (cite run id and path);
- a decision that already fixes a definition (exposure, outcome, effect
  size, window) the idea would want to change: changing it is out of scope
  for a campaign;
- a lesson that warns against the approach.

## Tier 2: the Zotero library (curated)

`research/references/` holds a note per key paper (`<citekey>.md`) and
`refs.bib`, synced from the `terrain` Zotero library by the `zotero-sync`
workflow. The scan above already covers them; read the relevant notes in
full. For each relevant paper, say what it shows and what it means for the
idea, citing the key. The `terrain-inbox` library is not synced: you cannot
see it, so ask Gabriel whether he has something there.

## Tier 3: the web (unverified)

Use web search for published and working papers (journals, NBER, SSRN,
authors' pages) on the same question, the same design in another country,
and the same data. Two to six searches are usually enough. For each find
give authors, year, title, venue and a link, and one line on how close it
is.

Rules:

- Label every web find **unverified** until Gabriel or a synced note
  confirms it. Never cite one as a fact in the campaign file; cite it as
  "found on the web, to check".
- Never invent a paper, a finding or a link. If you are not sure what a
  paper says, say so.
- Suggest which finds Gabriel may want to add to `terrain-inbox`. You
  cannot add them yourself.

## Reporting

One table, then two or three sentences of judgement:

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Close mayoral races have power at the municipality level | explored | run 42367009833 (`research/explore-runs/0003/42367009833.md`) |
| Alignment with the mayor changes clearing | new | no idea, run or note on it; nearest is `fivaLocalFavoritismAtlarge2016` |
| Same design in another country | partly explored | (web, unverified) authors, year, link |

Verdicts: **explored** (the repository or the literature already answers
it), **partly explored** (answered for a neighbouring case or with a
different method), **new**. Then recommend one of: go on; go on with a
narrower question (say which); stop. Gabriel decides.

## Read before this runs

Name the paper closest to the idea, and any other close one. They go in
the campaign file's "Read before this runs" section: citation key, or
authors, year and link for a web find, and whether Gabriel has read each,
in his words.

If the closest paper is marked unverified, it must be listed there. Before
setting `status: active` on a campaign of more than four steps, ask him:

> The closest paper I found is (authors, year, link), unverified. Have you
> read it?

Record his answer in Provenance, in his words. If he has not, recommend
`draft` (merge now, start once he has read it) or a probe (SKILL.md,
"Probe first"), because a close paper can make most of the steps moot.
He decides.
