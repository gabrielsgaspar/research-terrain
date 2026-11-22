"""What the amendment money of each amendments-panel row is (idea 0013, decision 0018).

Contract of the output: data/contracts/amendments_objects.md. One row per cycle, deputy and
municipality: exactly the rows of `amendments_panel` (the same deputies, author link,
recipient rules and municipalities, from `terrain.builds.amendments_panel`). For the pre and
the post window of each row, in reais, the deputy's individual payments to the municipality
split two ways:

- by instrument: `pix` (transferências especiais); `health` (not Pix, and the amendment's
  `Nome Função` in `EmendasParlamentares.csv` is Saúde); `tied` (not Pix, any other function
  or none);
- Pix by what its work plans say: a Pix payment is matched to the plans of
  `EmendasParlamentares_PlanodeTrabalhoTransferenciasEspeciais.csv` by amendment code and
  municipality (state and normalised name, as `amendments_panel` matches recipients) and its
  value is split over the plans in proportion to their `Valor`. A plan's class and
  specificity are the predictions of the classifier of `terrain.pixtext`, trained on the
  committed model labels and applied to every plan text of both halves. A payment with no
  plan goes to `no_plan`.

Rows of exploration-half municipalities (both exploration lists) go to the derived folder;
every other row goes to a sealed folder that this build only creates in and never reads.
`measurement.parquet` (derived only) holds the measure's quality and exploration-half
descriptions.

Plan texts (`Detalhamento do Objeto`) and `Beneficiário` are used in memory only. `CNPJ do
Beneficiário` is never read. No text of the file is written to a column, a note or an
exception message; the build checks it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl
import sklearn

from terrain import explore as terrain_explore
from terrain import parties, pixtext
from terrain.builds import amendments_monthly as amonthly
from terrain.builds import amendments_panel as ap
from terrain.builds import cell_outcomes, place_outcomes
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.amendments_panel import CYCLES, Cycle, _fetch_frame
from terrain.builds.cell_outcomes import _upload
from terrain.builds.place_outcomes import read_lists
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash
from terrain.profile import write_profile
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "amendments_objects"
MEASUREMENT = "measurement.parquet"
WINDOWS = ("pre", "post")
INSTRUMENTS = ("pix", "health", "tied")
CLASS_PARTS = tuple(f"pix_{c.lower()}" for c in pixtext.CLASSES) + ("pix_no_plan",)
GROUP_PARTS = tuple(f"pix_{g}" for g in pixtext.GROUP_NAMES)
SPEC_PARTS = tuple(f"pix_spec{s}" for s in pixtext.SPECIFICITIES)
FILED_PARTS = ("pix_legacy", "pix_regular")
PARTS = INSTRUMENTS + CLASS_PARTS + GROUP_PARTS + SPEC_PARTS + FILED_PARTS
# Each set of parts that must add up to the Pix total (`pix_no_plan` closes the plan-based ones)
PIX_SPLITS = {
    "classes": CLASS_PARTS,
    "groups": GROUP_PARTS,
    "specificity": (*SPEC_PARTS, "pix_no_plan"),
    "filed": (*FILED_PARTS, "pix_no_plan"),
}

HEALTH_FUNCTION = "SAUDE"  # `Nome Função`, normalised
FUNCTION_COLUMNS = {
    "amendment": "Código da Emenda",
    "function": "Nome Função",
    "paid": "Valor Pago",
}
MIN_LABELS = 2000  # labelled keys that must be found among the plan texts
MIN_PLAN_SHARE = 0.80  # of a year's Pix paid value matched to a plan, both halves
COVERAGE_FROM = 2020  # the first payment year the plan share is checked in
TOLERANCE = 1.0  # reais: how far the parts may be from their total before the floor
NOTE_TEXT_MIN = 8  # plan texts this long or longer may not appear in the notes

SCHEMA: dict[str, Any] = {
    "cycle": pl.Utf8,
    "deputy": pl.Utf8,
    "cd_ibge": pl.Utf8,
    **{f"obj_{w}_{p}": pl.Float64 for w in WINDOWS for p in PARTS},
}
MEASUREMENT_SCHEMA: dict[str, Any] = {
    "measure": pl.Utf8,
    "cycle": pl.Utf8,
    "year": pl.Int64,
    "class": pl.Utf8,
    "value": pl.Float64,
}
MEASURES = frozenset(
    {
        "n_labels",
        "cv_accuracy_classes",
        "cv_macro_f1_classes",
        "cv_accuracy_groups",
        "cv_macro_f1_groups",
        "cv_accuracy_specificity",
        "cv_macro_f1_specificity",
        "kappa_classes",
        "kappa_groups",
        "pix_value_with_plan",
        "legacy_share_rows",
        "class_value_share",
        "group_value_share",
        "specificity_value_share",
    }
)

# Every module whose code decides what this build writes: the monthly build's modules (the
# panel's rows, author link and payments), `amendments_monthly`, `pixtext` and this file.
CODE_MODULES = (
    Path(__file__),
    Path(pixtext.__file__),
    Path(amonthly.__file__),
    Path(ap.__file__),
    Path(parties.__file__),
    Path(terrain_explore.__file__),
    Path(place_outcomes.__file__),
    Path(cell_outcomes.__file__),
    Path(tenure.__file__),
)


def output_name(cycle: str) -> str:
    return f"objects_{cycle}.parquet"


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]],
    split_shas: list[str],
    reference: list[str],
    cycles: tuple[str, ...] = tuple(CYCLES),
    code: list[str] | None = None,
) -> str:
    """Input SHA-256s, the split, the reference texts (labels, codebook), the cycles, the
    scikit-learn version and the code."""
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    spec = ",".join(f"{c}={tuple(CYCLES[c])}" for c in sorted(cycles))
    return content_hash(
        shas, ",".join(split_shas), spec, f"sklearn={sklearn.__version__}", *reference, *sources
    )


# --- Budget functions


def read_functions(zip_path: Path) -> tuple[pl.DataFrame, dict[str, int]]:
    """(`amendment`, `health`): per amendment code of `EmendasParlamentares.csv`, whether its
    budget function is Saúde. A code with several functions takes the one with the largest
    `Valor Pago` (ties: the first name). Rows without a numeric code are skipped. Counts:
    `codes`, `multi_function` codes."""
    raw = ap._read_member(zip_path, ap.AMENDMENTS_MEMBER, FUNCTION_COLUMNS)
    code = pl.col("amendment").str.strip_chars()
    coded = raw.filter(code.str.contains(ap.AMENDMENT_CODE).fill_null(False))
    paid = pixtext.brazilian_number(pl.col("paid"))
    present = pl.col("paid").fill_null("").str.strip_chars().str.len_chars() > 0
    bad = coded.filter(present & paid.is_null()).height
    if bad:
        raise BuildError(f"{bad} amendment rows have a Valor Pago that is not a number")
    rows = coded.select(
        code.alias("amendment"),
        pl.col("function").fill_null("").map_elements(ap.normalise_name, return_dtype=pl.Utf8),
        paid.fill_null(0.0).alias("paid"),
    )
    per = rows.group_by("amendment", "function").agg(pl.col("paid").sum())
    multi = per.group_by("amendment").len().filter(pl.col("len") > 1).height
    chosen = (
        per.sort(["amendment", "paid", "function"], descending=[False, True, False])
        .group_by("amendment", maintain_order=True)
        .first()
    )
    out = chosen.select("amendment", (pl.col("function") == HEALTH_FUNCTION).alias("health"))
    return out.sort("amendment"), {"codes": out.height, "multi_function": multi}


# --- The measure


class Measure:
    """The classifier's predictions for every plan text and its quality."""

    def __init__(self, predicted: pl.DataFrame, quality: dict[str, float], n_labels: int):
        self.predicted = predicted  # key, class, specificity
        self.quality = quality
        self.n_labels = n_labels


