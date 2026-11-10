"""Build the list of municipalities outside the Legal Amazon, with population.

Contract of the output: data/contracts/non_amazon_municipalities.md. The
built `municipalities` table says which municipalities are outside the Legal
Amazon; IBGE's census table `CD2022_Populacao_2010_Compatibilizada` gives
each one's 2010 population on 2022 boundaries. The output, `non_amazon.csv`,
is the input to `scripts/seal_split.py --non-amazon` (decision 0011).
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import polars as pl

import terrain.builds.municipalities as municipalities_build
from terrain.builds.municipalities import UF_BY_CODE
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.ods import read_sheet
from terrain.storage import Store

DATASET = "non_amazon_municipalities"
OUTPUT_NAME = "non_amazon.csv"
POPULATION_FILE = "CD2022_Populacao_2010_Compatibilizada_20231222.ods"
MUNICIPALITIES_FILE = "municipalities.parquet"

COL_UF = "UF"
COL_CODE_UF = "COD. UF"
COL_CODE_MUN = "COD. MUNIC"
# The header cell ends in a footnote mark ("...até 2022)1"), so match its start.
COL_POPULATION = "População 2010 (Alterações de Limites até 2022)"

_IBGE_CODE = re.compile(r"\d{7}")
_SPACES = re.compile(r"[\s  ]")


class BuildError(ValueError):
    """Raised when an input or a check breaks the contract."""


def parse_count(text: str) -> int:
    """'24 392' -> 24392. Spaces (any kind) and dots are thousands separators."""
    plain = _SPACES.sub("", text).replace(".", "")
    if not plain.isdigit():
        raise BuildError(f"population is not a whole number: {text!r}")
    return int(plain)


def _cell(row: list[str], i: int) -> str:
    return row[i].strip() if len(row) > i else ""


def read_population(ods_bytes: bytes) -> dict[str, tuple[str, int]]:
    """IBGE code -> (state letters, 2010 population on 2022 boundaries).

    The header row is the one holding `COD. MUNIC`. Rows without a two-digit
    state code and a five-digit municipality code (titles, notes) are skipped.
    """
    rows = read_sheet(ods_bytes)
    header = next((r for r in rows if COL_CODE_MUN in r), None)
    if header is None:
        raise BuildError(f"population table: no header row with {COL_CODE_MUN!r}")
    for col in (COL_UF, COL_CODE_UF):
        if col not in header:
            raise BuildError(f"population table: no column {col!r}")
    matches = [i for i, h in enumerate(header) if h.startswith(COL_POPULATION)]
    if len(matches) != 1:
        raise BuildError(f"population table: expected one column {COL_POPULATION!r}")
    at_uf, at_cuf, at_mun, at_pop = (
        header.index(COL_UF),
        header.index(COL_CODE_UF),
        header.index(COL_CODE_MUN),
        matches[0],
    )
    found: dict[str, tuple[str, int]] = {}
    for row in rows[rows.index(header) + 1 :]:
        code_uf, code_mun = _cell(row, at_cuf), _cell(row, at_mun)
        code = code_uf + code_mun
        if not (len(code_uf) == 2 and len(code_mun) == 5 and _IBGE_CODE.fullmatch(code)):
            continue
        if code in found:
            raise BuildError(f"population table: repeated code {code}")
        uf = _cell(row, at_uf).upper()
        if UF_BY_CODE.get(code[:2]) != uf:
            raise BuildError(f"population table: {code} is listed under {uf!r}")
        population = parse_count(_cell(row, at_pop))
        if population <= 0:
            raise BuildError(f"population table: {code} has population {population}")
        found[code] = (uf, population)
    if not found:
        raise BuildError("population table: no municipalities")
    return found


def non_amazon_rows(
    municipalities: pl.DataFrame, population: dict[str, tuple[str, int]]
) -> tuple[list[tuple[str, str, int]], list[str]]:
    """(code, uf, population) of every municipality outside the Legal Amazon.

    Raises if one of them has no population, or if the population table has
    a code that is not a municipality. Also returns the Legal Amazon codes
    with no population (expected: Boa Esperança do Norte, created after 2022).
    """
    table = {
        code: (uf, la)
        for code, uf, la in municipalities.select("cd_ibge", "uf", "legal_amazon").iter_rows()
    }
    unknown = sorted(set(population) - set(table))
    if unknown:
        raise BuildError(f"{len(unknown)} population codes are not municipalities: {unknown[:10]}")
    outside = sorted(code for code, (_, la) in table.items() if not la)
    missing = [code for code in outside if code not in population]
    if missing:
        raise BuildError(
            f"{len(missing)} municipalities outside the Legal Amazon have no population: "
            f"{missing[:10]}"
        )
    rows = []
    for code in outside:
        uf, value = population[code]
        if uf != table[code][0]:
            raise BuildError(f"{code}: state {uf} in the population table, {table[code][0]} in DTB")
        rows.append((code, uf, value))
    amazon_missing = sorted(
        code for code, (_, la) in table.items() if la and code not in population
    )
    return rows, amazon_missing


def to_csv(rows: list[tuple[str, str, int]]) -> bytes:
    """`code_ibge,uf,population`, sorted by code, LF line endings."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["code_ibge", "uf", "population"])
    writer.writerows(sorted(rows))
    return buf.getvalue().encode("utf-8")


