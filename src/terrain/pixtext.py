"""Pix work-plan texts: keys, plan municipalities, the label file and the classifier.

Decision 0018 (measures built from text with model labels). The CGU file
`EmendasParlamentares_PlanodeTrabalhoTransferenciasEspeciais.csv` holds one row per work plan
of a Pix (transferência especial) amendment, each with a free text, `Detalhamento do Objeto`.
A model labelled a sample of exploration-half texts against the codebook
`data/reference/pix_object_codebook.md`; the labels are stored by key in
`data/reference/pix_object_labels.yaml`, never with their text. The measure is the plain,
deterministic classifier here (`make_classifier`), trained on those labels and applied by
the build `terrain.builds.amendments_objects` to every text of both halves.

Texts, and `Beneficiário`, are used in memory only. `CNPJ do Beneficiário` is never read.
No model is called here, in tests or in builds.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, cohen_kappa_score, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import FeatureUnion, Pipeline

from terrain.builds.amendments_panel import _read_member, normalise_name
from terrain.builds.polling_place_tenure import BuildError

MAX_CHARS = 600  # a normalised text is cut here
SEED = 20261121  # the sample's seed and the classifier's random_state
CV_FOLDS = 5

# The codebook's classes (data/reference/pix_object_codebook.md) and the analysis groups.
CLASSES = (
    "OBRA_VIARIA",
    "OBRA_PREDIAL",
    "MAQUINAS",
    "SAUDE",
    "EDUC_SOCIAL",
    "EVENTOS",
    "CUSTEIO_ADMIN",
    "VAGO",
    "MISTO",
)
GROUPS = {
    "OBRA_VIARIA": "visible",
    "OBRA_PREDIAL": "visible",
    "MAQUINAS": "visible",
    "EVENTOS": "visible",
    "SAUDE": "services",
    "EDUC_SOCIAL": "services",
    "CUSTEIO_ADMIN": "fungible",
    "VAGO": "fungible",
    "MISTO": "fungible",
}
GROUP_NAMES = ("visible", "services", "fungible")  # payments with no plan are fungible too
SPECIFICITIES = (0, 1, 2)

PLAN_MEMBER = "emendasparlamentares_planodetrabalhotransferenciasespeciais.csv"
# `CNPJ do Beneficiário` and `Autor da Emenda` are not selected.
PLAN_COLUMNS = {
    "amendment": "Emenda Parlamentar",
    "status": "Situação do Plano de Trabalho",
    "beneficiary": "Beneficiário",
    "uf": "UF do Beneficiário",
    "text": "Detalhamento do Objeto",
    "value": "Valor",
}
LEGACY_STATUS = "LEGADO ADPF"  # `Situação do Plano de Trabalho` of plans filed after the order
MUNICIPALITY_PREFIX = re.compile(r"^MUNICIPIO (DE|DO|DA|DOS|DAS) ")
NO_MUNICIPALITY = re.compile(r"^(ESTADO (DE|DO|DA|DOS|DAS) |DISTRITO FEDERAL$)")


# --- Text


def norm_text(text: str | None) -> str:
    """Strip, collapse spaces, upper-case and cut at `MAX_CHARS` characters."""
    if text is None:
        return ""
    return " ".join(text.split()).upper()[:MAX_CHARS]


def text_key(text: str | None) -> str:
    """SHA-256 (hex) of the normalised text: how a label is stored without its text."""
    return hashlib.sha256(norm_text(text).encode("utf-8")).hexdigest()


def plan_municipality(beneficiary: str | None, uf: str | None) -> str | None:
    """The normalised municipality name of a plan's `Beneficiário`, as `amendments_panel`
    normalises recipients; None for a state or the Federal District.

    `MUNICIPIO DE X` (or DO, DA, DOS, DAS) is X; a bare name is itself.
    """
    name = normalise_name(beneficiary)
    state = (uf or "").strip().upper()
    if not name or state == "DF" or NO_MUNICIPALITY.match(name):
        return None
    return MUNICIPALITY_PREFIX.sub("", name) or None


def amendment_year(code: pl.Expr) -> pl.Expr:
    """The budget year of an amendment: the first four digits of its 12-digit code."""
    return code.str.strip_chars().str.slice(0, 4).cast(pl.Int64, strict=False)


def brazilian_number(text: pl.Expr) -> pl.Expr:
    """`1.234,56` as a float; null where it is not a number."""
    cleaned = (
        text.str.strip_chars()
        .str.replace_all(r"R\$|\s", "")
        .str.replace_all(r"\.", "")
        .str.replace(",", ".", literal=True)
    )
    return cleaned.cast(pl.Float64, strict=False)


# --- Plans


def read_plans(zip_path: Path) -> pl.DataFrame:
    """The work plans: `amendment`, `year`, `legacy`, `uf`, `name_key`, `key`, `text`,
    `value`, one row per plan row of the file.

    `text` is the normalised text (`norm_text`), in memory only. `name_key` is the plan's
    municipality name (`plan_municipality`), null for states and the Federal District. A
    `Valor` that is not a number, or an amendment code that is not 12 digits, stops the build.
    """
    raw = _read_member(zip_path, PLAN_MEMBER, PLAN_COLUMNS)
    code = pl.col("amendment").str.strip_chars()
    bad_code = raw.filter(~code.str.contains(r"^\d{12}$").fill_null(False)).height
    if bad_code:
        raise BuildError(f"{bad_code} plan rows have an amendment code that is not 12 digits")
    value = brazilian_number(pl.col("value"))
    bad_value = raw.filter(value.is_null()).height
    if bad_value:
        raise BuildError(f"{bad_value} plan rows have a Valor that is not a number")
    names = (
        raw.select("beneficiary", "uf")
        .unique()
        .with_columns(
            pl.struct("beneficiary", "uf")
            .map_elements(
                lambda r: plan_municipality(r["beneficiary"], r["uf"]), return_dtype=pl.Utf8
            )
            .alias("name_key")
        )
    )
    texts = (
        raw.select("text")
        .unique()
        .with_columns(
            pl.col("text").map_elements(norm_text, return_dtype=pl.Utf8).alias("norm"),
        )
        .with_columns(
            pl.col("norm")
            .map_elements(lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest(), pl.Utf8)
            .alias("key")
        )
    )
    status = pl.col("status").fill_null("").map_elements(normalise_name, return_dtype=pl.Utf8)
    return (
        raw.join(names, on=["beneficiary", "uf"], how="left", nulls_equal=True)
        .join(texts, on="text", how="left", nulls_equal=True)
        .select(
            code.alias("amendment"),
            amendment_year(pl.col("amendment")).alias("year"),
            status.str.starts_with(LEGACY_STATUS).alias("legacy"),
            pl.col("uf").fill_null("").str.strip_chars().str.to_uppercase().alias("uf"),
            "name_key",
            "key",
            pl.col("norm").fill_null("").alias("text"),
            value.alias("value"),
        )
    )


def plans_with_municipality(plans: pl.DataFrame, munis: pl.DataFrame) -> pl.DataFrame:
    """Add `cd_ibge` to the plans from (`uf`, `name_key`), as `amendments_panel` matches
    recipients to (`uf`, normalised `name_ibge`). Null for states, the Federal District and
    names that match nothing."""
    lookup = (
        munis.select("cd_ibge", pl.col("uf").str.to_uppercase(), "name_ibge")
        .with_columns(
            pl.col("name_ibge").map_elements(normalise_name, return_dtype=pl.Utf8).alias("name_key")
        )
        .select("cd_ibge", "uf", "name_key")
    )
    if lookup.select(pl.struct("uf", "name_key").is_duplicated().any()).item():
        raise BuildError("municipalities: two municipalities share a state and a normalised name")
    return plans.join(lookup, on=["uf", "name_key"], how="left")


# --- The sample


def sample_keys(
    keys: pl.DataFrame, n: int, n_second: int, seed: int = SEED
) -> tuple[list[str], list[str]]:
    """Draw `n` distinct keys stratified by `year`, and `n_second` of them for a second pass.

    `keys`: `key`, `year`, one row per key (its earliest amendment year). Each year gets a
    share of `n` proportional to its keys (largest remainders, ties by year); within a year,
    keys are drawn from the sorted list with `random.Random(seed)`. Returns the sample and the
    second-pass keys, both sorted.
    """
    by_year = keys.group_by("year").agg(pl.col("key").sort()).sort("year")
    years = by_year["year"].to_list()
    pools = by_year["key"].to_list()
    total = sum(len(p) for p in pools)
    if n > total:
        raise ValueError(f"{n} keys asked for, {total} available")
    quotas = [n * len(p) / total for p in pools]
    counts = [int(q) for q in quotas]
    order = sorted(range(len(years)), key=lambda i: (-(quotas[i] - counts[i]), years[i]))
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    rng = random.Random(seed)
    chosen: list[str] = []
    for pool, k in zip(pools, counts, strict=True):
        chosen.extend(rng.sample(pool, k))
    chosen.sort()
    second = sorted(rng.sample(chosen, n_second))
    return chosen, second


# --- Labels


def load_labels(path: Path) -> dict[str, Any]:
    """The label file: its header and `labels` (key -> class, specificity, second-pass class).

    Stops on an unknown class or specificity, a key that is not a SHA-256, or a header field
    missing.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for field in ("model", "date", "codebook_sha256", "seed", "labels"):
        if field not in doc:
            raise BuildError(f"the label file has no {field}")
    for key, entry in doc["labels"].items():
        if not re.fullmatch(r"[0-9a-f]{64}", str(key)):
            raise BuildError("the label file has a key that is not a SHA-256")
        if entry.get("class") not in CLASSES or entry.get("specificity") not in SPECIFICITIES:
            raise BuildError("the label file has an unknown class or specificity")
        if "second" in entry and entry["second"] not in CLASSES:
            raise BuildError("the label file has an unknown second-pass class")
    return doc


