# Issue drafts

Ready-to-file agent tasks. Create one with

    gh issue create --title "<first line without '# '>" --body-file <file>

then add the `agent-plan` label. File them in order; each depends on the one
before it being merged and, where it reads data, on the data having been
acquired or built (its manifest merged into `data/manifests/`).

| Draft | Task | Needs first |
| --- | --- | --- |
| 01 | Storage and manifest helpers | done (#6) |
| 02 | Acquire TSE candidates | done (#11) |
| 03 | Build the candidates table | `acquire/tse_candidates` manifest (merged) |
| 04 | Catalog-driven acquirer and five new acquisitions | 02 merged |
| 05 | Municipalities and TSE-IBGE crosswalk | 03 built; `ibge_municipalities` and `polling_stations_geocoded` acquired |
| 06 | Results: votes, party votes, turnout, coalitions | 05 built; `tse_results` acquired |
| 07 | Section votes and polling places | 06 built; sections and polling places acquired |
