"""Match every polling place to at most one INEP school in the same municipality.

Contract of the output: data/contracts/school_polling_match.md.

The rules and thresholds (campaign 0006, step s9) are fixed before any real match
is run; changing them needs a new task. Names and addresses are read to score a
pair and are never written to the output.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import polars as pl

from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "school_polling_match"
YEARS = (2008, 2012, 2016, 2020, 2024)
KEY = ["ano", "cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
OUTPUT_COLUMNS = [
    *KEY,
    "id_escola",
    "rede",
    "confidence",
    "name_sim",
    "addr_sim",
    "cep_equal",
    "dist_km",
    "n_candidates",
]
PLACE_COLUMNS = [*KEY, "nm_local_votacao", "ds_endereco", "nr_cep", "lat", "long"]
SCHOOL_COLUMNS = [
    "id_escola",
    "nome_escola",
    "id_municipio",
    "rede",
    "endereco",
    "numero",
    "cep",
    "latitude",
    "longitude",
]
NAME_STOPWORDS = frozenset(
    """ESCOLA ESC EMEF EMEI EMEB EMEIEF EEEF EEEFM EE EM EEM EF MUNICIPAL MUN
    ESTADUAL EST COLEGIO COL UNIDADE ESCOLAR UE CENTRO EDUCACIONAL CE INSTITUTO
    DE DA DO DAS DOS ENSINO FUNDAMENTAL MEDIO INFANTIL BASICA PROF PROFA
    PROFESSOR PROFESSORA DR DRA DONA DOM""".split()
)
HIGH_NAME = 0.90
HIGH_ADDRESS = 0.80
MEDIUM_NAME_WITH_SUPPORT = 0.75
LOW_NAME = 0.60
NEAR_KM = 1.0
EARTH_RADIUS_KM = 6371.0088
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
LEVELS = ("high", "medium", "low", "none")


class BuildError(ValueError):
    """Raised when an input or a check breaks the contract."""


def output_name(year: int) -> str:
    return f"school_polling_match_{year}.parquet"


# --- Text and scores


def normalise(text: str | None, *, name: bool = False) -> str:
    """Upper case, no accents, every non-alphanumeric character a space, single spaces.

    For a name, one-letter tokens and the `NAME_STOPWORDS` are also dropped.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c)).upper()
    tokens = re.sub(r"[^A-Z0-9]+", " ", ascii_text).split()
    if name:
        tokens = [t for t in tokens if len(t) > 1 and t not in NAME_STOPWORDS]
    return " ".join(tokens)


def haversine_km(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> float | None:
    """Great-circle distance in km; None when any coordinate is missing."""
    values = [lat1, lon1, lat2, lon2]
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in values):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = p2 - p1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def confidence(name_sim: float, addr_sim: float, cep_equal: bool, near: bool) -> str:
    """`high`, `medium`, `low` or `none` for one pair, by the fixed rules."""
    if name_sim >= HIGH_NAME and (cep_equal or addr_sim >= HIGH_ADDRESS or near):
        return "high"
    if name_sim >= HIGH_NAME or (name_sim >= MEDIUM_NAME_WITH_SUPPORT and (cep_equal or near)):
        return "medium"
    if name_sim >= LOW_NAME:
        return "low"
    return "none"


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _address(street: str | None, number: str | None) -> str:
    return normalise(" ".join(p for p in (street, number) if p))


def _present(value: str | None) -> str:
    return (value or "").strip()


# --- Matching