def kappas(first: Sequence[str], second: Sequence[str]) -> dict[str, float]:
    """Cohen's kappa between two labelling passes, on classes and on groups."""
    return {
        "classes": float(cohen_kappa_score(first, second)),
        "groups": float(cohen_kappa_score([GROUPS[c] for c in first], [GROUPS[c] for c in second])),
    }


# --- The classifier


def make_classifier(seed: int = SEED) -> Pipeline:
    """TF-IDF of character n-grams (2 to 5, within words) and of words (1 to 2), then a
    logistic regression with balanced class weights and a fixed `random_state`."""
    features = FeatureUnion(
        [
            ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True)),
            ("words", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True)),
        ]
    )
    model = LogisticRegression(class_weight="balanced", random_state=seed, max_iter=5000)
    return Pipeline([("features", features), ("model", model)])


def fit_predict(
    train_texts: Sequence[str], train_labels: Sequence[Any], texts: Sequence[str], seed: int = SEED
) -> list[Any]:
    """Train on (`train_texts`, `train_labels`) and predict `texts`."""
    classifier = make_classifier(seed).fit(list(train_texts), list(train_labels))
    return classifier.predict(list(texts)).tolist()


def cross_validate(
    texts: Sequence[str], labels: Sequence[Any], seed: int = SEED, folds: int = CV_FOLDS
) -> list[Any]:
    """Out-of-fold predictions of 5-fold stratified cross-validation with a fixed seed."""
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    predicted = cross_val_predict(
        make_classifier(seed), list(texts), np.asarray(labels), cv=splitter
    )
    return predicted.tolist()


def scores(truth: Sequence[Any], predicted: Sequence[Any]) -> dict[str, float]:
    """Accuracy and macro-F1."""
    return {
        "accuracy": float(accuracy_score(truth, predicted)),
        "macro_f1": float(f1_score(truth, predicted, average="macro")),
    }
