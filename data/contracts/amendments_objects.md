# amendments_objects

One row per cycle, federal deputy and municipality: exactly the rows of `amendments_panel`.
For the pre and the post window of each row, the deputy's individual amendment payments to
the municipality, split by instrument and, for Pix, by what the work plans say the money is
for. Idea 0013, decisions 0003, 0011 and 0018. Built by
`src/terrain/builds/amendments_objects.py` (owner PR "Data: what amendment money is";
run in campaign 0015).

## Inputs

- The same as `amendments_monthly` (`data/contracts/amendments_monthly.md`): `tse_general`
  (`consulta_cand_<year>.zip` of t0-4 and t0), `cgu_amendments`, `tse_results` (the mayoral
  year m), `tse_candidates`, `municipalities`, `camara_deputies` and the two exploration
  lists.
- From the `cgu_amendments` zip, three members:
  - `EmendasParlamentares_PorFavorecido.csv`: the payments, as `amendments_panel` reads them;
  - `EmendasParlamentares.csv`: `Código da Emenda`, `Nome Função` and `Valor Pago`;
  - `EmendasParlamentares_PlanodeTrabalhoTransferenciasEspeciais.csv`: `Emenda Parlamentar`,
    `Situação do Plano de Trabalho`, `Beneficiário`, `UF do Beneficiário`,
    `Detalhamento do Objeto` and `Valor`. `CNPJ do Beneficiário` and `Autor da Emenda` are
    not read. The text and `Beneficiário` are used in memory only.
- `data/reference/pix_object_labels.yaml` (model labels by text key, decision 0018) and
  `data/reference/pix_object_codebook.md`, whose SHA-256 must be the one the labels record.

## Rows

The rows of a cycle are the panel's (`cycle`, `deputy`, `cd_ibge`), computed by the same code
(`amendments_panel.cycle_link`, `amendments_panel.panel_keys`). The payments are the panel's:
individual amendments, the recipient matched to a municipality, the author linked to the
deputy by the cycle's author link, summed over the windows of `amendments_panel.CYCLES`.

## The measure

- **Text key.** `terrain.pixtext.norm_text` (strip, collapse spaces, upper-case, cut at 600
  characters); the key is its SHA-256.
- **Classifier.** `terrain.pixtext.make_classifier`: TF-IDF of character n-grams (2 to 5,
  within words) and of words (1 to 2), logistic regression with balanced class weights and
  `random_state` 20261121. One is trained on the first-pass classes, one on the
  specificities, of the labelled keys found among the plan texts (at least 2,000), and each
  predicts every distinct plan text of both halves.
- **Plan municipality.** `Beneficiário` without its `MUNICIPIO DE/DO/DA/DOS/DAS` prefix,
  normalised as `amendments_panel` normalises recipients, with `UF do Beneficiário`, matched
  to `municipalities`; states and the Federal District have none.
- **Matching.** A Pix payment is matched to the plans with the same amendment code
  (`Código da Emenda` = `Emenda Parlamentar`) and municipality. Its value is split over the
  matched plans in proportion to their `Valor` (by their count where the values add up to 0
  or less). With no match it is `pix_no_plan`.
- **Instrument.** `pix`: `Tipo de Emenda` is transferências especiais. Otherwise `health` if
  the amendment's `Nome Função` is Saúde; a code with several functions takes the one with
  the largest `Valor Pago`. Otherwise `tied`, also when the code has no function (counted).

## Output and split

`objects_<cycle>.parquet`, sorted by `deputy`, `cd_ibge`. Rows of exploration-half
municipalities go to `data/derived/amendments_objects/<hash>/`; every other row goes only to
`sealed/outcomes/amendments_objects/<hash>/`, which the build creates in and never reads.
`measurement.parquet` goes to the derived folder only. `<hash>` is `content_hash` of the
sorted input SHA-256s, the SHA-256s of the two lists, the cycles, the scikit-learn version,
the text of the label file and of the codebook, and the source of this build and of the
`terrain` modules it imports (`pixtext`, `amendments_monthly`, `amendments_panel`,
`parties`, `explore`, `place_outcomes`, `cell_outcomes`, `polling_place_tenure`).

## Columns of `objects_<cycle>.parquet`

