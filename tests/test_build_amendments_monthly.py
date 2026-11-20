"""The monthly amendments table on the amendments panel's synthetic world (cycle A).

The world, its payments and its staging come from `test_build_amendments_panel`. The monthly
rows must be the panel's rows, and the months of a window must add up to the panel's sums.
"""

import io
import json
from pathlib import Path

import polars as pl
import pytest
import test_build_amendments_panel as world

from terrain.builds import amendments_monthly as am
from terrain.builds import amendments_panel as ap
from terrain.builds.amendments_monthly import BuildError, build
from terrain.manifest import write_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/amendments_monthly/"
SEALED = "sealed/outcomes/amendments_monthly/"
R1, R2, R3, C1, C2 = world.R1, world.R2, world.R3, world.C1, world.C2
MONTHS_A = 46  # 2015-01 to 2018-10


def monthly_manifests(manifests):
    """The six inputs of the monthly build, out of the panel's eight."""
    general, cgu, results, candidates, municipalities, _, chamber, _ = manifests
    return general, cgu, results, candidates, municipalities, chamber


def run(store, manifests, tmp_path, **kwargs):
    options = {"cycles": ("A",), "min_rows": 1, "max_rows": 100}
    options.update(kwargs)
    tmp = tmp_path / "monthly"
    tmp.mkdir(parents=True, exist_ok=True)
    return build(
        store,
        *monthly_manifests(manifests),
        derived_root=DERIVED,
        sealed_root=SEALED,
        tmp_dir=tmp,
        code_commit="abc",
        created_at="2026-11-20T00:00:00+00:00",
        **options,
    )


def read(store, path):
    return pl.read_parquet(io.BytesIO(store.read_bytes(path)))


def both_halves(store, manifest):
    paths = [f["path"] for f in manifest["files"] + manifest["sealed_files"]]
    return pl.concat([read(store, p) for p in paths])


@pytest.fixture
def built(tmp_path):
    store = MemoryStore()
    manifests = world.stage(store)
    panel_manifest = world.run(store, manifests, tmp_path)
    before = set(store.list(""))
    manifest = run(store, manifests, tmp_path)
    return store, manifest, world.whole_panel(store, panel_manifest), before


def months_of(table, deputy, cd_ibge):
    return table.filter((pl.col("deputy") == deputy) & (pl.col("cd_ibge") == cd_ibge))


# --- 1. The rows


def test_the_months_of_a_cycle():
    assert am.month_range(ap.CYCLES["A"]) == (201501, 201810)
    assert am.month_range(ap.CYCLES["C"]) == (202301, 202610)
    months = am.months(ap.CYCLES["A"])
    assert len(months) == MONTHS_A and months[0] == 201501 and months[-1] == 201810
    assert 201513 not in months and 201601 in months


def test_rows_are_the_panels_rows_in_every_month(built):
    store, manifest, panel, _ = built
    table = both_halves(store, manifest)
    assert table.schema == pl.Schema(am.SCHEMA)
    keys = sorted(set(zip(table["deputy"], table["cd_ibge"], strict=True)))
    assert keys == sorted(zip(panel["deputy"], panel["cd_ibge"], strict=True))
    assert table.height == len(keys) * MONTHS_A
    assert set(table["cycle"]) == {"A"}


def test_payments_by_month(built):
    store, manifest, _, _ = built
    table = both_halves(store, manifest)
    joao = months_of(table, "1001", R1)
    by_month = dict(zip(joao["ym"], joao["amend_total"], strict=True))
    assert by_month[201502] == pytest.approx(1000.5)  # an older amendment of a current author
    assert by_month[201609] == 2000.0
    assert by_month[201610] == 7000.0  # between the windows: in the monthly table
    assert by_month[201705] == 500.0 and joao.filter(pl.col("ym") == 201705)["amend_pix"][0] == 500
    assert by_month[201810] == 9999.0  # October of t1 is the last month
    assert by_month[201501] == 0.0 and joao.filter(pl.col("ym") == 201501)["n_pay"][0] == 0
    assert months_of(table, "1003", R1)["amend_total"].sum() == pytest.approx(1234.56)


def test_window_months_add_up_to_the_panel(built):
    store, manifest, panel, _ = built
    table = both_halves(store, manifest)
    cycle = ap.CYCLES["A"]
    for label, window in (("pre", cycle.pre), ("post", cycle.post)):
        sums = (
            table.filter(pl.col("ym").is_between(*window))
            .group_by("deputy", "cd_ibge")
            .agg(pl.col("amend_total").sum(), pl.col("amend_pix").sum(), pl.col("n_pay").sum())
        )
        joined = panel.join(sums, on=["deputy", "cd_ibge"], how="left")
        assert joined[f"amend_{label}_total"].to_list() == pytest.approx(
            joined["amend_total"].to_list()
        )
        assert joined[f"amend_{label}_pix"].to_list() == pytest.approx(
            joined["amend_pix"].to_list()
        )
        assert joined[f"n_pay_{label}"].to_list() == joined["n_pay"].to_list()


