# 0003: Where confirmation-half rows live

Date: 2026-11-02. Status: proposed (decide before any outcome data is built).

## The question

Decision 0001 leaves open whether rows for confirmation-half municipalities
ever sit in `data/derived/`, where exploration jobs can read them. Today the
protection is procedural: explore scripts must filter to the exploration
half (`terrain.explore.restrict`, enforced by a test and by review), but the
`analysis` account could read every row.

## Options

| Option | What it means | Protects | Costs |
| --- | --- | --- | --- |
| A. Procedural only (today) | All derived tables hold every municipality; explore code filters | Honest mistakes caught by test and review | A bug or a careless script can look at confirmation outcomes |
| B. Split everything | Every derived table is written twice: exploration rows to `data/derived/`, confirmation rows to `sealed/` | The confirmation half is unreadable to exploration | Every build changes; cross-table joins and the crosswalk need both halves; much more machinery |
| C. Split outcomes only | Treatment-side tables (candidates, results, sections, polling places, municipalities) stay whole; outcome tables (land use, deforestation, anything the hypotheses predict) are written split, with confirmation rows only in `sealed/` | Exactly what forking paths can exploit: outcomes in the confirmation half | One extra write path in outcome builds, and a create-only grant for the build account on `sealed/outcomes/` |

## Proposal: C

Garden-of-forking-paths risk comes from seeing outcomes, not from seeing who
ran for council where. Close pairs and strongholds must be defined on the
whole sample anyway (a municipality's design does not depend on which half it
is in), and the crosswalk needs every municipality. Outcomes are where a
glance changes what gets tried next.

What C requires, when the first outcome build is written:

1. `scripts/gcp/setup_gcs.sh`: grant `terrain-build` create-only on
   `sealed/outcomes/`, and `terrain-unblind` read on it; `terrain-analysis`
   gets nothing there.
2. Outcome builds write `data/derived/<name>/<hash>/...` from exploration rows
   and `sealed/outcomes/<name>/<hash>/...` from confirmation rows, and record
   both in the manifest.
3. `confirm-run` reads both halves; `explore-run` cannot.

To accept: change the status above to "accepted" and the date, in a PR.