def match_year(places: pl.DataFrame, schools: pl.DataFrame) -> pl.DataFrame:
    """One row per polling place with its best school (or `none`), sorted by `KEY`.

    `places` has `PLACE_COLUMNS`, `schools` has `SCHOOL_COLUMNS`. Only schools of
    the place's own municipality (`cd_ibge` = `id_municipio`) are compared.
    """
    places = places.sort(KEY)
    by_municipality: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in schools.iter_rows(named=True):
        by_municipality[row["id_municipio"]].append(
            {
                "id": row["id_escola"],
                "rede": row["rede"],
                "name": normalise(row["nome_escola"], name=True),
                "address": _address(row["endereco"], row["numero"]),
                "cep": _present(row["cep"]),
                "lat": row["latitude"],
                "lon": row["longitude"],
            }
        )

    ids: list[str | None] = []
    redes: list[str | None] = []
    levels: list[str] = []
    name_sims: list[float | None] = []
    addr_sims: list[float | None] = []
    cep_equals: list[bool | None] = []
    dists: list[float | None] = []
    n_candidates: list[int] = []

    for place in places.iter_rows(named=True):
        name = normalise(place["nm_local_votacao"], name=True)
        address = normalise(place["ds_endereco"])
        cep = _present(place["nr_cep"])
        matcher = SequenceMatcher(None, "", name)  # caches the place name as seq2
        best: tuple | None = None
        count = 0
        for school in by_municipality.get(place["cd_ibge"], ()):
            if not name or not school["name"]:
                continue
            matcher.set_seq1(school["name"])
            # The cheap upper bounds never skip a pair whose ratio reaches the floor.
            if matcher.real_quick_ratio() < LOW_NAME or matcher.quick_ratio() < LOW_NAME:
                continue
            name_sim = matcher.ratio()
            if name_sim < LOW_NAME:
                continue
            count += 1
            addr_sim = _ratio(school["address"], address)
            cep_equal = bool(cep) and cep == school["cep"]
            dist = haversine_km(place["lat"], place["long"], school["lat"], school["lon"])
            level = confidence(name_sim, addr_sim, cep_equal, dist is not None and dist <= NEAR_KM)
            order = (
                -CONFIDENCE_RANK[level],
                -name_sim,
                -addr_sim,
                dist is None,
                dist or 0.0,
                school["id"],
            )
            if best is None or order < best[0]:
                best = (order, school, level, name_sim, addr_sim, cep_equal, dist)
        n_candidates.append(count)
        if best is None:
            ids.append(None)
            redes.append(None)
            levels.append("none")
            name_sims.append(None)
            addr_sims.append(None)
            cep_equals.append(None)
            dists.append(None)
        else:
            _, school, level, name_sim, addr_sim, cep_equal, dist = best
            ids.append(school["id"])
            redes.append(school["rede"])
            levels.append(level)
            name_sims.append(name_sim)
            addr_sims.append(addr_sim)
            cep_equals.append(cep_equal)
            dists.append(dist)

    return places.select(KEY).with_columns(
        pl.Series("id_escola", ids, dtype=pl.Utf8),
        pl.Series("rede", redes, dtype=pl.Utf8),
        pl.Series("confidence", levels, dtype=pl.Utf8),
        pl.Series("name_sim", name_sims, dtype=pl.Float64),
        pl.Series("addr_sim", addr_sims, dtype=pl.Float64),
        pl.Series("cep_equal", cep_equals, dtype=pl.Boolean),
        pl.Series("dist_km", dists, dtype=pl.Float64),
        pl.Series("n_candidates", n_candidates, dtype=pl.Int64),
    )


# --- Checks


def check_one_row_per_place(source: pl.DataFrame, out: pl.DataFrame) -> None:
    """The key is unique in both, and the output has the key set of `polling_places`."""
    if source.select(KEY).is_duplicated().any():
        raise BuildError("a polling place appears more than once in the input")
    if out.select(KEY).is_duplicated().any():
        raise BuildError("a polling place appears more than once in the output")
    if out.height != source.height:
        raise BuildError(f"{out.height} output rows for {source.height} polling places")
    if source.select(KEY).join(out.select(KEY), on=KEY, how="anti").height:
        raise BuildError("a polling place is missing from the output")


def check_schools(schools: pl.DataFrame) -> None:
    if schools["id_escola"].is_null().any() or schools["id_escola"].is_duplicated().any():
        raise BuildError("id_escola is missing or repeated in the school catalogue")


# --- Notes


def _rate(count: int, total: int) -> str:
    return f"{count / total:.4f}" if total else "n/a"


