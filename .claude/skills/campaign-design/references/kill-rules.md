# Kill rules

A kill rule is applied by code to the run's `results.json`:

```yaml
kill_rules:
  - id: k1
    says: "Fewer than 60 close races at the 1% window"
    field: counts.1pct.races     # dotted path into results.json
    op: "<"                       # < <= > >= == !=
    value: 60
    confirmed: true               # only after Gabriel confirms it
```

Any rule met kills the step. A field that is missing, or not a number when
the rule compares numbers, makes the step **unreadable**: it stops and asks
Gabriel. So the task draft for the script must say exactly which keys it
writes, and a test in that task must check them.

## Where thresholds come from

Never from looking at outcomes. Good sources, as used in this repository:

- **Design counts.** The design needs enough units to say anything: idea
  0001's kill criterion 1 asked for at least 200 close-pair strongholds per
  constituency type. Derive the number from the inference you will run
  (pairs re-flipped for randomisation inference need enough pairs for the
  p-value to reach 0.05; with n pairs the smallest two-sided p is about
  2 / 2^n, but power is the real limit).
- **Power.** Decision 0007 fixes the effect size (8% of baseline clearing)
  and asks for 80% power. A rule like "minimum detectable effect above 8% of
  baseline" (`mde_share > 0.08`) kills an underpowered variant before it is
  run on outcomes.
- **Placebos.** A pre-election placebo with randomisation-inference p below
  0.10 (`placebo.ri_p < 0.10`) says the comparison is not balanced; idea
  0001's kill criterion 2 is the model. See "False stops" below before
  proposing one.
- **Balance.** Covariate balance rules, as in task 35: a window fails if a
  balance test rejects at the stated level.
- **Plausibility.** A magnitude no mechanism could produce (a share above
  1, an effect larger than baseline clearing) is a sign of a bug: a rule on
  it is fine, and cheap.

## False stops

A rule of the form "p below a level" (`placebo.ri_p < 0.10`, a balance
test that rejects at 5%) stops a valid design that share of the time,
because a balanced design still gives a small p by chance:

- p below 0.05 stops 1 valid design in 20;
- p below 0.10 stops 1 valid design in 10;
- several such rules add up: three rules at 0.10 stop up to 3 valid
  designs in 10 (at most the sum of the levels; a little less when the
  tests are independent).

When you propose such a rule, tell Gabriel this number for the step and,
if the campaign has several, for the whole campaign. Then offer the
alternative: a rule on the size of the imbalance, for example "the
placebo slope is larger than a stated bound" (`placebo.slope_abs >` the
bound), with the bound fixed before any run, such as a share of decision
0007's effect size. A size rule stops a design when the imbalance is large
enough to matter, not merely detectable; for a balanced design its chance
of a false stop falls as the sample grows, while a p rule's stays at its
level. Let him choose either, or both.

## Proposing rules to Gabriel

For each `explore_run` step, offer two or three candidates and say for
each: what it protects against, how likely it is to fire, and what is lost
if it is too strict. Example:

> For s2 (power of close mayoral races) I'd suggest one of:
> 1. `mde_share.1pct > 0.08`: dies if the 1% window cannot detect decision
>    0007's effect. Strict; matches the rest of the project.
> 2. `counts.1pct.races < 60`: dies on too few races. Cheaper to explain,
>    but says nothing about power directly.
> 3. Both. My recommendation: 1, with 2 as a sanity check.
> Which, or something else?

Then read the chosen rules back in plain words and ask for a clear yes.

## Anti-patterns to refuse or flag

- A threshold picked after seeing a run's output (forking paths). If
  Gabriel has seen the number, say so in the Provenance section.
- A rule no plausible run could meet, or one every run will meet. Say
  which it is.
- A rule on a field the script does not write.
- Treating a passed rule as a result. A passed p-value rule is not
  evidence of balance: with few units it passes a large imbalance. Never
  write "balanced" because one passed; if balance matters to the next
  step, add a rule on the size of the imbalance.
- Two-sided ambiguity: say whether a sign is part of the rule.
- A rule on post-election outcomes that is not in the step's stated scope
  (referee R2). Outcome rules are fine only when the draft says which
  outcome years the script reads.
- Changing an idea file's kill criteria: those are Gabriel's, outside the
  campaign. A campaign's rules may restate them, never loosen them.