def check_labels(doc: dict[str, Any], codebook_text: str) -> dict[str, float]:
    """The label file's codebook must be this codebook; returns its kappas."""
    sha = hashlib.sha256(codebook_text.encode("utf-8")).hexdigest()
    if doc["codebook_sha256"] != sha:
        write_profile("label_codebook", [("all", "inconsistent", 1)])
        raise BuildError("the label file was made with another codebook (SHA-256 differs)")
    kappa = doc.get("kappa") or {}
    if not {"classes", "groups"} <= set(kappa):
        raise BuildError("the label file has no kappa on classes and groups")
    return {"kappa_classes": float(kappa["classes"]), "kappa_groups": float(kappa["groups"])}


def measure(
    plans: pl.DataFrame, labels: dict[str, dict[str, Any]], *, min_labels: int = MIN_LABELS
) -> Measure:
    """Train the classifier on the labelled keys found among the plan texts (first-pass
    class and specificity) and predict every distinct plan text. Quality: cross-validated
    accuracy and macro-F1 for classes, groups (the class predictions mapped to groups) and
    specificity."""
    texts = plans.select("key", "text").unique("key").sort("key")
    train = texts.filter(pl.col("key").is_in(sorted(labels)))
    if train.height < min_labels:
        write_profile(
            "labelled_keys",
            [("all", "ok", train.height), ("all", "not_in_reference", len(labels) - train.height)],
        )
        raise BuildError(
            f"{train.height} labelled keys found among the plan texts, fewer than {min_labels}"
        )
    keys, train_texts = train["key"].to_list(), train["text"].to_list()
    classes = [labels[k]["class"] for k in keys]
    specs = [labels[k]["specificity"] for k in keys]
    cv_classes = pixtext.cross_validate(train_texts, classes)
    cv_specs = pixtext.cross_validate(train_texts, specs)
    quality: dict[str, float] = {}
    for name, truth, pred in (
        ("classes", classes, cv_classes),
        ("groups", [pixtext.GROUPS[c] for c in classes], [pixtext.GROUPS[c] for c in cv_classes]),
        ("specificity", specs, cv_specs),
    ):
        s = pixtext.scores(truth, pred)
        quality[f"cv_accuracy_{name}"] = s["accuracy"]
        quality[f"cv_macro_f1_{name}"] = s["macro_f1"]
    all_texts = texts["text"].to_list()
    predicted = texts.select("key").with_columns(
        pl.Series("class", pixtext.fit_predict(train_texts, classes, all_texts), pl.Utf8),
        pl.Series("specificity", pixtext.fit_predict(train_texts, specs, all_texts), pl.Int64),
    )
    return Measure(predicted, quality, train.height)


