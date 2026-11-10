"""Build located polling places of Brazil, one Parquet per election year.

Contract of the output: data/contracts/polling_places.md. Pitfalls of the source
files: data/fixtures/tse/README.md and data/fixtures/hidalgo/README.md.

Coordinates come from the TSE polling-place files (2012 onward) where they are
not -1, and from Hidalgo's geocoded stations otherwise. 2008 uses Hidalgo only.
The postal code (`nr_cep`) follows the same order. Phone numbers are never
selected, so they cannot reach the output.
"""

from __future__ import annotations

import fnmatch
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import polars as pl

from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "polling_places"
YEARS = (2008, 2012, 2016, 2020, 2024)
HIDALGO_ONLY_YEARS = (2008,)
GEOCODED_FILE = "geocoded_polling_stations.csv.gz"
PANEL_FILE = "panel_ids.csv.gz"
TSE_MEMBER = "eleitorado_local_votacao_*.csv"
MAX_MISSING_SHARE = 0.05
# Coordinates that are present but do not parse as numbers become null and are
# counted per year and source; above this share of a year's rows the build
# stops, because a systematic format change (decimal commas, say) would
# otherwise be hidden by the Hidalgo fallback. Checked on the real files
# (2026-11-02): none in the TSE files for 2012-2024; 3 empty Hidalgo rows.
MAX_UNPARSED_SHARE = 0.001
# The TSE's only "no coordinate" code in these files is -1 (checked for
# 2012-2024; -3 and -4 do not occur in the coordinate columns). Values written
# without a leading zero near the equator (".0075", "-.0065") parse correctly.
NO_COORDINATE = "-1"