def _note(year: int, table: pl.DataFrame) -> str:
    total = table.height
    counts = {lv: int((table["confidence"] == lv).sum()) for lv in LEVELS}
    parts = [f"{year}: places={total}"]
    parts += [f"share_{lv}={_rate(counts[lv], total)}" for lv in LEVELS]
    states = table.with_columns(state=pl.col("cd_ibge").str.slice(0, 2))
    shares: list[str] = []
    rates: list[str] = []
    for state in sorted(states["state"].unique().to_list()):
        sub = states.filter(pl.col("state") == state)
        n = sub.height
        by_level = {lv: int((sub["confidence"] == lv).sum()) for lv in LEVELS}
        shares.append(f"{state}={'/'.join(_rate(by_level[lv], n) for lv in LEVELS)}")
        rates.append(f"{state}={_rate(by_level['high'] + by_level['medium'], n)}")
    parts.append("shares_high/medium/low/none_by_state=" + " ".join(shares))
    parts.append("high_medium_rate_by_state=" + " ".join(rates))
    matched = table.filter(pl.col("id_escola").is_not_null())
    per_school = matched.group_by("id_escola").len()
    sharing = int(per_school.filter(pl.col("len") > 1)["len"].sum())
    parts.append(f"places_sharing_a_school={sharing}")
    return ", ".join(parts)


# --- Build


def _file(manifest: dict[str, Any], suffix: str) -> dict[str, Any]:
    found = [f for f in manifest["files"] if f["path"].endswith(suffix)]
    if len(found) != 1:
        raise BuildError(f"{manifest.get('dataset')}: expected one file ending {suffix}")
    return found[0]


# Every module whose code decides what this build writes. Its source is part of
# the output path. This build imports no other data-handling terrain module.
CODE_MODULES = (Path(__file__),)


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]], years: tuple[int, ...], code: list[str] | None = None
) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    return content_hash(shas, ",".join(str(y) for y in sorted(years)), *sources)


def _fetch(store: Store, entry: dict[str, Any], tmp_dir: Path) -> Path:
    target = tmp_dir / entry["path"].rsplit("/", 1)[-1]
    store.download(entry["path"], target)
    if sha256_file(target) != entry["sha256"]:
        raise BuildError(f"{target.name} does not match the sha256 in its manifest")
    return target


def build(
    store: Store,
    polling_places_manifest: dict[str, Any],
    catalogue_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    years: tuple[int, ...] = YEARS,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one Parquet per year into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status`
    is `created`. When the output path already has a manifest, nothing is read or
    written and the status is `unchanged`.
    """
    place_entries = {
        y: _file(polling_places_manifest, f"polling_places_{y}.parquet") for y in years
    }
    catalogue_entry = _file(catalogue_manifest, "inep_school_catalogue.parquet")
    entries = [*place_entries.values(), catalogue_entry]

    prefix = f"{derived_root}{input_hash(entries, years)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    schools = pl.read_parquet(_fetch(store, catalogue_entry, tmp_dir), columns=SCHOOL_COLUMNS)
    check_schools(schools)

    # Every year is built and checked locally first; nothing reaches the store
    # unless all of them pass, so a failed run leaves no partial output.
    local: list[tuple[int, Path]] = []
    notes: list[str] = []
    for y in sorted(years):
        source = pl.read_parquet(_fetch(store, place_entries[y], tmp_dir), columns=PLACE_COLUMNS)
        table = match_year(source, schools)
        check_one_row_per_place(source, table)
        path = tmp_dir / output_name(y)
        table.select(OUTPUT_COLUMNS).write_parquet(path)
        local.append((y, path))
        notes.append(_note(y, table))

    files: list[dict[str, Any]] = []
    for y, path in local:
        store.create(prefix + output_name(y), path)
        files.append(
            {
                "path": prefix + output_name(y),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )

    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=files,
        inputs=[
            m["gcs_prefix"] + MANIFEST_NAME for m in (polling_places_manifest, catalogue_manifest)
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
