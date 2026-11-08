"""Confirmation runs: `confirm-run` (shuffled treatment) and `unblind` (real, once).

Decision 0001 splits municipalities into two halves. Decision 0003 keeps the
confirmation half's outcome rows only under `sealed/outcomes/`, which only
the terrain-unblind account can read. This module holds the logic behind the
two workflows (harness/BUILD_PLAN.md, section 4.8, item 3.6):

- `.github/workflows/confirm-run.yml` runs one registered specification from
  `confirm/specs/` on the confirmation half with **shuffled treatment**. Each
  close pair's sides are swapped by a coin flip seeded from the
  specification's hash, so a working pipeline must find nothing. Every run
  adds an entry to `confirm/ledger/`.
- `.github/workflows/unblind.yml` runs the same specification with the real
  treatment, after Gabriel approves the `unblind` environment, and only
  once. It refuses if the specification has no shuffled ledger entry with
  the same hash, if that shuffled run's check failed (unless the dispatch
  accepts it), or if the specification was unblinded before.

A specification is a YAML file in the format of `confirm/specs/TEMPLATE.yaml`, with
every one of its fields, plus three this runner needs:

    analysis: 0001_direct      # added: a name registered with `register`
    pap_commit: <40 hex>       # added: the commit that added the plan to confirm/pap/
    params: {...}              # added, optional: settings the analysis reads

The template's fields are checked here (`id` like `NNNN-slug` with the idea's
number, `idea` an idea file, `registered` a date, `predicted_sign`, `sample:
confirm`, `treatment.design: close_pair_swap`, `inference.method: randomisation`,
`inference.draws` a whole number, ...); the registered analysis checks that the
others (outcome, exposure, fixed effects, cluster) describe what it computes. Any
other top-level key is refused, so nothing in a registered specification is
silently ignored.

The analysis is a function registered by name (`register`) in a module under
`terrain.registered`, written, reviewed and merged before the plan is
registered. It receives a `RunContext` and returns numbers only (see
`validate_results`). The same code runs in both modes; only the context
differs. The context gives out confirmation-half outcomes only after the
analysis has taken its treatment through `RunContext.assign`, and the run
fails if the analysis never calls it.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import importlib
import io
import json
import math
import pkgutil
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from terrain.storage import Store

SPLIT_PATH = "sealed/split/split.csv"
SEALED_PREFIX = "sealed/"
SEALED_OUTCOMES = "sealed/outcomes/"
PAP_DIR = "confirm/pap/"

SHUFFLED = "shuffled"
REAL = "real"
MODES = (SHUFFLED, REAL)

LABEL_SHUFFLED = "shuffled"
LABEL_SHUFFLED_POST = "shuffled, post-unblinding"
LABEL_UNBLINDED = "unblinded"

WORKFLOWS = {SHUFFLED: "confirm-run.yml", REAL: "unblind.yml"}
SHUFFLED_CHECK_ALPHA = 0.05
OUTPUT_MAX_BYTES = 200_000

_SPEC_ID = re.compile(r"[0-9]{4}-[a-z0-9-]{1,40}")
_NAME = re.compile(r"[a-z0-9_]{1,60}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_TEMPLATE_KEYS = {
    "id",
    "idea",
    "registered",
    "hypothesis",
    "predicted_sign",
    "sample",
    "outcome",
    "treatment",
    "exposure",
    "fixed_effects",
    "inference",
    "seed_policy",
}
_SPEC_KEYS_REQUIRED = _TEMPLATE_KEYS | {"analysis", "pap_commit"}
_SPEC_KEYS_OPTIONAL = {"params"}
# The template lists positive, negative and zero; two_sided is added for a test whose
# sign is not predicted (idea 0001's direct effect).
PREDICTED_SIGNS = ("positive", "negative", "zero", "two_sided")
OUTCOME_WINDOWS = ("term_years", "pre_years")


class ConfirmError(Exception):
    """A confirmation run broke one of the rules above, and must not go on."""


# --- the specification ---------------------------------------------------


@dataclass(frozen=True)
class Spec:
    id: str
    analysis: str
    pap_commit: str
    params: Mapping[str, Any]
    raw: Mapping[str, Any]
    sha256: str


def _sub(raw: dict[str, Any], key: str, fields: tuple[str, ...]) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ConfirmError(f"{key} must have exactly {sorted(fields)}")
    return value


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfirmError(f"{what} must be filled in")
    return value


def load_spec(data: bytes) -> Spec:
    """Parse and check a specification file's bytes."""
    try:
        raw = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfirmError(f"the specification is not valid UTF-8 YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfirmError("the specification must be a YAML mapping")
    keys = set(raw)
    missing = _SPEC_KEYS_REQUIRED - keys
    unknown = keys - _SPEC_KEYS_REQUIRED - _SPEC_KEYS_OPTIONAL
    if missing:
        raise ConfirmError(f"the specification lacks {sorted(missing)}")
    if unknown:
        raise ConfirmError(
            f"the specification has keys this runner does not use: {sorted(unknown)}"
        )
    spec_id, analysis, commit = raw["id"], raw["analysis"], raw["pap_commit"]
    if not (isinstance(spec_id, str) and _SPEC_ID.fullmatch(spec_id)):
        raise ConfirmError(f"id must look like 0001-some-name, not {spec_id!r}")
    idea = raw["idea"]
    if not (
        isinstance(idea, str)
        and re.fullmatch(rf"research/ideas/{spec_id[:4]}-[a-z0-9-]+\.md", idea)
    ):
        raise ConfirmError(f"idea must be the file research/ideas/{spec_id[:4]}-....md")
    registered = raw["registered"]
    if not isinstance(registered, dt.date) or isinstance(registered, dt.datetime):
        raise ConfirmError("registered must be a date, YYYY-MM-DD")
    _text(raw["hypothesis"], "hypothesis")
    if raw["predicted_sign"] not in PREDICTED_SIGNS:
        raise ConfirmError(f"predicted_sign must be one of {list(PREDICTED_SIGNS)}")
    if raw["sample"] != "confirm":
        raise ConfirmError("sample must be confirm: these runs use the confirmation half only")
    outcome = _sub(raw, "outcome", ("dataset", "variable", "window"))
    _text(outcome["dataset"], "outcome.dataset")
    _text(outcome["variable"], "outcome.variable")
    if outcome["window"] not in OUTCOME_WINDOWS:
        raise ConfirmError(f"outcome.window must be one of {list(OUTCOME_WINDOWS)}")
    treatment = _sub(raw, "treatment", ("design", "bandwidth_rule"))
    if treatment["design"] != "close_pair_swap":
        raise ConfirmError("treatment.design must be close_pair_swap, the shuffle this runner does")
    _text(treatment["bandwidth_rule"], "treatment.bandwidth_rule")
    _text(raw["exposure"], "exposure")
    effects = raw["fixed_effects"]
    if not (isinstance(effects, list) and effects and all(isinstance(e, str) for e in effects)):
        raise ConfirmError("fixed_effects must be a list of names")
    inference = _sub(raw, "inference", ("method", "draws", "cluster"))
    if inference["method"] != "randomisation":
        raise ConfirmError("inference.method must be randomisation")
    draws = inference["draws"]
    if isinstance(draws, bool) or not isinstance(draws, int) or draws < 1:
        raise ConfirmError("inference.draws must be a whole number")
    _text(inference["cluster"], "inference.cluster")
    _text(raw["seed_policy"], "seed_policy")
    if not (isinstance(analysis, str) and _NAME.fullmatch(analysis)):
        raise ConfirmError(f"analysis must be a registered name, not {analysis!r}")
    if not (isinstance(commit, str) and _COMMIT.fullmatch(commit)):
        raise ConfirmError("pap_commit must be a full 40-character commit hash")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise ConfirmError("params must be a mapping")
    return Spec(
        id=spec_id,
        analysis=analysis,
        pap_commit=commit,
        params=params,
        raw=raw,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def shuffle_seed(spec_sha256: str) -> int:
    """The shuffle's seed, fixed by the specification's hash.

    Re-running `confirm-run` on the same specification gives the same flips
    and the same numbers, so repeated shuffled runs cannot be averaged to
    learn anything about the real treatment.
    """
    digest = hashlib.sha256(f"{spec_sha256}:shuffle".encode()).hexdigest()
    return int(digest[:16], 16)


def check_pap_commit(repo: Path, commit: str) -> None:
    """The plan's commit is on the checked-out history and adds a file under
    confirm/pap/ other than its README."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8"
        )

    if git("merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
        raise ConfirmError(f"pap_commit {commit} is not on the checked-out history of main")
    # Against the first parent, so a merge commit lists what it brought in.
    changed = git(
        "diff-tree",
        "-r",
        "--root",
        "-m",
        "--first-parent",
        "--no-commit-id",
        "--name-only",
        "--diff-filter=AM",
        commit,
    )
    if changed.returncode != 0:
        raise ConfirmError(f"cannot list the files pap_commit {commit} changed")
    plan_files = [
        p
        for p in changed.stdout.splitlines()
        if p.startswith(PAP_DIR) and p != f"{PAP_DIR}README.md"
    ]
    if not plan_files:
        raise ConfirmError(f"pap_commit {commit} adds or changes no plan under {PAP_DIR}")


# --- the two halves ---------------------------------------------------------


def confirmation_municipalities(store: Store, split_sha256: str) -> frozenset[str]:
    """IBGE codes of the confirmation half, from the sealed split.

    The split's bytes must hash to the committed `confirm/split.sha256`.
    """
    expected = split_sha256.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ConfirmError("the committed split hash is not one SHA-256")
    data = store.read_bytes(SPLIT_PATH)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ConfirmError(f"{SPLIT_PATH} does not match confirm/split.sha256")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    if reader.fieldnames != ["code_ibge", "half"]:
        raise ConfirmError(f"{SPLIT_PATH} must have columns code_ibge and half")
    codes = frozenset(row["code_ibge"] for row in reader if row["half"] == "confirm")
    if not codes:
        raise ConfirmError(f"{SPLIT_PATH} has no confirmation municipality")
    return codes


# --- the treatment ----------------------------------------------------------


def flips_for(keys: Iterable[Sequence[Any]], seed: int) -> list[bool]:
    """One coin flip per pair, from the pair's key and the seed.

    The flip depends on the key, not on row order, so the same pair is
    flipped the same way however the analysis sorts its table.
    """
    out = []
    for key in keys:
        text = json.dumps([seed, [str(k) for k in key]])
        out.append(hashlib.sha256(text.encode()).digest()[0] & 1 == 1)
    return out


def flip_sides(
    pairs: pl.DataFrame,
    flips: Sequence[bool],
    side_columns: Sequence[tuple[str, str]],
    negate: Sequence[str] = (),
) -> pl.DataFrame:
    """Swap each flipped pair's two sides, and negate its signed columns."""
    if len(flips) != pairs.height:
        raise ConfirmError("one flip per pair is needed")
    flip = pl.Series("__flip", list(flips), dtype=pl.Boolean)
    exprs = []
    for a, b in side_columns:
        exprs.append(pl.when(flip).then(pl.col(b)).otherwise(pl.col(a)).alias(a))
        exprs.append(pl.when(flip).then(pl.col(a)).otherwise(pl.col(b)).alias(b))
    for c in negate:
        exprs.append(pl.when(flip).then(-pl.col(c)).otherwise(pl.col(c)).alias(c))
    return pairs.with_columns(exprs)


@dataclass
class RunContext:
    """What a registered analysis sees. It reads data only through `read`."""

    store: Store
    mode: str
    params: Mapping[str, Any]
    spec: Mapping[str, Any]
    municipalities: frozenset[str]
    seed: int
    assigned: bool = False
    pairs: int = 0
    pairs_flipped: int = 0
    _log: list[str] = field(default_factory=list)

    def restrict(self, df: pl.DataFrame, column: str = "cd_ibge") -> pl.DataFrame:
        """Keep only rows of confirmation municipalities."""
        if column not in df.columns:
            raise ConfirmError(f"cannot restrict to the confirmation half: no column {column!r}")
        return df.filter(pl.col(column).cast(pl.Utf8).is_in(sorted(self.municipalities)))

    def assign(
        self,
        pairs: pl.DataFrame,
        key: Sequence[str],
        side_columns: Sequence[tuple[str, str]] = (("elected_sq", "other_sq"),),
        negate: Sequence[str] = ("margin",),
    ) -> pl.DataFrame:
        """The treatment, once: the pairs as they are (real) or with their
        sides swapped by coin flips (shuffled). Outcomes can be read after."""
        if self.assigned:
            raise ConfirmError("assign is called once per run")
        if not key:
            raise ConfirmError("assign needs the columns that identify a pair")
        if pairs.select(list(key)).is_duplicated().any():
            raise ConfirmError(f"the pair key {list(key)} is not unique")
        self.assigned = True
        self.pairs = pairs.height
        if self.mode == REAL:
            return pairs
        flips = flips_for(pairs.select(list(key)).iter_rows(), self.seed)
        self.pairs_flipped = sum(flips)
        return flip_sides(pairs, flips, side_columns, negate)

    def _guard(self, path: str) -> None:
        if path.startswith(SEALED_PREFIX) and not path.startswith(SEALED_OUTCOMES):
            raise ConfirmError(f"an analysis cannot read {path}; the runner reads the split")
        if path.startswith(SEALED_OUTCOMES) and not self.assigned:
            raise ConfirmError("outcomes are read only after the treatment is assigned")
        self._log.append(path)

    def read(self, path: str) -> bytes:
        self._guard(path)
        return self.store.read_bytes(path)

    def download(self, path: str, local_file: Path) -> None:
        self._guard(path)
        self.store.download(path, local_file)

    def list(self, prefix: str) -> list[str]:
        return self.store.list(prefix)


# --- registered analyses ----------------------------------------------------

Analysis = Callable[[RunContext], dict[str, Any]]
ANALYSES: dict[str, Analysis] = {}


def register(name: str) -> Callable[[Analysis], Analysis]:
    """Register an analysis under `name` (used by `analysis:` in a spec)."""
    if not _NAME.fullmatch(name):
        raise ConfirmError(f"analysis names look like 0001_direct, not {name!r}")

    def wrap(fn: Analysis) -> Analysis:
        if name in ANALYSES and ANALYSES[name] is not fn:
            raise ConfirmError(f"analysis {name!r} is registered twice")
        ANALYSES[name] = fn
        return fn

    return wrap


def load_registered() -> None:
    """Import every module under terrain.registered, so their analyses register."""
    package = importlib.import_module("terrain.registered")
    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"terrain.registered.{info.name}")


# --- results ----------------------------------------------------------------


SIGNIFICANT = 12  # every number is recorded to 12 significant digits
EXTRA_FIELDS = ("q025", "q975", "clustered_se", "mean_y", "pct_of_baseline", "p1", "coef_z")
STOP_REASONS = ("kill_criterion_1",)


def _number(value: Any, what: str, missing: bool = False) -> float | None:
    """A finite number, rounded to `SIGNIFICANT` digits; None only where `missing` allows."""
    if value is None and missing:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfirmError(f"{what} must be a finite number")
    return float(f"{float(value):.{SIGNIFICANT}g}")


def validate_results(results: Any) -> dict[str, Any]:
    """Results hold numbers and short names only, so nothing else can leave a run.

        {"estimates": [{"name": str, "estimate": float | None, "p_value": float | None,
                        "confirmatory": bool, <EXTRA_FIELDS>: float | None}, ...],
         "counts": {name: int, ...},              # optional
         "values": {name: float | None, ...},     # optional: constants and other numbers
         "stopped": one of STOP_REASONS}          # optional: the run stopped early

    A number is None where it is not estimable. Unless the run stopped, at least one
    estimate is confirmatory. Numbers are rounded to 12 significant digits, so a rerun
    that differs only in floating-point summation order records the same numbers.
    """
    allowed = {"estimates", "counts", "values", "stopped"}
    if not isinstance(results, dict) or set(results) - allowed:
        raise ConfirmError(f"results must be a mapping with keys among {sorted(allowed)}")
    stopped = results.get("stopped")
    if stopped is not None and stopped not in STOP_REASONS:
        raise ConfirmError(f"stopped must be one of {list(STOP_REASONS)}")
    estimates = results.get("estimates")
    if not isinstance(estimates, list) or (not estimates and stopped is None):
        raise ConfirmError("results need at least one estimate")
    clean, names = [], set()
    base = {"name", "estimate", "p_value", "confirmatory"}
    for e in estimates:
        if not isinstance(e, dict) or not base <= set(e) or set(e) - base - set(EXTRA_FIELDS):
            raise ConfirmError(
                "each estimate has name, estimate, p_value, confirmatory and only "
                f"{list(EXTRA_FIELDS)} besides"
            )
        name = e["name"]
        if not (isinstance(name, str) and _NAME.fullmatch(name)) or name in names:
            raise ConfirmError(f"estimate names are unique and look like direct_y4, not {name!r}")
        names.add(name)
        if not isinstance(e["confirmatory"], bool):
            raise ConfirmError(f"{name}: confirmatory must be true or false")
        # None where the estimate is not estimable (no variance), confirmatory or not.
        missing = True
        p = _number(e["p_value"], f"{name}: p_value", missing)
        if p is not None and not 0 <= p <= 1:
            raise ConfirmError(f"{name}: p_value must be between 0 and 1")
        row = {
            "name": name,
            "estimate": _number(e["estimate"], f"{name}: estimate", missing),
            "p_value": p,
            "confirmatory": e["confirmatory"],
        }
        for extra in EXTRA_FIELDS:
            if extra in e:
                row[extra] = _number(e[extra], f"{name}: {extra}", True)
        clean.append(row)
    if stopped is None and not any(e["confirmatory"] for e in clean):
        raise ConfirmError("results need at least one confirmatory estimate")
    counts = results.get("counts", {})
    values = results.get("values", {})
    if not isinstance(counts, dict) or not isinstance(values, dict):
        raise ConfirmError("counts and values must be mappings")
    for group in (counts, values):
        for k in group:
            if not (isinstance(k, str) and _NAME.fullmatch(k)):
                raise ConfirmError(f"names look like pairs_2008, not {k!r}")
    for k, v in counts.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise ConfirmError(f"count {k} must be a whole number")
    out = {
        "estimates": clean,
        "counts": dict(sorted(counts.items())),
        "values": {k: _number(v, k, True) for k, v in sorted(values.items())},
    }
    if stopped is not None:
        out["stopped"] = stopped
    return out


def shuffled_check(results: dict[str, Any]) -> dict[str, Any]:
    """The shuffled run must find nothing: no confirmatory p below 0.05.

    A run that stopped early (kill criterion 1, which does not depend on the treatment)
    has nothing to find, and passes.
    """
    failing = [
        e["name"]
        for e in results["estimates"]
        if e["confirmatory"] and e["p_value"] is not None and e["p_value"] < SHUFFLED_CHECK_ALPHA
    ]
    return {"alpha": SHUFFLED_CHECK_ALPHA, "passed": not failing, "failing": failing}


# --- the run ----------------------------------------------------------------


def check_workflow(mode: str, environ: Mapping[str, str]) -> None:
    """Each mode runs only in its own workflow, on main, in GitHub Actions."""
    if mode not in MODES:
        raise ConfirmError(f"mode is shuffled or real, not {mode!r}")
    ref = environ.get("GITHUB_WORKFLOW_REF", "")
    wanted = f"/.github/workflows/{WORKFLOWS[mode]}@refs/heads/main"
    if environ.get("GITHUB_ACTIONS") != "true" or not ref.endswith(wanted):
        raise ConfirmError(f"a {mode} run happens only in {WORKFLOWS[mode]} on main")


def run(
    spec: Spec,
    store: Store,
    mode: str,
    split_sha256: str,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Run a registered specification on the confirmation half."""
    check_workflow(mode, environ)
    analysis = ANALYSES.get(spec.analysis)
    if analysis is None:
        raise ConfirmError(f"no analysis is registered as {spec.analysis!r}")
    ctx = RunContext(
        store=store,
        mode=mode,
        params=spec.params,
        spec=spec.raw,
        municipalities=confirmation_municipalities(store, split_sha256),
        seed=shuffle_seed(spec.sha256),
    )
    raw = analysis(ctx)
    if not ctx.assigned:
        raise ConfirmError("the analysis never took its treatment through assign")
    results = validate_results(raw)
    output: dict[str, Any] = {
        "mode": mode,
        "spec_id": spec.id,
        "spec_sha256": spec.sha256,
        "pap_commit": spec.pap_commit,
        "split_sha256": split_sha256.strip(),
        "pairs": ctx.pairs,
        "results": results,
    }
    if mode == SHUFFLED:
        output["shuffle_seed"] = ctx.seed
        output["pairs_flipped"] = ctx.pairs_flipped
        output["shuffled_check"] = shuffled_check(results)
    return output


def write_output(out_dir: Path, output: dict[str, Any]) -> Path:
    payload = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if len(payload.encode("utf-8")) > OUTPUT_MAX_BYTES:
        raise ConfirmError("the run's output is over 200 KB")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "output.json"
    path.write_text(payload, encoding="utf-8")
    return path


# --- the ledger ---------------------------------------------------------------


def read_ledger(ledger_dir: Path) -> list[dict[str, Any]]:
    """Every entry in confirm/ledger/, oldest first by file name."""
    if not ledger_dir.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(ledger_dir.glob("*.json"))]


def unblinded(spec: Spec, entries: Iterable[dict[str, Any]]) -> bool:
    return any(e.get("spec_id") == spec.id and e.get("label") == LABEL_UNBLINDED for e in entries)


def check_shuffled(spec: Spec, entries: list[dict[str, Any]]) -> str:
    """Before a shuffled run: its ledger label."""
    return LABEL_SHUFFLED_POST if unblinded(spec, entries) else LABEL_SHUFFLED


def check_unblind(
    spec: Spec, entries: list[dict[str, Any]], accept_failed_shuffle: bool = False
) -> str:
    """Before the real run: refuse unless it is the first, and a shuffled
    run of the same specification, byte for byte, is in the ledger."""
    if unblinded(spec, entries):
        raise ConfirmError(f"{spec.id} was unblinded before; unblind runs once")
    shuffled = [
        e
        for e in entries
        if e.get("spec_id") == spec.id
        and e.get("label") == LABEL_SHUFFLED
        and e.get("spec_sha256") == spec.sha256
    ]
    if not shuffled:
        raise ConfirmError(
            f"no shuffled run of {spec.id} with this specification's hash is in the ledger"
        )
    if not shuffled[-1].get("shuffled_check", {}).get("passed") and not accept_failed_shuffle:
        raise ConfirmError(
            f"the last shuffled run of {spec.id} found something; "
            "fix the pipeline, or dispatch with accept_failed_shuffle"
        )
    return LABEL_UNBLINDED


def ledger_entry(
    output: dict[str, Any],
    label: str,
    *,
    run_id: str,
    run_url: str,
    code_commit: str,
    date_utc: str,
    accept_failed_shuffle: bool = False,
) -> dict[str, Any]:
    if not run_id.isdigit():
        raise ConfirmError(f"run id must be digits, not {run_id!r}")
    if not _COMMIT.fullmatch(code_commit):
        raise ConfirmError("code commit must be a full commit hash")
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", date_utc):
        raise ConfirmError("date must look like 2026-11-07T12:00:00Z")
    expected_mode = SHUFFLED if label in (LABEL_SHUFFLED, LABEL_SHUFFLED_POST) else REAL
    if label not in (LABEL_SHUFFLED, LABEL_SHUFFLED_POST, LABEL_UNBLINDED):
        raise ConfirmError(f"unknown ledger label {label!r}")
    if output.get("mode") != expected_mode:
        raise ConfirmError(f"a {output.get('mode')} run cannot be labelled {label!r}")
    entry = dict(output)
    entry.update(
        {
            "label": label,
            "run_id": run_id,
            "run_url": run_url,
            "code_commit": code_commit,
            "date_utc": date_utc,
        }
    )
    if label == LABEL_UNBLINDED:
        entry["accept_failed_shuffle"] = accept_failed_shuffle
    return entry


def ledger_filename(entry: dict[str, Any]) -> str:
    stamp = entry["date_utc"].replace("-", "").replace(":", "")
    slug = {
        LABEL_SHUFFLED: "shuffled",
        LABEL_SHUFFLED_POST: "shuffled-post",
        LABEL_UNBLINDED: "unblinded",
    }[entry["label"]]
    return f"{stamp}-{entry['spec_id']}-{slug}-{entry['run_id']}.json"


def write_ledger_entry(ledger_dir: Path, entry: dict[str, Any]) -> Path:
    """Add one entry; never overwrite one."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_dir / ledger_filename(entry)
    with path.open("x", encoding="utf-8") as f:
        f.write(json.dumps(entry, indent=2, sort_keys=True) + "\n")
    return path