def test_a_month_netting_below_zero_becomes_zero(tmp_path):
    store = MemoryStore()
    manifests = world.stage(store, cgu=world.cgu_zip(world.with_negatives()))
    manifest = run(store, manifests, tmp_path)
    table = both_halves(store, manifest)
    cabixi = months_of(table, "1001", R3)
    assert cabixi.filter(pl.col("ym") == 201801)["amend_total"][0] == 0.0
    assert cabixi.filter(pl.col("ym") == 201801)["n_pay"][0] == 1
    assert cabixi.filter(pl.col("ym") == 201706)["amend_total"][0] == 100.0
    notes = manifest["notes"].split("; ")
    # 2016-03 (the reversal of 50 alone in its month) and 2018-01: a month, not a window
    assert "A_floored_to_zero=amend_total:2,amend_pix:0" in notes


# --- 2. Notes, identifiers, the split and the path


def test_manifest_notes(built):
    _, manifest, _, _ = built
    notes = manifest["notes"].split("; ")
    note = next(n for n in notes if n.startswith("A: "))
    assert note.startswith(f"A: rows={4 * MONTHS_A}, panel_rows=4, months={MONTHS_A}")
    assert "(2015-01..2018-10), deputy_authors=4, money_share=" in note
    assert "first_payment_month=2015-01, last=2026-09" in notes


def test_no_identifier_in_any_output(built):
    store, manifest, _, before = built
    forbidden = [*world.NAMES, *[s.lower() for s in world.SENTINEL_FAVORECIDO]]
    for f in manifest["files"] + manifest["sealed_files"]:
        frame = read(store, f["path"])
        assert not any(w in c.lower() for c in frame.columns for w in ("cpf", "nome", "name"))
        for column, dtype in frame.schema.items():
            if dtype == pl.Utf8:
                for value in frame[column].unique().to_list():
                    assert not any(w in value.lower() for w in forbidden)
                    assert value not in world.CODES
    text = json.dumps(manifest).lower()
    assert not any(w in text for w in forbidden)
    assert world.CPF1 not in text
    new = set(store.list("")) - before
    assert {p for p in new if not p.startswith((DERIVED, SEALED))} == set()


def test_exploration_half_in_derived_and_the_rest_only_in_sealed(built):
    store, manifest, _, _ = built
    (derived,) = [f["path"] for f in manifest["files"]]
    (sealed,) = [f["path"] for f in manifest["sealed_files"]]
    assert derived.startswith(DERIVED) and sealed.startswith(SEALED)
    assert derived.endswith("/monthly_A.parquet") and sealed.endswith("/monthly_A.parquet")
    assert set(read(store, derived)["cd_ibge"]) == {R1, C1}
    assert set(read(store, sealed)["cd_ibge"]) == {R2, R3, C2}


def test_a_second_run_is_unchanged(built, tmp_path):
    store, manifest, _, _ = built
    write_manifest(manifest, store, tmp_path / "manifest.json")
    again = run(store, world.stage_manifests(store), tmp_path)
    assert again["status"] == "unchanged"


def test_a_code_change_in_any_module_changes_the_path():
    files = [{"sha256": "a" * 64}]
    base = am.input_hash(files, ["s1", "s2"], ("A",))
    sources = am.code_sources()
    assert len(sources) == len(am.CODE_MODULES)
    for i in range(len(sources)):
        changed = list(sources)
        changed[i] += "\n# changed"
        assert am.input_hash(files, ["s1", "s2"], ("A",), code=changed) != base
    assert am.input_hash(files, ["s1", "s2"], ("A", "B")) != base


def test_code_modules_list_this_file_and_every_data_module_it_imports():
    from terrain import explore, parties
    from terrain.builds import cell_outcomes, place_outcomes, polling_place_tenure

    expected = {am.__file__, ap.__file__, parties.__file__, explore.__file__}
    expected |= {place_outcomes.__file__, cell_outcomes.__file__, polling_place_tenure.__file__}
    assert set(am.CODE_MODULES) == {Path(p) for p in expected}


# --- 3. The stop rules


def tables(built):
    store, manifest, _, _ = built
    return {"A": both_halves(store, manifest)}


def test_check_tables_passes_on_the_world(built):
    am.check_tables(tables(built), {"A": 10}, min_rows=1, max_rows=100)


def test_stop_on_a_duplicate_or_a_missing_month(built):
    t = tables(built)
    with pytest.raises(BuildError, match="appears twice"):
        am.check_tables({"A": pl.concat([t["A"], t["A"].head(1)])}, {"A": 10}, min_rows=1)
    with pytest.raises(BuildError, match="rows, not 460"):
        am.check_tables({"A": t["A"].slice(1)}, {"A": 10}, min_rows=1)


def test_stop_on_negative_money_or_more_pix_than_total(built):
    t = tables(built)
    negative = t["A"].with_columns(pl.lit(-1.0).alias("amend_total"))
    with pytest.raises(BuildError, match="amend_total below 0"):
        am.check_tables({"A": negative}, {"A": 10}, min_rows=1)
    more = t["A"].with_columns(pl.lit(5.0).alias("amend_pix"))
    with pytest.raises(BuildError, match="more Pix"):
        am.check_tables({"A": more}, {"A": 10}, min_rows=1)


def test_stop_on_panel_row_bounds(built, tmp_path):
    with pytest.raises(BuildError, match="10 panel rows, outside 11-100"):
        am.check_tables(tables(built), {"A": 10}, min_rows=11, max_rows=100)


def test_a_wrong_sha_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = world.stage(store)
    manifests[1]["files"][0]["sha256"] = "0" * 64
    with pytest.raises(BuildError, match="does not match"):
        run(store, manifests, tmp_path)