`cycle`, `deputy` (t0 `sq_candidato`) and `cd_ibge` (7 digits), as in `amendments_panel`;
then, for `<w>` in `pre` and `post`, reais (nominal), each set to 0 where its window nets
below 0:

| Column | Meaning |
| --- | --- |
| `obj_<w>_pix` | Pix payments |
| `obj_<w>_health` | not Pix, function Saúde |
| `obj_<w>_tied` | not Pix, any other function or none |
| `obj_<w>_pix_<class>` | Pix value split to plans of the class, one column per codebook class: `obra_viaria`, `obra_predial`, `maquinas`, `saude`, `educ_social`, `eventos`, `custeio_admin`, `vago`, `misto` |
| `obj_<w>_pix_no_plan` | Pix value with no matched plan |
| `obj_<w>_pix_visible` | `obra_viaria` + `obra_predial` + `maquinas` + `eventos` |
| `obj_<w>_pix_services` | `saude` + `educ_social` |
| `obj_<w>_pix_fungible` | `custeio_admin` + `vago` + `misto` + `no_plan` |
| `obj_<w>_pix_spec0`, `_spec1`, `_spec2` | Pix value split to plans of each predicted specificity |
| `obj_<w>_pix_legacy`, `_regular` | Pix value split to plans filed as "Legado ADPF 854" or not |

Before the floor: `pix` + `health` + `tied` is the panel's `amend_<w>_total`; the classes
with `no_plan`, the three groups, the specificities with `no_plan` and `legacy` + `regular`
with `no_plan` each add up to `pix`.

## `measurement.parquet` (derived only)

Long format: `measure`, `cycle`, `year`, `class` (text, or null), `value` (float).

| measure | keyed by | meaning |
| --- | --- | --- |
| `n_labels` | | labelled keys found among the plan texts |
| `cv_accuracy_<x>`, `cv_macro_f1_<x>` | | 5-fold stratified cross-validation (seed 20261121) for `classes`, `groups` (class predictions mapped to groups) and `specificity` |
| `kappa_classes`, `kappa_groups` | | Cohen's kappa of the two labelling passes, from the label file |
| `pix_value_with_plan` | cycle | share of exploration-half post-window Pix value (panel rows, before the floor) with a matched plan; cycles with Pix only |
| `legacy_share_rows` | year (null: all) | share of exploration-half plan rows filed as "Legado ADPF 854", by amendment year |
| `class_value_share`, `group_value_share`, `specificity_value_share` | year (null: all), class | shares of exploration-half plan value, by amendment year |

## Checks the build enforces

Each raises `BuildError` with counts only, after writing a row-count profile
(`terrain.profile.write_profile`), before anything is uploaded.

1. The label file was made with another codebook (SHA-256), or has no kappas.
2. Fewer than 2,000 labelled keys found among the plan texts.
3. Before the floor, instruments that do not add up to the window total, or a Pix split that
   does not add up to the Pix total, within R$1.
4. A duplicate (`cycle`, `deputy`, `cd_ibge`); rows that are not the panel's rows; a column
   below 0 (after the floor, as a guard); fewer than 5,000 or more than 300,000 panel rows.
5. In a payment year from 2020, less than 80% of the Pix paid value (window payments of
   every author to an identified municipality, both halves) matched to a plan.
6. An output cell or note that could hold a text of the file: a row-table text cell that is
   not a cycle or digits, a measurement text cell outside its fixed vocabulary, or a note
   containing a plan text of 8 characters or more.
7. The CGU rules of `amendments_panel` (month range, Pix, formats, the 2% recipient rule), a
   plan amendment code that is not 12 digits, a plan `Valor` or `Valor Pago` that is not a
   number.

## Manifest notes

Per cycle: exploration-half rows, panel rows, deputy authors, `money_share` of the author
link, cells set to 0. Then plan rows (with and without a municipality), distinct texts,
legacy rows; the label file's size, model, date and codebook SHA-256 and the labels found;
plan keys split by count; amendment codes and codes with several functions; non-Pix payment
rows with no function, per year; Pix payment rows matched to a plan, per year; the recipient
notes of `amendments_panel`. No text, CNPJ, name or favorecido code in any column, note or
message.