def plan_shares(plans: pl.DataFrame, predicted: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """Per (`amendment`, `cd_ibge`) with a plan: the share of each class, specificity and
    filing (`legacy` or not) in the plans' `Valor`. Where the plans' values add up to 0 or
    less, the shares are of the plan count. Returns the shares and the count of such keys."""
    rows = plans.filter(pl.col("cd_ibge").is_not_null()).join(predicted, on="key", how="left")
    indicators = (
        [(pl.col("class") == c).alias(f"pix_{c.lower()}") for c in pixtext.CLASSES]
        + [(pl.col("specificity") == s).alias(f"pix_spec{s}") for s in pixtext.SPECIFICITIES]
        + [pl.col("legacy").alias("pix_legacy"), (~pl.col("legacy")).alias("pix_regular")]
    )
    names = [*CLASS_PARTS[:-1], *SPEC_PARTS, *FILED_PARTS]
    rows = rows.with_columns(indicators)
    sums = rows.group_by("amendment", "cd_ibge").agg(
        pl.col("value").sum().alias("plan_value"),
        pl.len().alias("plan_rows"),
        *[pl.col("value").filter(pl.col(n)).sum().alias(f"v_{n}") for n in names],
        *[pl.col(n).sum().alias(f"n_{n}") for n in names],
    )
    by_value = pl.col("plan_value") > 0
    shares = sums.select(
        "amendment",
        "cd_ibge",
        *[
            pl.when(by_value)
            .then(pl.col(f"v_{n}") / pl.col("plan_value"))
            .otherwise(pl.col(f"n_{n}") / pl.col("plan_rows"))
            .alias(f"share_{n}")
            for n in names
        ],
    )
    return shares, sums.filter(~by_value).height


def split_payments(
    payments: pl.DataFrame, functions: pl.DataFrame, shares: pl.DataFrame
) -> pl.DataFrame:
    """Each payment row (`amendment`, `cd_ibge`, `value`, `pix`, ...) with one column per
    part: its value under the instrument, class, group, specificity and filing it belongs
    to (0 elsewhere), `planned` (a Pix payment matched to a plan) and the Pix flag renamed
    `is_pix` (`pix` is now the Pix amount)."""
    rows = (
        payments.with_columns(pl.col("amendment").fill_null("").str.strip_chars())
        .rename({"pix": "is_pix"})
        .join(functions, on="amendment", how="left")
        .join(shares, on=["amendment", "cd_ibge"], how="left")
    )
    value, pix = pl.col("value"), pl.col("is_pix")
    health = ~pix & pl.col("health").fill_null(False)
    planned = pix & pl.col("share_pix_legacy").is_not_null()
    parts = [
        pl.when(pix).then(value).otherwise(0.0).alias("pix"),
        pl.when(health).then(value).otherwise(0.0).alias("health"),
        pl.when(~pix & ~health).then(value).otherwise(0.0).alias("tied"),
        pl.when(pix & ~planned).then(value).otherwise(0.0).alias("pix_no_plan"),
    ]
    for name in (*CLASS_PARTS[:-1], *SPEC_PARTS, *FILED_PARTS):
        share = pl.col(f"share_{name}")
        parts.append(pl.when(planned).then(value * share).otherwise(0.0).alias(name))
    rows = rows.with_columns(*parts, planned.alias("planned"))
    groups = [
        pl.sum_horizontal(
            [pl.col(f"pix_{c.lower()}") for c in pixtext.CLASSES if pixtext.GROUPS[c] == g]
            + ([pl.col("pix_no_plan")] if g == "fungible" else [])
        ).alias(f"pix_{g}")
        for g in pixtext.GROUP_NAMES
    ]
    return rows.with_columns(groups)


def window_parts(rows: pl.DataFrame, cycle: Cycle) -> pl.DataFrame:
    """Per (`deputy`, `cd_ibge`): every part summed over the pre and the post window, and the
    window totals (`total_<w>`) as `amendments_panel.window_sums` adds them."""
    aggs = []
    for w in WINDOWS:
        inside = pl.col("ym").is_between(*getattr(cycle, w))
        aggs.append(pl.col("value").filter(inside).sum().alias(f"total_{w}"))
        aggs.extend(pl.col(p).filter(inside).sum().alias(f"obj_{w}_{p}") for p in PARTS)
    return rows.group_by("deputy", "cd_ibge").agg(aggs)


def cycle_table(
    name: str, keys: pl.DataFrame, rows: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The cycle's rows (`keys`: `deputy`, `cd_ibge`) with every part of both windows, 0
    where the deputy paid nothing; before the floor, with the window totals."""
    sums = window_parts(rows, CYCLES[name])
    value_columns = [c for c in sums.columns if c not in ("deputy", "cd_ibge")]
    table = (
        keys.select("deputy", "cd_ibge")
        .join(sums, on=["deputy", "cd_ibge"], how="left")
        .with_columns(
            pl.lit(name).alias("cycle"), *[pl.col(c).fill_null(0.0) for c in value_columns]
        )
    )
    return table.sort("deputy", "cd_ibge"), sums


def check_sums(name: str, table: pl.DataFrame, tolerance: float = TOLERANCE) -> None:
    """Before the floor: the instruments add up to the window total, and each Pix split adds
    up to the Pix total, within `tolerance` reais."""
    checks = [("instruments", "total_{w}", INSTRUMENTS)]
    checks += [(split, "obj_{w}_pix", parts) for split, parts in PIX_SPLITS.items()]
    for split, total, parts in checks:
        for w in WINDOWS:
            gap = (
                pl.sum_horizontal([pl.col(f"obj_{w}_{p}") for p in parts])
                - pl.col(total.format(w=w))
            ).abs()
            off = table.filter(gap > tolerance).height
            if off:
                write_profile(
                    "parts_add_up",
                    [("all", "inconsistent", off), ("all", "ok", table.height - off)],
                )
                raise BuildError(f"{name}: {off} rows whose {split} ({w}) do not add up")


def floor_parts(table: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """Every part below 0 (refunds netting out a window) set to 0; returns the table in
    `SCHEMA` and the number of cells set to 0."""
    columns = [c for c in SCHEMA if c.startswith("obj_")]
    floored = int(table.select(sum((pl.col(c) < 0).cast(pl.Int64) for c in columns)).sum().item())
    out = table.with_columns(pl.col(c).clip(lower_bound=0.0) for c in columns)
    return out.select([pl.col(n).cast(t) for n, t in SCHEMA.items()]), floored


def check_rows(
    tables: dict[str, pl.DataFrame],
    keys: dict[str, pl.DataFrame],
    *,
    min_rows: int = ap.MIN_ROWS,
    max_rows: int = ap.MAX_ROWS,
) -> None:
    """The rows are the panel's rows, once each; no part is below 0. Both halves."""
    for name, table in sorted(tables.items()):
        dup = table.select(pl.struct("cycle", "deputy", "cd_ibge").is_duplicated().sum()).item()
        if dup:
            write_profile("objects_rows", [("all", "duplicate", dup), ("all", "ok", table.height)])
            raise BuildError(f"{name}: {dup} rows share a (cycle, deputy, cd_ibge)")
        panel = keys[name].select("deputy", "cd_ibge")
        extra = table.join(panel, on=["deputy", "cd_ibge"], how="anti").height
        missing = panel.join(table, on=["deputy", "cd_ibge"], how="anti").height
        if extra or missing or table.height != panel.height:
            write_profile(
                "objects_rows",
                [("all", "not_in_reference", extra), ("all", "empty", missing),
                 ("all", "ok", table.height - extra)],
            )  # fmt: skip
            raise BuildError(
                f"{name}: {table.height} rows, {panel.height} panel rows, "
                f"{extra} not the panel's, {missing} missing"
            )
        for column in SCHEMA:
            if column.startswith("obj_"):
                low = table.filter(pl.col(column) < 0).height
                if low:
                    write_profile("objects_negative", [("all", "out_of_range", low)])
                    raise BuildError(f"{name}: {low} rows have {column} below 0")
        if not min_rows <= panel.height <= max_rows:
            raise BuildError(f"{name}: {panel.height} panel rows, outside {min_rows}-{max_rows}")


def plan_coverage(
    rows: pl.DataFrame, *, first_year: int = COVERAGE_FROM
) -> dict[int, tuple[int, int, float, float]]:
    """Per payment year from `first_year`: Pix payment rows (matched to a plan, all) and Pix
    paid value (matched, all), from split payment rows of every author, both halves."""
    pix = rows.filter(pl.col("is_pix") & ((pl.col("ym") // 100) >= first_year))
    per = (
        pix.group_by((pl.col("ym") // 100).alias("year"))
        .agg(
            pl.col("planned").sum().alias("n_planned"),
            pl.len().alias("n"),
            pl.col("value").filter(pl.col("planned")).sum().alias("v_planned"),
            pl.col("value").sum().alias("v"),
        )
        .sort("year")
    )
    return {
        int(y): (int(a), int(b), float(c), float(d))
        for y, a, b, c, d in per.select("year", "n_planned", "n", "v_planned", "v").iter_rows()
    }


def check_coverage(
    coverage: dict[int, tuple[int, int, float, float]], min_share: float = MIN_PLAN_SHARE
) -> None:
    """Stops if in any year less than `min_share` of the Pix paid value matched a plan.
    Counts only in the message and the profile."""
    low = [y for y, (_, _, vp, v) in coverage.items() if v > 0 and vp < min_share * v]
    if low:
        write_profile(
            "pix_plan_coverage",
            [(str(y), "ok", a) for y, (a, _, _, _) in coverage.items()]
            + [(str(y), "not_in_reference", n - a) for y, (a, n, _, _) in coverage.items()],
        )
        y = low[0]
        a, n, _, _ = coverage[y]
        raise BuildError(
            f"{y}: less than {min_share:.0%} of Pix paid value matches a work plan "
            f"({a} of {n} Pix payment rows match)"
        )


# --- Measurement and the text check


def _row(measure: str, value: float, cycle: str | None = None, year: int | None = None,
         cls: str | None = None) -> dict[str, Any]:  # fmt: skip
    return {"measure": measure, "cycle": cycle, "year": year, "class": cls, "value": value}


def measurement(
    m: Measure,
    kappa: dict[str, float],
    plan_share: dict[str, float],
    explore_plans: pl.DataFrame,
) -> pl.DataFrame:
    """The measure's quality and exploration-half descriptions (long format)."""
    out = [_row("n_labels", float(m.n_labels))]
    out += [_row(k, v) for k, v in sorted(m.quality.items())]
    out += [_row(k, v) for k, v in sorted(kappa.items())]
    out += [_row("pix_value_with_plan", v, cycle=c) for c, v in sorted(plan_share.items())]
    plans = explore_plans.join(m.predicted, on="key", how="left").with_columns(
        pl.col("class").replace_strict(pixtext.GROUPS, default=None).alias("group"),
        pl.col("specificity").cast(pl.Utf8).alias("spec"),
    )
    for year, part in [(None, plans), *plans.group_by("year", maintain_order=False)]:
        y = None if year is None else int(year[0])
        if part.height:
            out.append(_row("legacy_share_rows", part["legacy"].mean(), year=y))
        total = part["value"].sum()
        if total <= 0:
            continue
        for measure_name, column in (
            ("class_value_share", "class"),
            ("group_value_share", "group"),
            ("specificity_value_share", "spec"),
        ):
            sums = part.group_by(column).agg(pl.col("value").sum()).sort(column)
            out += [_row(measure_name, v / total, year=y, cls=k) for k, v in sums.iter_rows()]
    frame = pl.DataFrame(out, schema=MEASUREMENT_SCHEMA, orient="row")
    return frame.sort(["measure", "cycle", "year", "class"], nulls_last=False)


def allowed_strings() -> set[str]:
    """Every text value a measurement cell may hold."""
    return (
        set(MEASURES)
        | set(pixtext.CLASSES)
        | set(pixtext.GROUP_NAMES)
        | set(CYCLES)
        | {str(s) for s in pixtext.SPECIFICITIES}
    )


def text_in_outputs(
    tables: dict[str, pl.DataFrame], meas: pl.DataFrame, notes: list[str], texts: list[str]
) -> int:
    """How many output cells or notes could hold a text of the file: a row table's text cell
    that is not a cycle or a string of digits, a measurement text cell outside its fixed
    vocabulary, or a note that contains a plan text of `NOTE_TEXT_MIN` characters or more."""
    bad = 0
    for table in tables.values():
        bad += table.filter(~pl.col("cycle").is_in(list(CYCLES))).height
        for column in ("deputy", "cd_ibge"):
            bad += table.filter(~pl.col(column).str.contains(r"^\d+$")).height
    allowed = sorted(allowed_strings())
    for column in ("measure", "cycle", "class"):
        bad += meas.filter(pl.col(column).is_not_null() & ~pl.col(column).is_in(allowed)).height
    joined = "\n".join(notes).upper()
    bad += sum(1 for t in set(texts) if len(t) >= NOTE_TEXT_MIN and t in joined)
    return bad


# --- Build


def build(
    store: Store,
    general_manifest: dict[str, Any],
    cgu_manifest: dict[str, Any],
    results_manifest: dict[str, Any],
    candidates_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    chamber_manifest: dict[str, Any],
    *,
    labels_path: Path,
    codebook_path: Path,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    cycles: tuple[str, ...] = tuple(CYCLES),
    min_rows: int = ap.MIN_ROWS,
    max_rows: int = ap.MAX_ROWS,
    min_labels: int = MIN_LABELS,
    coverage_from: int = COVERAGE_FROM,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the per-cycle, per-half Parquet files and the measurement file; return the
    manifest.

    Exploration files and `measurement.parquet` go to `<derived_root><hash>/`, confirmation
    files to `<sealed_root><hash>/`. The caller writes the manifest when `status` is
    `created`. The build never lists, reads or checks the sealed folder. Nothing is uploaded
    unless every check has passed.
    """
    explore, split_shas = read_lists(store)
    general, vote_entries, turnout_entries = amonthly.entries(
        general_manifest, results_manifest, cycles
    )
    cgu_entry = _file(cgu_manifest, "/EmendasParlamentares.zip")
    muni_entry = _file(municipalities_manifest, "/municipalities.parquet")
    cand_entry = _file(candidates_manifest, "/candidates.parquet")
    chamber_entry = _file(chamber_manifest, "/deputados.csv")
    files = [
        cgu_entry,
        muni_entry,
        cand_entry,
        chamber_entry,
        *general.values(),
        *vote_entries.values(),
        *turnout_entries.values(),
    ]
    labels_text = labels_path.read_text(encoding="utf-8")
    codebook_text = codebook_path.read_text(encoding="utf-8")
    hashed = input_hash(files, split_shas, [labels_text, codebook_text], cycles)
    derived_prefix = f"{derived_root}{hashed}/"
    sealed_prefix = f"{sealed_root}{hashed}/"
    if store.exists(derived_prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(derived_prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    doc = pixtext.load_labels(labels_path)
    kappa = check_labels(doc, codebook_text)

    munis = _fetch_frame(store, muni_entry, tmp_dir, ap.MUNICIPALITY_COLUMNS)
    if munis.filter(pl.col("cd_tse").is_not_null())["cd_tse"].is_duplicated().any():
        raise BuildError("municipalities: a cd_tse appears twice")
    attrs = _fetch_frame(store, cand_entry, tmp_dir, ap.CANDIDATE_COLUMNS)
    chamber_path = _fetch(store, chamber_entry, tmp_dir)
    try:
        chamber = ap.read_chamber(chamber_path)
    finally:
        chamber_path.unlink(missing_ok=True)
    cgu_path = _fetch(store, cgu_entry, tmp_dir)
    try:
        raw = ap.read_cgu(cgu_path)
        years, _ = ap.read_amendment_years(cgu_path)
        functions, function_counts = read_functions(cgu_path)
        plans = pixtext.plans_with_municipality(pixtext.read_plans(cgu_path), munis)
    finally:
        cgu_path.unlink(missing_ok=True)
    individual, stats = ap.parse_payments(raw)
    del raw
    ap.check_payment_stats(stats)
    years_by_author = ap.author_years(individual, years)
    paid, dropped = ap.match_recipients(individual.filter(ap.in_windows(cycles)), munis)
    del individual

    m = measure(plans, doc["labels"], min_labels=min_labels)
    shares, zero_value_keys = plan_shares(plans, m.predicted)
    split = split_payments(paid.filter(pl.col("cd_ibge").is_not_null()), functions, shares)
    coverage = plan_coverage(split, first_year=coverage_from)

    tables: dict[str, pl.DataFrame] = {}
    keys: dict[str, pl.DataFrame] = {}
    plan_share: dict[str, float] = {}
    notes: list[str] = []
    explore_ids = sorted(explore)
    for name in cycles:
        cy = CYCLES[name]
        link = ap.cycle_link(name, store, general, paid, years_by_author, chamber, tmp_dir)
        mayors = ap._mayors(store, vote_entries, turnout_entries, cy.m, tmp_dir, attrs)
        deputies = link.deputies.select("sq", "uf", "party", "elected")
        panel_rows = ap.panel_keys(deputies, mayors, munis).select("deputy", "cd_ibge")
        linked = link.linked.filter(pl.col("cd_ibge").is_not_null()).select(
            "deputy", "amendment", "cd_ibge", "ym", "value", "pix"
        )
        rows = split_payments(linked, functions, shares)
        table, _ = cycle_table(name, panel_rows, rows)
        check_sums(name, table)
        half = table.filter(pl.col("cd_ibge").is_in(explore_ids))
        pix_post = half["obj_post_pix"].sum()
        if pix_post > 0:
            plan_share[name] = float((pix_post - half["obj_post_pix_no_plan"].sum()) / pix_post)
        tables[name], floored = floor_parts(table)
        keys[name] = panel_rows
        share = link.counts["money_share"]
        notes.append(
            f"{name}: rows={half.height}, panel_rows={panel_rows.height}, "
            f"deputy_authors={link.counts['deputies']}, "
            f"money_share={'none' if share is None else f'{share:.4f}'}, "
            f"cells_floored_to_zero={floored}"
        )

    check_rows(tables, keys, min_rows=min_rows, max_rows=max_rows)
    check_coverage(coverage)

    unlabelled_codes = (
        split.filter(~pl.col("is_pix") & pl.col("health").is_null())
        .group_by((pl.col("ym") // 100).alias("year"))
        .len()
    )
    explore_plans = plans.filter(pl.col("cd_ibge").is_in(explore_ids))
    meas = measurement(m, kappa, plan_share, explore_plans)
    notes += [
        f"plan_rows={plans.height}, "
        f"plan_rows_with_municipality={plans['cd_ibge'].drop_nulls().len()}, "
        f"plan_rows_no_municipality={plans['name_key'].null_count()}, "
        f"plan_texts={plans['key'].n_unique()}, legacy_plan_rows={int(plans['legacy'].sum())}",
        f"labels={len(doc['labels'])}, labels_found={m.n_labels}, label_model={doc['model']}, "
        f"label_date={doc['date']}, codebook_sha256={doc['codebook_sha256']}",
        f"plan_keys_with_zero_value_split_by_count={zero_value_keys}",
        f"amendment_codes={function_counts['codes']}, "
        f"codes_with_several_functions={function_counts['multi_function']}",
        "non_pix_rows_with_no_function="
        + ap._years(dict(unlabelled_codes.sort("year").iter_rows())),
        "pix_rows_matched_to_a_plan="
        + ",".join(f"{y}:{a}/{n}" for y, (a, n, _, _) in coverage.items()),
        f"dropped_recipient_rows_no_municipality={ap._years(dropped['no_municipality'])}",
        f"dropped_recipient_rows_unmatched={ap._years(dropped['unmatched'])}",
        *ap.placeholder_notes(dropped),
    ]

    bad = text_in_outputs(tables, meas, notes, plans["text"].to_list())
    if bad:
        write_profile("text_in_outputs", [("all", "other", bad)])
        raise BuildError(f"{bad} output cells or notes could hold a text of the CGU file")
    del plans

    derived_dir, sealed_dir = tmp_dir / "derived", tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    local: list[tuple[Path, Path]] = []
    for name, table in tables.items():
        is_explore = table["cd_ibge"].is_in(explore_ids)
        sealed_file, derived_file = sealed_dir / output_name(name), derived_dir / output_name(name)
        table.filter(~is_explore).write_parquet(sealed_file)
        table.filter(is_explore).write_parquet(derived_file)
        local.append((sealed_file, derived_file))
    meas_file = derived_dir / MEASUREMENT
    meas.write_parquet(meas_file)

    # Every check has passed. Sealed first; the manifest is the caller's last step.
    sealed_files = [_upload(store, sealed_prefix + p.name, p) for p, _ in local]
    out_files = [_upload(store, derived_prefix + p.name, p) for _, p in local]
    out_files.append(_upload(store, derived_prefix + MEASUREMENT, meas_file))
    manifest = build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=derived_prefix,
        files=out_files,
        inputs=[
            m_["gcs_prefix"] + MANIFEST_NAME
            for m_ in (
                general_manifest,
                cgu_manifest,
                results_manifest,
                candidates_manifest,
                municipalities_manifest,
                chamber_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
