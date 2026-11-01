# research-terrain

An agent-assisted research lab on how elections shape land, forests and public
goods in Brazil. Data lives in GCS; ideas, tests, lessons and the paper live
here.

> Work in progress. Nothing here is a finding until it appears in the paper.

## The question

Does local democracy protect land that has voters and push environmental harm
onto land that does not? The lead design compares the electoral strongholds of
narrowly elected and narrowly defeated city-council candidates in the Legal
Amazon. See `research/questions.md` and `research/ideas/`.

## How the work is organised

- **Explore freely, confirm once.** Municipalities are split into an
  exploration half and a sealed confirmation half before any outcome data
  exists (`research/decisions/0001-split-sample.md`). Ideas are tried on the
  first; survivors are registered in `confirm/specs/` and run once on the
  second.
- **Everything leaves a trace.** Every exploration updates its idea file and
  `research/lessons.md`, including dead ends.
- **Code checks what code can check.** Agents plan, build and review through
  GitHub Actions; people approve every plan and every merge (`AGENTS.md`).

## Agent workflow

Adapted from [Alteram](https://github.com/gabrielsgaspar/alteram):

1. Open an issue with the **Agent task** template.
2. Add the `agent-plan` label and read the plan comment.
3. If the plan is right, swap the label to `agent-build`.
4. Wait for the PR, CI and the reviewer's comment, then merge or push back.

## Layout

```
src/terrain/   tested code            research/   questions, ideas, lessons,
pipeline/      acquire and build                  decisions, references
explore/       one script per idea    confirm/    pre-analysis plan, specs,
methods/       simulations                        ledger (human-only)
data/          catalog, contracts,    legacy/     the original paper's code
               fixtures (no data)     overleaf/   the paper (submodule)
```

## Setup

You need [uv](https://docs.astral.sh/uv/) and, for Claude Code locally, WSL2.

```bash
uv sync
uv run ruff check . && uv run pytest
```

Repository settings, the GitHub App, environments, GCS and Workload Identity
Federation are described in `research/decisions/0002-repo-and-storage.md`.
Repository variables the workflows expect: `AGENT_APP_CLIENT_ID`,
`GCP_WIF_PROVIDER`, `GCP_PROJECT_ID`. Secrets: `CLAUDE_CODE_OAUTH_TOKEN`,
`AGENT_APP_PRIVATE_KEY`.

## Licence

MIT for code. Data keep their original licences (`data/catalog.yaml`).
