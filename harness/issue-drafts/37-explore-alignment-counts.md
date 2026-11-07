# Task: aligned and unaligned close pairs at 0.25% (explore, idea 0004)

## Goal

Idea 0004 (`research/ideas/0004-mayor-alignment.md`) asks whether the
direct effect of a narrow council win differs between councillors aligned
with the elected mayor and councillors who are not. Its drafted kill
criterion 1 needs at least 200 aligned and 200 unaligned close pairs.
**This task counts aligned, unaligned and mixed close pairs at decision
0008's 0.25% window**, per election, on the exploration half. It also
prints a rough implied power for the moderation test from those counts. It
reads no outcome data and computes no effect. The script computes exactly
what this issue lists and nothing more (referee R7).

**Outcome data in scope (for referee R2): none.** No `cell_outcomes`,
`cell_exposure` or `cell_displacement` file is read.

## Idea

`research/ideas/0004-mayor-alignment.md` (Design, kill criteria 1 and 3,
drafted); decisions 0001 (split), 0007 (effect size) and 0008 (window,
power at 0.25%). Alignment is within one election only, so no party-lineage
table is used (PR #213 is not merged and must not be read). This is an
explore task (label `explore`): it may change only `explore/` and
`tests/test_explore*`.

Read first: `src/terrain/strongholds.py` (`main_election`,
`candidacy_votes`, `within_list_pairs`, `valid_votes`, `margins`),
`explore/0003_mayor_power.py` (`deciding_round`, `candidacy_votes_mayor`,
`CV_COLUMNS`), `explore/0001_window.py` (`load_candidates`, `with_ibge`) and
`explore/0001_feasibility_census.py` (`_paths`), and the contracts
`tse_results`, `tse_candidates` and `tse_parties` in `data/contracts/`. Load
the explore scripts with importlib, as `explore/0001_window.py` loads its
dependencies, and reuse those functions. Do not change any existing script.

## Definitions

- **Elections** E = 2008, 2012, 2016, 2020, 2024. `main =
  strongholds.main_election(candidate_votes)`: 30, 47, 220, 426, 619
  (profiled). Supplementary elections are not used.
- **Close pairs.** `margins(within_list_pairs(candidacy_votes(cv, E, main)),
  valid_votes(turnout, main))`, non-inverted, |margin| ≤ 0.0025 + 1e-12, as
  `explore/0001_window.py` builds them. Each pair has an elected side
  (`elected_sq`) and an other side (`other_sq`).
- **Each council side's party**: `nr_partido`, and in 2024 `nr_federacao`,
  from `tse_candidates` (`cd_cargo` 13, the same `cd_eleicao`, `sg_ue` and
  `sq_candidato`; `cd_ibge` added as in `load_candidates`). Read only
  `ano_eleicao`, `cd_eleicao`, `nr_turno`, `cd_cargo`, `sg_ue`,
  `sq_candidato`, `nr_partido`, `sq_coligacao` and `nr_federacao`. A side
  with no match or a null `nr_partido` is counted per year, and its pair is
  left out.
- **The elected mayor.** The deciding round as `deciding_round` (round 2
  under `main + 1` where the municipality has mayoral rows there, else round
  1 under `main`); votes per candidacy as `candidacy_votes_mayor`. The mayor
  is the first candidacy by votes (ties broken by `sq_candidato`, counted),
  including municipalities with one candidacy. A mayor whose
  `ds_sit_tot_turno` is not `ELEITO` is counted per year and kept.
- **The mayor's coalition.** The mayor's main-election candidacy in
  `tse_candidates`: `cd_cargo` 11, `cd_eleicao` = `main`, same `sg_ue` and
  `sq_candidato` (`sq_candidato` is the same in both rounds in the raw TSE
  files, 2008, 2016 and 2024 profiled). Its `sq_coligacao` and `nr_partido`.
  The coalition's parties are the `tse_parties` `coalitions_<E>` rows with
  `cd_cargo` 11, `cd_eleicao` = `main`, the same `sg_ue` and `sq_coligacao`
  (compared as text); the mayor's own `nr_partido` is always included. In
  2024, the coalition's federations are the non-null `nr_federacao` values
  of those rows and of the mayor's own row. Counted per year: mayors with no
  main-election candidacy row (their municipality's pairs are left out), and
  mayors whose `sq_coligacao` has no coalition rows (their own party is the
  coalition).
- **Aligned side**: its `nr_partido` is in the coalition's parties, or (2024
  only) its non-null `nr_federacao` is in the coalition's federations.
- **Pair type**: aligned (both sides aligned), unaligned (neither), mixed
  (one side). Mixed pairs are counted and left out of the contrast. From
  2020 lists are parties or federations, so mixed pairs should be rare; they
  are counted, not dropped silently.
- **Implied power** (rough, not a computation on outcomes). Decision 0008
  gives the direct effect's power at 8% as 0.868 on 2,328 pairs at 0.25%
  (2008-2020). With K = 1.96 + Φ⁻¹(0.868), and assuming each group's slope
  has variance proportional to 1 / its pairs, the power to detect an
  aligned-minus-unaligned gap of one effect size, two-sided 5%, is
  Φ(K · √((1/2,328) / (1/n_a + 1/n_u)) − 1.96), with n_a and n_u the aligned
  and unaligned pairs of 2008-2020. Print it with the formula and the
  constants. Also print the same formula for an even split (n_a = n_u =
  2,328 / 2) as the best case.

## What to report

`summary.md`:
1. First line: aligned, unaligned and mixed pairs pooled 2008-2024; whether
   drafted kill criterion 1 (200 each) is met; the implied power.
2. Table per election and pooled (2008-2024 and 2008-2020): close pairs,
   aligned, unaligned, mixed, left out (side not matched; mayor not
   matched).
3. Counts: deciding rounds that were run-offs; mayoral ties; mayors not
   `ELEITO`; mayors without a main-election row; coalitions with no rows;
   sides not matched.
4. The implied power, its formula and constants, and the even-split best
   case.
5. Caveats: exploration half; alignment is fixed by the mayoral race, not
   randomised; the power is a rough scaling of decision 0008's direct
   power, not a computation; no lineage across elections.

`results.json`: every number above.

## Expected (a mismatch is a stop, not a result)

- Close pairs per election equal decision 0008's at 0.25%: 478, 578, 596,
  676 and 541 (2008-2024), 2,869 pooled; 2,328 in 2008-2020.
- Aligned + unaligned + mixed + left out = close pairs, in every election.
- Left out, of either kind, at most 5% of the close pairs in every election.

## In scope

Expected files (two): `explore/0004_alignment_counts.py`,
`tests/test_explore_alignment_counts.py`.

## Out of scope

Any outcome or exposure table; any estimate of an effect or a difference;
alignment with any mayor other than the one elected in the same election;
party lineage across elections (`data/reference/`); ideology or any other
moderator; changes to other explore scripts; the idea file (written from
the record); `sealed/` and `confirm/`. No CPF or voter ID column is read
(the columns above exclude them).

## Done when

1. Pairs: on synthetic council rows, the close pairs at 0.25% are those of
   `strongholds` with |margin| ≤ 0.0025 (a pair at exactly 0.25% is in, one
   at 0.26% and an inverted one are out).
2. Mayor: a run-off municipality takes the round-2 first candidacy; others
   the round-1 first; a one-candidacy municipality has a mayor; a tie is
   broken by `sq_candidato` and counted.
3. Coalition: on a synthetic coalitions table, the parties are those of the
   mayor's `sq_coligacao` for `cd_cargo` 11 only (a council coalition row
   with the same `sq_coligacao` text is not used); the mayor's own party is
   included when its coalition has no rows, and that is counted.
4. Alignment: a pre-2020 list with one side in the coalition and one not is
   mixed; both in is aligned; neither is unaligned. In 2024, a side whose
   party is not in the coalition but whose federation is counts as aligned.
5. Sides or mayors not matched are counted, and their pairs left out, never
   counted as unaligned.
6. Implied power: for n_a = n_u = 1,164 it equals Φ(K/2 − 1.96) with K as
   above (about 0.34), and it falls as either count falls.
7. No outcome, exposure or displacement file is read (a fake store sees no
   such path), and `results.json` has no key for an estimate.
8. Every table read is restricted to the exploration half (the existing
   explore test passes); `uv run ruff check .`, `uv run ruff format --check .`
   and `uv run pytest` pass.
