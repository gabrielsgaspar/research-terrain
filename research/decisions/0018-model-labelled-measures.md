---
id: "0018"
title: "Measures built from text with model labels"
status: proposed
date: 2026-11-22
supersedes: null
---

# 0018: Measures built from text with model labels

Date: 2026-11-22. Status: proposed, drafted by Claude for Gabriel from his
brief of 2026-11-22 (campaign 0015). It takes effect when Gabriel merges
the pull request that adds it, with the codebook
`data/reference/pix_object_codebook.md`, the labels
`data/reference/pix_object_labels.yaml` and the build `amendments_objects`.

## The question

Pix amendments (transferências especiais) have no budget function: in the
CGU file they are all "Encargos especiais". What the money buys is only in
the work plans that town halls file, as free text ("Detalhamento do
Objeto"). Turning that text into classes needs reading it, and a language
model can read thousands of texts in an afternoon. But a model reading the
texts is an agent reading data, and the repository's rules keep agents away
from the confirmation half; a model's labels also drift with its version
and its prompt, and nobody can rerun them in a test.

How can a measure built from text with model labels enter an analysis,
keep the split intact and stay reproducible?

## Decision

1. **The classes come from a written codebook** in `data/reference/`, which
   Gabriel approves by merging it. A label is valid only for the codebook
   whose SHA-256 it records.
2. **A model labels only texts of exploration-half municipalities**, and it
   sees nothing but the codebook and the text: never the place, the
   deputy, the value, the date or anything about the race. Each batch is
   labelled in a fresh context.
3. **Labels are stored in `data/reference/`** as a key (the SHA-256 of the
   normalised text) and a class, with the model's id, the date, the
   codebook's SHA-256 and the sample's seed. No text goes into Git.
4. **The measure used in analysis is a plain, deterministic classifier**
   trained on those labels and applied by the build to every text of both
   halves. No model and no agent ever reads a confirmation-half text, and
   the measure is the same function on both halves.
5. **Quality is measured and gated**: agreement between two independent
   labelling passes on a marked subsample (Cohen's kappa), and the
   classifier's cross-validated macro-F1. The build writes both; the
   campaign's kill rules use them.
6. **No model is called in tests, pipelines or workflows.** The labels are
   a committed input; the classifier runs inside the build.
7. **Before any design that uses such a measure is registered for the
   confirmation half**, Gabriel hand-labels a random sample of at least 200
   texts. The error against his labels is reported and corrected for, with
   design-based supervised learning (Egami, Hinck, Stewart and Wei 2023).

## What does not change

The exploration/confirmation split and the sealed outputs; that agents
never read confirmation-half data; that builds are deterministic and their
outputs are addressed by the hash of their inputs and code; that nothing on
the exploration half is a finding; that kill rules are confirmed by Gabriel
before a campaign starts.

## Risks and how they are handled

- **A model's labels are not ground truth.** Point 5 measures how far two
  passes of the same model agree and how well the classifier learns them;
  point 7 measures the error against a person before anything is
  confirmed, and corrects for it.
- **The classifier is weaker than the model.** It is the price of point 4:
  it runs on the confirmation half without anyone reading it, and it gives
  the same answer every time. Its cross-validated macro-F1 is gated.
- **Texts may leak.** Texts are used in memory by the build and the
  sampling script only; the labels file holds hashes; the build checks
  that no text of the source file appears in any output.
- **Declared use, not actual use.** The texts are what town halls
  declared, many filed after the Supreme Court ordered plans (ADPF 854).
  Ideas that use the measure say so; the build reports the share of such
  plans.

## Where it is used

- `src/terrain/pixtext.py` (normalisation, keys, the classifier),
  `scripts/pix_label_sample.py` (the sample), the build
  `amendments_objects`.
- First use: idea 0013, campaign 0015.
