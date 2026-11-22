---
id: "0013"
title: "What do allied towns get? The instrument and the declared use of deputies' amendment money"
status: exploring
created: 2026-11-22
updated: 2026-11-22
datasets:
  - amendments_panel
  - amendments_objects
kill_criteria:
  - "The measure is unreliable: Cohen's kappa on groups between the two labelling passes is below 0.70 (stated by Gabriel in his brief, 2026-11-22)."
  - "The classifier does not learn the groups: its cross-validated macro-F1 on groups is below 0.80 (stated by Gabriel in his brief, 2026-11-22)."
  - "Too much Pix money has no plan: less than 85% of exploration-half post-window Pix value has a matched work plan in cycle B or C (stated by Gabriel in his brief, 2026-11-22)."
  - "No Pix first stage: the municipality-clustered F of the Pix jump (ln(1 + reais per inhabitant), post window, cycles B and C pooled, at h) is below 10 (stated by Gabriel in his brief, 2026-11-22)."
  - "Pre-trend: in cycle C the pre-window Pix jump is more than half the post-window one and its randomisation p is below 0.05 (stated by Gabriel in his brief, 2026-11-22)."
  - "No Pix group has a strong jump: none of visible, services and fungible Pix money has a clustered F of at least 10 (stated by Gabriel in his brief, 2026-11-22)."
related: ["0010", "0011"]
---

# 0013: What do allied towns get? The instrument and the declared use of deputies' amendment money

## Claim

Campaign 0011 found that federal deputies send more individual amendment
money to towns where their party narrowly won the mayoralty (idea 0010).
This idea asks what that extra money is: which instrument carries it, and,
for Pix, what the town hall said it would buy.

## When and why this idea was formed

Formed on 2026-11-22, after campaign 0011's gate and main run
(`research/explore-runs/0010/44484340952.md`, `44538371996.md`), which
found the premium, and before any outcome of the new measure was read. It
uses the same exploration half and the same 7.5% window, so a result here
is a further look at data already analysed, and the report must say so.

Background, from the public CGU file the repository acquired
(`data/raw/cgu/amendments/2026-11-16/`; national totals only, computed
outside the repository, as Gabriel's brief states them):

- Individual amendments reach a town through three instruments: **Pix**
  (transferências especiais: cash to the municipal treasury, with no
  agreed object), **health** (budget function Saúde, mostly to the
  municipal health fund) and **other tied transfers** (agreements for a
  stated object: urban works, sport, farming and so on).
- Pix was 7% of individual payments in 2020, 21% in 2021, 40% in 2023
  and 29% in 2025-26. The budget function Urbanismo fell from 20% (2017)
  to 1% (2025). Health stayed at 52-62%.
- Pix has no budget function of its own ("Encargos especiais"), so what it
  buys is only in the work plans. The file has 58,990 plan rows for
  2020-2026 (R$37.7bn), each with a free-text "Detalhamento do Objeto".
  34,336 are marked "Legado ADPF 854", filed after the Supreme Court
  ordered plans.

## Prediction

Two readings, declared before any estimate:

- **Credit-claiming.** The premium of allied towns is in visible things:
  works, machines, events. Then within Pix the visible group carries the
  premium (visible minus fungible above 0), and tied transfers, which name
  an object, gain at least as much as health.
- **Broker payment.** The premium is in fungible money: running costs,
  unspecified uses, no plan. Then within Pix the fungible group carries
  it (visible minus fungible below 0), and Pix gains more than tied money.

**Declared estimates** (three, Holm-adjusted together; everything else is
descriptive):

1. The Poisson premium of Pix minus tied, cycles B and C pooled.
2. Visible minus fungible within Pix, cycles B and C pooled.
3. Health, C minus A.

Against the idea as a whole: no instrument or Pix group shows a jump
(the kill criteria above).

**The measure is "declared use".** The classes are what town halls wrote
in their plans, many of them only after the Supreme Court ordered plans to
be filed (ADPF 854). A plan says what was declared, not what was bought.

## Design

Idea 0010's design. Exploration half only (decision 0011). Close mayoral
races; a row is a deputy and a town where the deputy's party had a
finalist; treatment `win` (the party's finalist won). Window h = 7.5%,
read from gate record `research/explore-runs/0010/44484340952.md`, with
5% as a check. The linear estimator of `explore/0010_amendments_main.py`:
local linear in the margin, deputy-by-cycle fixed effects, errors
clustered by municipality, randomisation inference re-flipping races.
Effects in percent come from pyfixest `fepois` on reais with offset
ln(`population_m`). Cycles A (mayor 2016), B (2020), C (2024).

Outcomes, from `amendments_objects` (decision 0018), post window:

- by instrument: Pix, health, tied;
- Pix by work-plan class, using a plain classifier trained on 6,000
  model labels of exploration-half texts and applied to every plan.
  Groups: visible = road works + building works + machines + events;
  services = health + education and social; fungible = running costs +
  vague + mixed + Pix with no plan.

## Literature

- Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`) and
  campaigns 0011 and 0013 (`research/campaigns/0011-amendments-share-of-quota/`,
  `research/campaigns/0013-amendments-mechanisms/`).
- Cavalcanti (2026), "Para onde vai o Pix?", Ipea: Pix by area for the
  whole country (as Gabriel's brief cites it; web, unverified: a search
  on 2026-11-22 found Ipea's notes on amendments but not this title).
  Nobody has asked what allies get.
- Baião and Couto (2017), "A eficácia do pork barrel", *Opinião Pública*
  23(3) (web, unverified).
- Ventura (2021), *Electoral Studies* (as Gabriel's brief cites it;
  unverified).
- Transparência Brasil, "Emendas Pix" reports for 2023 and 2024
  (https://transparencia.org.br/downloads/publicacoes/emendaspix2024.pdf;
  web, unverified): descriptive, on how vague the plans are.
- Decision 0018 (`research/decisions/0018-model-labelled-measures.md`).

## Data needed

`amendments_panel` (v3, in the bucket) and `amendments_objects`, built by
campaign 0015's first step (owner PR #470; dry-run on 2026-11-22).

## Status

- 2026-11-22: proposed (Gabriel's brief, 2026-11-22).
- 2026-11-22: exploring. Campaign 0015 (`research/campaigns/0015-amendment-objects/`)
  starts when this pull request merges.

## Variants tried

None yet.

## Log

- Campaign 0015's pull request: this file and the campaign.
