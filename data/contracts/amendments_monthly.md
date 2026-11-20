# amendments_monthly

One row per cycle, federal deputy, municipality and month, for the rows of `amendments_panel`:
the deputy's individual amendment payments to the municipality in that month. Idea 0011 (H6),
decisions 0003 and 0011. Built by `src/terrain/builds/amendments_monthly.py` (owner PR
"mayoral incumbency panel"; run in campaign 0012).

## Inputs

The same as `amendments_panel` (`data/contracts/amendments_panel.md`), without the vote files:
`tse_general` (`consulta_cand_<year>.zip` of t0-4 and t0 only), `cgu_amendments`,
`tse_results` (the mayoral year m), `tse_candidates`, `municipalities`, `camara_deputies` and
the two exploration lists.

## Rows

The rows of a cycle are exactly the panel's (`cycle`, `deputy`, `cd_ibge`): the same
deputies, the same author link and the same municipalities, computed by the same code
(`amendments_panel.cycle_link` and `amendments_panel.panel_keys`). Each appears once per
month from January of m-1 to October of t1:

| cycle | first month | last month | months |
| --- | --- | --- | --- |
| A | 2015-01 | 2018-10 | 46 |
| B | 2019-01 | 2022-10 | 46 |
| C | 2023-01 | 2026-10 | 46 |

## Output and split

`monthly_<cycle>.parquet`, sorted by `deputy`, `cd_ibge`, `ym`. Rows of exploration-half
municipalities go to `data/derived/amendments_monthly/<hash>/`; every other row goes only to
`sealed/outcomes/amendments_monthly/<hash>/`, which the build creates in and never reads.
`<hash>` is `content_hash` of the sorted input SHA-256s, the SHA-256s of the two lists, the
cycles with their months and the source of this build and of the `terrain` modules it
imports (`amendments_panel`, `parties`, `explore`, `place_outcomes`, `cell_outcomes`,
`polling_place_tenure`).

## Columns

| Column | Type | Meaning |
| --- | --- | --- |
| `cycle` | text | `A`, `B` or `C` |
| `deputy` | text | t0 `sq_candidato`, as in `amendments_panel` |
| `cd_ibge` | text | 7-digit IBGE code |
| `ym` | int | the payment month, YYYYMM |
| `amend_total` | float | reais, nominal: the deputy's individual payments to the municipality in the month |
| `amend_pix` | float | the same, Pix (`TRANSFERENCIAS ESPECIAIS`) only |
| `n_pay` | int | payment rows in the month, negative ones included |

Payments follow `amendments_panel`: individual amendments by payment month, the recipient
matched to a municipality, the author linked to the deputy by the cycle's author link (a
linked author's payments in every month count, also between the panel's windows). Negative
rows are summed with the rest; a month whose total is below 0 is set to 0 and counted. The
months of a panel window add up to the panel's window sums, except where a month was set to
0 (the panel floors the window, this table the month).

## Checks the build enforces

Each raises `BuildError` with counts only, before anything is uploaded.

1. A duplicate (`cycle`, `deputy`, `cd_ibge`, `ym`).
2. Rows of a cycle other than its panel rows times its months.
3. A payment column below 0 (after the floor, as a guard), or a month with more Pix than total.
4. Fewer than 5,000 or more than 300,000 panel rows in a cycle (the panel's bounds).
5. The CGU rules of `amendments_panel` (month range, Pix, formats, the 2% recipient rule) and
   its input checks.

## Manifest notes

Per cycle: exploration-half rows and panel rows, the months, the deputy authors and
`money_share` of the author link (the panel's, as a cross-check); `<cycle>_floored_to_zero`
(months, both halves). Then the recipient notes of `amendments_panel` for the months read.
No CPF, name or favorecido code, and no hash of one, in any column, note or message.