# The only TSE columns ever read. NR_TELEFONE_LOCAL is deliberately absent.
TSE_COLUMNS = (
    "aa_eleicao",
    "cd_municipio",
    "nr_zona",
    "nr_local_votacao",
    "nm_local_votacao",
    "ds_endereco",
    "nm_bairro",
    "nr_cep",
    "nr_latitude",
    "nr_longitude",
)
PLACE = ["cd_municipio", "nr_zona", "nr_local_votacao"]
KEY = ["ano", "cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
OUTPUT_COLUMNS = [
    "ano",
    "cd_ibge",
    "sg_ue",
    "nr_zona",
    "nr_local_votacao",
    "lat",
    "long",
    "coord_source",
    "conf_dist_km",
    "panel_id",
    "nm_local_votacao",
    "ds_endereco",
    "nm_bairro",
    "nr_cep",
]


class BuildError(ValueError):
    """Raised when an input or a check breaks the contract."""


def output_name(year: int) -> str:
    return f"polling_places_{year}.parquet"


# --- Readers


def _tse_member(zf: zipfile.ZipFile) -> str:
    members = [n for n in zf.namelist() if fnmatch.fnmatch(n.lower(), TSE_MEMBER)]
    if len(members) != 1:
        raise BuildError(f"expected one {TSE_MEMBER} member, found {len(members)}")
    return members[0]


def read_tse_year(zip_path: Path) -> pl.DataFrame:
    """The allowlisted columns of one TSE polling-place zip, as text.

    A column a year lacks is filled with null. Latitude and longitude become
    floats; `-1` (the TSE's "no coordinate") and text that is not a number
    become null. Zone and polling-place number are integers. `coord_unparsed`
    flags rows whose coordinate text was present (not empty, not `-1`) but did
    not parse; the raw text itself is not kept, only counted (see
    `check_unparsed`).
    """
    with zipfile.ZipFile(zip_path) as zf:
        raw = zf.read(_tse_member(zf)).decode("latin-1")
    df = pl.read_csv(io.BytesIO(raw.encode("utf-8")), separator=";", infer_schema=False)
    df = df.rename({c: c.strip().lower() for c in df.columns})
    df = df.select(
        pl.col(c).str.strip_chars() if c in df.columns else pl.lit(None, dtype=pl.String).alias(c)
        for c in TSE_COLUMNS
    )
    return df.with_columns(
        pl.col("cd_municipio").str.zfill(5),
        pl.col("nr_zona").cast(pl.Int32),
        pl.col("nr_local_votacao").cast(pl.Int32),
        _cep("nr_cep"),
        _coordinate("nr_latitude").alias("lat"),
        _coordinate("nr_longitude").alias("long"),
        (_unparsed("nr_latitude") | _unparsed("nr_longitude")).alias("coord_unparsed"),
    ).drop("nr_latitude", "nr_longitude")


def _cep(column: str) -> pl.Expr:
    """Postal code as 8 digits with leading zeros; null unless 1-8 digits once stripped.

    `-1` (the TSE's "none"), empty text and anything else that is not 1-8 digits
    become null. The original text is not kept.
    """
    text = pl.col(column).str.strip_chars()
    return (
        pl.when(text.str.contains(r"^[0-9]{1,8}$"))
        .then(text.str.zfill(8))
        .otherwise(None)
        .alias(column)
    )


def _coordinate(column: str) -> pl.Expr:
    value = pl.col(column).cast(pl.Float64, strict=False)
    return pl.when(pl.col(column) == NO_COORDINATE).then(None).otherwise(value)


def _unparsed(column: str, missing: tuple[str, ...] = ("", NO_COORDINATE)) -> pl.Expr:
    """True where the text is present but is not a number."""
    text = pl.col(column)
    present = text.is_not_null() & ~text.is_in(list(missing))
    return (present & text.cast(pl.Float64, strict=False).is_null()).fill_null(False)


def read_hidalgo(geocoded_gz: Path, panel_gz: Path) -> pl.DataFrame:
    """Hidalgo stations with `panel_id`, one row per `local_id`.

    `cd_localidade_tse` is zero-padded to 5 digits and the panel IDs are joined on
    `local_id`. Raises if `local_id` repeats in either file, or if a station key
    (`ano`, TSE code, zone, polling-place number) repeats.
    """
    stations = pl.read_csv(
        geocoded_gz,
        columns=[
            "local_id",
            "ano",
            "cd_localidade_tse",
            "nr_zona",
            "nr_locvot",
            "nm_locvot",
            "ds_endereco",
            "ds_bairro",
            "nr_cep",
            "lat",
            "long",
            "conf_dist_km",
        ],
        infer_schema=False,
    ).select(
        pl.col("local_id"),
        pl.col("ano").cast(pl.Int32),
        pl.col("cd_localidade_tse").str.strip_chars().str.zfill(5).alias("sg_ue"),
        pl.col("nr_zona").cast(pl.Int32),
        pl.col("nr_locvot").cast(pl.Int32).alias("nr_local_votacao"),
        pl.col("nm_locvot").alias("nm_local_votacao"),
        pl.col("ds_endereco"),
        pl.col("ds_bairro").alias("nm_bairro"),
        _cep("nr_cep"),
        pl.col("lat").cast(pl.Float64, strict=False),
        pl.col("long").cast(pl.Float64, strict=False),
        pl.col("conf_dist_km").cast(pl.Float64, strict=False),
        (
            _unparsed("lat", ("", "NA"))
            | _unparsed("long", ("", "NA"))
            | _unparsed("conf_dist_km", ("", "NA"))
        ).alias("coord_unparsed"),
    )
    panel = pl.read_csv(panel_gz, columns=["panel_id", "local_id"], infer_schema=False)
    if stations["local_id"].is_duplicated().any():
        raise BuildError("Hidalgo: local_id repeats in the geocoded file")
    if panel["local_id"].is_duplicated().any():
        raise BuildError("Hidalgo: local_id repeats in panel_ids")
    if stations.select("ano", "sg_ue", "nr_zona", "nr_local_votacao").is_duplicated().any():
        raise BuildError("Hidalgo: (ano, cd_localidade_tse, nr_zona, nr_locvot) repeats")
    return stations.join(panel, on="local_id", how="left")


# --- Collapse and combine


def collapse_places(rows: pl.DataFrame) -> tuple[pl.DataFrame, int, int]:
    """One row per (`cd_municipio`, `nr_zona`, `nr_local_votacao`).

    `rows` has one row per section; `lat`, `long` and `nr_cep` are null where
    missing. The place's coordinate is the most frequent non-missing pair; ties
    go to the smallest (`lat`, `long`). The place's `nr_cep` is the most frequent
    non-missing code, ties to the smallest. Also returns how many places have
    more than one distinct pair, and how many more than one distinct CEP. Names
    and address are the smallest value among the rows.
    """
    meta = rows.group_by(PLACE).agg(
        pl.col("nm_local_votacao").drop_nulls().min(),
        pl.col("ds_endereco").drop_nulls().min(),
        pl.col("nm_bairro").drop_nulls().min(),
    )
    pairs = (
        rows.filter(pl.col("lat").is_not_null() & pl.col("long").is_not_null())
        .group_by(PLACE + ["lat", "long"])
        .agg(pl.len().alias("n"))
    )
    several = pairs.group_by(PLACE).agg(pl.len().alias("k")).filter(pl.col("k") > 1).height
    best = pairs.sort(PLACE + ["n", "lat", "long"], descending=[False] * 3 + [True, False, False])
    best = best.unique(subset=PLACE, keep="first", maintain_order=True).drop("n")
    codes = (
        rows.filter(pl.col("nr_cep").is_not_null())
        .group_by(PLACE + ["nr_cep"])
        .agg(pl.len().alias("n"))
    )
    several_cep = codes.group_by(PLACE).agg(pl.len().alias("k")).filter(pl.col("k") > 1).height
    best_cep = codes.sort(PLACE + ["n", "nr_cep"], descending=[False] * 3 + [True, False])
    best_cep = best_cep.unique(subset=PLACE, keep="first", maintain_order=True).drop("n")
    places = meta.join(best, on=PLACE, how="left").join(best_cep, on=PLACE, how="left")
    return places, several, several_cep


def place_table(
    year: int,
    hidalgo: pl.DataFrame,
    tse_rows: pl.DataFrame | None,
    municipalities: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """The polling places of one year, every municipality with a TSE code, and counts.

    `municipalities` has `cd_ibge`, `cd_tse` and `uf`. `tse_rows` is the
    section-level TSE frame (`read_tse_year`); it is not used, and may be None,
    for the years in HIDALGO_ONLY_YEARS.
    """
    legal = municipalities.filter(pl.col("cd_tse").is_not_null()).select(
        "cd_ibge", pl.col("cd_tse").alias("sg_ue"), "uf"
    )
    if legal["sg_ue"].is_duplicated().any():
        raise BuildError("the municipalities table repeats a cd_tse")
    stations = hidalgo.filter(pl.col("ano") == year).join(legal.drop("uf"), on="sg_ue", how="inner")
    stations = stations.select(
        "cd_ibge",
        "sg_ue",
        "nr_zona",
        "nr_local_votacao",
        "panel_id",
        pl.col("lat").alias("h_lat"),
        pl.col("long").alias("h_long"),
        pl.col("conf_dist_km").alias("h_conf"),
        pl.col("nm_local_votacao").alias("h_name"),
        pl.col("ds_endereco").alias("h_address"),
        pl.col("nm_bairro").alias("h_bairro"),
        pl.col("nr_cep").alias("h_cep"),
    )
    two_pair = two_cep = 0
    unmatched = 0
    if year in HIDALGO_ONLY_YEARS:
        table = stations.with_columns(
            pl.col("h_name").alias("nm_local_votacao"),
            pl.col("h_address").alias("ds_endereco"),
            pl.col("h_bairro").alias("nm_bairro"),
            pl.lit(None, dtype=pl.Float64).alias("t_lat"),
            pl.lit(None, dtype=pl.Float64).alias("t_long"),
            pl.lit(None, dtype=pl.String).alias("t_cep"),
        )
    else:
        if tse_rows is None:
            raise BuildError(f"{year}: the TSE polling-place file is needed")
        known_tse = tse_rows.filter(pl.col("cd_municipio").is_in(legal["sg_ue"].to_list()))
        places, two_pair, two_cep = collapse_places(known_tse)
        places = places.rename(
            {"lat": "t_lat", "long": "t_long", "nr_cep": "t_cep", "cd_municipio": "sg_ue"}
        )
        keys = ["sg_ue", "nr_zona", "nr_local_votacao"]
        unmatched = stations.join(places.select(keys), on=keys, how="anti").height
        table = places.join(legal.drop("uf"), on="sg_ue", how="inner")
        table = table.join(
            stations.drop("cd_ibge"), on=keys, how="left", validate="1:1"
        ).with_columns(
            pl.col("nm_local_votacao").fill_null(pl.col("h_name")),
            pl.col("ds_endereco").fill_null(pl.col("h_address")),
            pl.col("nm_bairro").fill_null(pl.col("h_bairro")),
        )
    has_tse = pl.col("t_lat").is_not_null() & pl.col("t_long").is_not_null()
    has_hidalgo = pl.col("h_lat").is_not_null() & pl.col("h_long").is_not_null()
    source = pl.when(has_tse).then(pl.lit("tse")).when(has_hidalgo).then(pl.lit("hidalgo"))
    out = table.select(
        pl.lit(year, dtype=pl.Int32).alias("ano"),
        "cd_ibge",
        "sg_ue",
        "nr_zona",
        "nr_local_votacao",
        pl.when(has_tse).then(pl.col("t_lat")).otherwise(pl.col("h_lat")).alias("lat"),
        pl.when(has_tse).then(pl.col("t_long")).otherwise(pl.col("h_long")).alias("long"),
        source.alias("coord_source"),
        pl.when(has_tse).then(pl.lit(0.0)).otherwise(pl.col("h_conf")).alias("conf_dist_km"),
        "panel_id",
        "nm_local_votacao",
        "ds_endereco",
        "nm_bairro",
        # The TSE's code where it has one, otherwise Hidalgo's (all of 2008).
        pl.coalesce("t_cep", "h_cep").alias("nr_cep"),
    )
    # The conf_dist_km of a place without any coordinate means nothing.
    out = out.with_columns(
        pl.when(pl.col("coord_source").is_null())
        .then(None)
        .otherwise(pl.col("conf_dist_km"))
        .alias("conf_dist_km")
    ).sort(KEY)
    per_state = (
        out.join(legal.select("cd_ibge", "uf"), on="cd_ibge", how="left")
        .with_columns(pl.col("uf").fill_null("??"))
        .group_by("uf")
        .len()
        .sort("uf")
    )
    stats: dict[str, Any] = {
        "by_state": dict(zip(per_state["uf"].to_list(), per_state["len"].to_list(), strict=True)),
        "cep_missing": out["nr_cep"].null_count(),
        "two_cep": two_cep,
        "rows": out.height,
        "missing": out.filter(pl.col("coord_source").is_null()).height,
        "tse": out.filter(pl.col("coord_source") == "tse").height,
        "hidalgo": out.filter(pl.col("coord_source") == "hidalgo").height,
        "two_pair": two_pair,
        "with_panel": out["panel_id"].count(),
        "hidalgo_not_in_tse": unmatched,
    }
    return out, stats


# --- Checks


def check_key(df: pl.DataFrame) -> None:
    repeated = df.select(KEY).is_duplicated().sum()
    if repeated:
        raise BuildError(f"{repeated} rows repeat (ano, cd_ibge, sg_ue, nr_zona, nr_local_votacao)")


def check_municipalities(df: pl.DataFrame, codes: set[str]) -> None:
    bad = df.filter(pl.col("cd_ibge").is_null() | ~pl.col("cd_ibge").is_in(list(codes)))
    if bad.height:
        raise BuildError(f"{bad.height} rows have a cd_ibge missing from the municipalities table")


def check_unparsed(year: int, source: str, rows: int, unparsed: int, max_share: float) -> None:
    """Stop when too many present coordinates failed to parse."""
    if rows and unparsed / rows > max_share:
        raise BuildError(
            f"{year}: {unparsed} of {rows} {source} rows have coordinates that are not numbers "
            f"(max share {max_share}); check the file's number format"
        )


def check_coverage(year: int, rows: int, missing: int, max_share: float) -> None:
    if rows == 0:
        raise BuildError(f"{year}: no polling places")
    if missing / rows >= max_share:
        raise BuildError(
            f"{year}: {missing} of {rows} places have no coordinate (max share {max_share})"
        )


# --- Build


def _file(manifest: dict[str, Any], suffix: str) -> dict[str, Any]:
    found = [f for f in manifest["files"] if f["path"].endswith(suffix)]
    if len(found) != 1:
        raise BuildError(f"{manifest.get('dataset')}: expected one file ending {suffix}")
    return found[0]


def _tse_entries(tse_manifest: dict[str, Any], years: tuple[int, ...]) -> dict[int, dict[str, Any]]:
    return {
        y: _file(tse_manifest, f"eleitorado_local_votacao_{y}.zip")
        for y in years
        if y not in HIDALGO_ONLY_YEARS
    }


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


def _note(year: int, s: dict[str, Any]) -> str:
    rows = s["rows"]
    by_state = " ".join(f"{u}:{n}" for u, n in sorted(s["by_state"].items()))
    return (
        f"{year}: rows={rows}, missing_coord_share={s['missing'] / rows:.4f}, "
        f"tse={s['tse']}, hidalgo={s['hidalgo']}, two_pair_places={s['two_pair']}, "
        f"panel_id_share={s['with_panel'] / rows:.4f}, "
        f"hidalgo_stations_not_in_tse={s['hidalgo_not_in_tse']}, "
        f"tse_unparsed={s.get('tse_unparsed', 0)}, "
        f"hidalgo_unparsed={s.get('hidalgo_unparsed', 0)}, "
        f"tse_other_election_year_rows={s.get('tse_other_year', 0)}, "
        f"cep_missing_share={s['cep_missing'] / rows:.4f}, two_cep_places={s['two_cep']}, "
        f"places_by_state=[{by_state}]"
    )


def build(
    store: Store,
    tse_manifest: dict[str, Any],
    hidalgo_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    years: tuple[int, ...] = YEARS,
    max_missing_share: float = MAX_MISSING_SHARE,
    max_unparsed_share: float = MAX_UNPARSED_SHARE,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one Parquet per year into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status`
    is `created`. When the output path already has a manifest, nothing is read or
    written and the status is `unchanged`.
    """
    tse_entries = _tse_entries(tse_manifest, years)
    geocoded_entry = _file(hidalgo_manifest, GEOCODED_FILE)
    panel_entry = _file(hidalgo_manifest, PANEL_FILE)
    mun_entry = _file(municipalities_manifest, ".parquet")
    entries = [geocoded_entry, panel_entry, mun_entry, *tse_entries.values()]

    prefix = f"{derived_root}{input_hash(entries, years)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    hidalgo = read_hidalgo(
        _fetch(store, geocoded_entry, tmp_dir), _fetch(store, panel_entry, tmp_dir)
    )
    municipalities = pl.read_parquet(
        _fetch(store, mun_entry, tmp_dir), columns=["cd_ibge", "cd_tse", "uf"]
    )
    codes = set(municipalities.filter(pl.col("cd_tse").is_not_null())["cd_ibge"].to_list())

    # Every year is built and checked locally first; nothing reaches the store
    # unless all of them pass, so a failed run leaves no partial output.
    local: list[tuple[int, Path]] = []
    notes: list[str] = []
    for y in sorted(years):
        tse_rows = None
        tse_unparsed = tse_other_year = 0
        if y in tse_entries:
            tse_rows = read_tse_year(_fetch(store, tse_entries[y], tmp_dir))
            # A file can carry rows of a later supplementary election; keep only
            # this election year and count the rest (none in 2012-2024 so far).
            other = pl.col("aa_eleicao").is_not_null() & (pl.col("aa_eleicao") != str(y))
            tse_other_year = tse_rows.filter(other).height
            tse_rows = tse_rows.filter(~other)
            tse_unparsed = int(tse_rows["coord_unparsed"].sum())
            check_unparsed(y, "TSE", tse_rows.height, tse_unparsed, max_unparsed_share)
        year_stations = hidalgo.filter(pl.col("ano") == y)
        hidalgo_unparsed = int(year_stations["coord_unparsed"].sum())
        check_unparsed(y, "Hidalgo", year_stations.height, hidalgo_unparsed, max_unparsed_share)
        table, stats = place_table(y, hidalgo, tse_rows, municipalities)
        stats.update(
            tse_unparsed=tse_unparsed,
            hidalgo_unparsed=hidalgo_unparsed,
            tse_other_year=tse_other_year,
        )
        del tse_rows
        check_key(table)
        check_municipalities(table, codes)
        check_coverage(y, stats["rows"], stats["missing"], max_missing_share)
        path = tmp_dir / output_name(y)
        table.select(OUTPUT_COLUMNS).write_parquet(path)
        local.append((y, path))
        notes.append(_note(y, stats))

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
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (tse_manifest, hidalgo_manifest, municipalities_manifest)
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