# --- Build


def _file(manifest: dict[str, Any], suffix: str) -> dict[str, Any]:
    found = [f for f in manifest["files"] if f["path"].endswith(suffix)]
    if len(found) != 1:
        raise BuildError(f"{manifest.get('dataset')}: expected one file ending {suffix}")
    return found[0]


# Every module whose code decides what this build writes (UF_BY_CODE comes
# from the municipalities build); a fix to any of them gives a new path.
CODE_MODULES = (
    Path(__file__),
    Path(read_sheet.__code__.co_filename),
    Path(municipalities_build.__file__),
)


def code_sources(modules: tuple[Path, ...] = CODE_MODULES) -> list[str]:
    return [m.read_text(encoding="utf-8") for m in sorted(modules)]


def input_hash(files: list[dict[str, Any]], code: list[str] | None = None) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    return content_hash(shas, *(code_sources() if code is None else code))


def _fetch(store: Store, entry: dict[str, Any], tmp_dir: Path) -> Path:
    target = tmp_dir / entry["path"].rsplit("/", 1)[-1]
    store.download(entry["path"], target)
    if sha256_file(target) != entry["sha256"]:
        raise BuildError(f"{target.name} does not match the sha256 in its manifest")
    return target


def build(
    store: Store,
    municipalities_manifest: dict[str, Any],
    population_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build `non_amazon.csv` into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest when `status` is `created`. When the output
    path already has a manifest, nothing is read or written and the status is
    `unchanged`.
    """
    table_entry = _file(municipalities_manifest, MUNICIPALITIES_FILE)
    population_entry = _file(population_manifest, POPULATION_FILE)
    prefix = f"{derived_root}{input_hash([table_entry, population_entry])}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    municipalities = pl.read_parquet(_fetch(store, table_entry, tmp_dir))
    population = read_population(_fetch(store, population_entry, tmp_dir).read_bytes())
    rows, amazon_missing = non_amazon_rows(municipalities, population)

    out_path = tmp_dir / OUTPUT_NAME
    out_path.write_bytes(to_csv(rows))
    store.create(prefix + OUTPUT_NAME, out_path)

    by_uf: dict[str, int] = {}
    for _, uf, _ in rows:
        by_uf[uf] = by_uf.get(uf, 0) + 1
    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=[
            {
                "path": prefix + OUTPUT_NAME,
                "sha256": sha256_file(out_path),
                "bytes": out_path.stat().st_size,
            }
        ],
        inputs=[
            municipalities_manifest["gcs_prefix"] + MANIFEST_NAME,
            population_manifest["gcs_prefix"] + MANIFEST_NAME,
        ],
        notes=(
            f"non_amazon={len(rows)}; population_rows={len(population)}; "
            f"legal_amazon_without_population={amazon_missing}; by state: "
            + ", ".join(f"{uf}={n}" for uf, n in sorted(by_uf.items()))
        ),
        code_commit=code_commit,
        created_at=created_at,
    )
