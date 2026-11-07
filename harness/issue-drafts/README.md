# Issue drafts

Ready-to-file agent tasks. Create one with

    gh issue create --title "<first line without '# '>" --body-file <file>

then add the `agent-plan` label. First check it has not been filed already:
`gh issue list --state all --search "<title words>"`. File them in order; each depends on the one
before it being merged and, where it reads data, on the data having been
acquired or built (its manifest merged into `data/manifests/`).

| Draft | Task | Needs first |
| --- | --- | --- |
| 01 | Storage and manifest helpers | done (#6) |
| 02 | Acquire TSE candidates | done (#11) |
| 03 | Build the candidates table | done (#18) |
| 04 | Catalog-driven acquirer and five new acquisitions | done (#26) |
| 05 | Municipalities and TSE-IBGE crosswalk | build `tse_candidates` merged (done) |
| 06a | Candidate votes and turnout | 05 built; `acquire/tse_results` merged |
| 06b | Party votes and coalitions | 05 built; `acquire/tse_results` merged |
| 07a | Located polling places | 05 built |
| 07b | Section votes linked to candidacies | 06a built |
| 08 | Candidates build tolerates invalid birth dates | done (#21) |
| 09 | Type every polling place (seat, town, rural, ...) | `uv add shapely pyshp`; `ibge_localities` and `ibge_urbanized_areas` acquired |
| 10 | Feasibility census (explore) | `polling_place_types` built and recorded |
| 11 | Front matter for records, and a validator | — |
| 12 | Generated `research/INDEX.md` | 11 merged |
| 13 | Acquire ArcGIS-portal files (public-forest register) | done (#79) |
| 14 | Polling-place distances to indigenous land, settlements, undesignated forest | done (#82) |
| 15 | Kill criterion 1 for idea 0001 (explore) | done (#85) |
| 16 | Acquire the census grids, basemap and 2024 boundaries | done (#91) |
| 17 | Simplified map layers for the figures (`figure_layers`) | done (#100) |
| 18 | Figures 1 (study area) and 2 (polling places) | done (#105) |
| 19 | Legal Amazon 1 km cells with population and tenure (`grid_cells`) | done (#101) |
| 20 | Figure 3 (2022 population per cell, with tenure) | done (#115) |
| 21 | Exposure formulas compared for decision 0004 (explore) | done (#116) |
| 22 | Zotero sync: `refs.bib` and note stubs | done (#110) |
| 23 | Figure 5 (empty cells over undesignated forest) | done (#120) |
| 24 | Cell exposure to close races (`cell_exposure`, decision 0004) | done (#125) |
| 25 | Figure 6: one close pair's strongholds over their exposure | `cell_exposure` recorded (done) |
| 26 | Acquire MapBiomas code shares per 1 km cell (Earth Engine, decision 0006) | `earthengine-api` and `tifffile` merged (done) |
| 28 | Explore scripts import `terrain.strongholds` (explore) | done (#159) |
| 29 | Displacement-exposure formulas compared for decision 0005 (explore) | `cell_exposure` recorded (done) |
| 30 | Unrepresented cells' exposure (`cell_displacement`, decision 0005) | done (#174) |
| 31 | MapBiomas acquisition resumes earlier exports | task 26 merged (done) |
| 32 | Pre-election placebo, kill criterion 2 (explore) | cell_outcomes available (done; #189) |
| 33 | Minimum detectable effects for decision 0007 (explore) | placebo recorded (done; #194) |
| 34 | Main exploration, kill criteria 3 and 4 (explore) | decision 0007 accepted (done) |
| 35 | Close-race window by covariate balance (explore) | done (#212; record #219, decision 0008) |
| 36 | Close mayoral races: power at the municipality level (explore, idea 0003) | done (#216; record #217) |
| 37 | Aligned and unaligned close pairs at 0.25% (explore, idea 0004) | done (#223, #226, fix #231; record #232) |
| 38 | Kill criterion 1 at the 0.25% window (explore, idea 0001) | done (#224, #225; record #228) |
| 39 | Validate the registered analysis against run 42298466207, at 0.50% (explore, idea 0001) | PR #236 merged; script already in it, so no agent build |

## Before filing a task

1. Search: `gh issue list --state all --search "<title words>"`.
2. If it reads real data, profile the real files first (every column the
   task names exists in the file it names; values a build will reject;
   keys; row counts) and put the numbers in the task. Fixtures are
   anonymised and can hide defects.
3. Everything it needs exists: dependencies added by a person, fixtures
   committed, input manifests merged.
4. It asks only for what the builder can do (AGENTS.md, "What the builder
   can do"). Anything else is a step for a person, done first.
5. "Done when" items are checkable on fixtures or inputs built in the test,
   and say exactly which parts of anything they mirror.
6. Size: at most about ten files changed. Split larger work.
7. A task that reports a kill-criterion verdict states the condition as
   the idea writes it ("met if fewer than 200 ..."), and its Done when has
   one case each way (harness lesson of 2026-11-07, PR #226).
8. After editing a draft, update the issue (`gh issue edit N --body-file
   ...`) before adding `agent-plan`.

## Before building a plan

- **Files to change:** one full path per bullet, deletions included, no
  braces or globs.
- Nothing under protected paths, `pyproject.toml` or `uv.lock`.
- Every step uses only the builder's commands.
- The "Done when" list matches the issue's.

## Before merging a workflow change

- Run each inline script under bash with sample inputs, and run
  `actionlint`.
- After merging, start a new run (Run workflow or `gh workflow run`);
  re-running an old run uses the old workflow.
