---
id: "0011"
title: "The geography of representation: national scope and split"
status: accepted
date: 2026-11-10
supersedes: null
---

# 0011: The geography of representation: national scope and split

Date: 2026-11-10. Status: accepted (Gabriel, 2026-11-10, with the four
choices in PR #280: 2010 population on 2022 boundaries, terciles within each
state, the 5,571-row DTB 2024 list, and the note on raw data below). Drafted
by Claude for Gabriel from his instructions of 2026-11-10.

## The question

Idea 0006 (the geography of representation) asks whether narrow council
winners' own voters' places get more of the state during the term. Its
outcomes (municipal school equipment, night lights, built-up area, native
vegetation) exist for the whole country, and the Legal Amazon alone has too
few municipalities with school polling places to answer it. Decision 0001
split only the 773 Legal Amazon municipalities. How can idea 0006 use the
whole country while the exploration/confirmation split still holds?

## Decision

1. **Scope.** Idea 0006 covers every municipality in IBGE's territorial
   division 2024 (DTB 2024), the list the `municipalities` build uses:
   5,571 rows, of which 773 are in the Legal Amazon and 4,798 are not.
   (Brazil is usually counted as 5,570 municipalities. The 5,571st row is
   Boa Esperança do Norte (MT, 5101837), created after the 2022 census and
   in the Legal Amazon, so it changes nothing below.) Brasília (DF) holds no
   council elections; it is in the split and simply never has a close pair.
2. **The Legal Amazon keeps its split.** The 773 Legal Amazon municipalities
   keep the sealed assignment of decision 0001: `sealed/split/split.csv`,
   its hash `confirm/split.sha256` and the exploration list
   `data/derived/split/explore_municipalities.csv` do not change.
3. **The rest get a new split, drawn once.** The 4,798 municipalities
   outside the Legal Amazon are split 50/50 into an exploration half and a
   confirmation half by the same procedure as decision 0001:
   `scripts/seal_split.py` with a system random source and no seed, run
   once by Gabriel, so it cannot be regenerated or tuned.
4. **Stratified by state and population tercile.** Within each state, the
   municipalities are ranked by population (ties by IBGE code) and cut into
   three terciles of sizes differing by at most one; each state-by-tercile
   group is a stratum. In each stratum half go to each side; when a stratum
   is odd, the extra one is decided by the random source
   (`terrain.split.stratified_split`, unchanged). Population is the 2010
   census count on 2022 boundaries ("População 2010 (Alterações de Limites
   até 2022)") from IBGE's table `CD2022_Populacao_2010_Compatibilizada`:
   a count from before every election idea 0006 studies except 2008,
   available for all 4,798 municipalities. Terciles are within the state,
   not national, so that every state has all three strata.
5. **Sealed and hash-committed like decision 0001.** The full split goes to
   `gs://research-terrain/sealed/split/split_non_amazon.csv`; the exploration
   list to `data/derived/split/explore_municipalities_non_amazon.csv`; only
   the SHA-256 is committed, as `confirm/split_non_amazon.sha256`. The
   exploration half of idea 0006 is the union of the two exploration lists;
   its confirmation half is the union of the two confirmation halves.
6. **Before any outcome data for them exists in a readable place.** The
   split is drawn before any outcome table covering municipalities outside
   the Legal Amazon is built, and before any acquire that idea 0006 adds.
   Today the only outcome data that touches them is raw and unread (see
   "What exists today").
7. **Idea 0001 is untouched.** Its registered plan (`confirm/pap/`,
   `confirm/specs/`), its confirmation half and every run in
   `confirm/ledger/` stay as they are; the confirmation runner keeps
   reading only `split.csv` for it.

## What exists today

Checked on 2026-11-10, from `data/manifests/` on main:

- **Treatment side, whole country:** `tse_results`, `tse_candidates` and the
  `municipalities` table cover all of Brazil. Decision 0003 allows this:
  close pairs are defined on the whole sample.
- **MapBiomas deforestation, raw only:** `mapbiomas_deforestation` was
  exported for the Legal Amazon's bounding box (longitude -74 to -43,
  latitude -18.5 to 5.5), which also covers parts of GO, PI, BA, MS, MG and
  the Maranhão municipalities outside the Legal Amazon (36 by IBGE's
  counts). It sits in
  `data/raw/`, which no exploration account can read; `cell_outcomes`, the
  only table built from it, holds Legal Amazon cells only.
- **IBAMA fines and embargoes, raw only:** acquired for the nine Legal Amazon
  states, so they include the non-Amazon part of Maranhão, in
  `data/raw/` only; `cell_enforcement` is built for Legal Amazon cells.
- No explore run, figure or derived table has ever held an outcome for a
  municipality outside the Legal Amazon.

The split uses no outcome: only the state and the 2010 population.

## What it needs

- A new raw dataset, `ibge_population_2022` (the IBGE table above), and a
  new build, `non_amazon_municipalities`, which writes `non_amazon.csv`
  (`code_ibge,uf,population`) for the 4,798, the input to the draw. Both are
  in the pull request that adds this decision.
- `terrain.split.population_strata` and `seal_split.py --non-amazon`, in the
  same pull request. `stratified_split` and the Legal Amazon mode of
  `seal_split.py` are unchanged.
- Later, before idea 0006's first explore run (Gabriel's changes, owned):
  `terrain.explore` must read both exploration lists for idea 0006, and
  any confirmation run of idea 0006 must read both sealed files and check
  both hashes. Neither is needed to draw the split.
- Outcome builds for idea 0006 follow decision 0003 option C: exploration
  rows in `data/derived/`, confirmation rows only in `sealed/outcomes/`.

## Cost

The confirmation half of idea 0006 is about 2,786 municipalities (about 386
from the Legal Amazon plus about 2,399 others), and the exploration half the
same. A second sealed file and hash add one more thing that can go wrong in
a confirmation run; the runner must check both.
