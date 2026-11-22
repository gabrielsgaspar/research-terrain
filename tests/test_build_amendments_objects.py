"""The amendment objects table on the amendments panel's synthetic world (cycle A).

The world, its payments and its staging come from `test_build_amendments_panel`; this file
adds budget functions to `EmendasParlamentares.csv`, a work-plan member and a label file.
The rows must be the panel's rows; the instruments must add up to the panel's window totals
and the Pix classes to the Pix total.
"""

import hashlib
import io

import polars as pl
import pytest
import test_build_amendments_panel as world
import yaml

from terrain import pixtext
from terrain.builds import amendments_objects as ao
from terrain.builds.amendments_objects import BuildError, build
from terrain.manifest import write_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/amendments_objects/"
SEALED = "sealed/outcomes/amendments_objects/"
R1, R2, R3, C1, C2 = world.R1, world.R2, world.R3, world.C1, world.C2
CURRENT, OLDER = world.CURRENT, world.OLDER
NO_PLAN = "201700000002"  # a Pix amendment with no work plan
SENTINEL_CNPJ = "12345678000199"

# Training texts: ten of each class, labelled; the two plans of João's Pix are among them.
ROAD = [f"PAVIMENTACAO ASFALTICA DA RUA {c}" for c in "ABCDEFGHIJ"]
DRUGS = [f"AQUISICAO DE MEDICAMENTOS LOTE {c}" for c in "ABCDEFGHIJ"]
VAGUE = [f"ATENDER AS NECESSIDADES DO MUNICIPIO ITEM {c}" for c in "ABCDEFGHIJ"]
PLAN_HEADER = [
    "Emenda Parlamentar",
    "Autor da Emenda",
    "Programa do Plano de Trabalho",
    "Situação do Plano de Trabalho",
    "CNPJ do Beneficiário",
    "Beneficiário",
    "UF do Beneficiário",
    "Plano de Ação",
    "Situação do Plano de Ação",
    "Detalhamento do Objeto",
    "Valor",
]
LEGACY = "Legado ADPF 854 STF / NT - TCU"
AMENDMENT_HEADER = [
    "Código da Emenda",
    "Ano da Emenda",
    "Tipo de Emenda",
    "Nome Função",
    "Valor Pago",
]


def plan(code, beneficiary, uf, text, value, status="Ciente"):
    return [code, "X", "P", status, SENTINEL_CNPJ, beneficiary, uf, "1", "S", text, value]


def plans():
    alta = "MUNICIPIO DE ALTA FLORESTA D'OESTE"
    rows = [
        plan(CURRENT, alta, "RO", ROAD[0].lower(), "300,00", LEGACY),
        plan(CURRENT, alta, "RO", DRUGS[0], "100,00"),
        plan(CURRENT, "ESTADO DE RONDONIA", "RO", VAGUE[0], "50,00"),  # a state: no municipality
    ]
    for i, text in enumerate(ROAD[1:] + DRUGS[1:] + VAGUE[1:]):
        rows.append(plan(f"20200000{i:04d}", "MUNICIPIO DE ARIQUEMES", "RO", text, "10,00"))
    return rows


def labels_doc(codebook_text, texts=None, **header):
    texts = texts if texts is not None else ROAD + DRUGS + VAGUE
    classes = {**dict.fromkeys(ROAD, ("OBRA_VIARIA", 2)), **dict.fromkeys(DRUGS, ("SAUDE", 1))}
    classes.update(dict.fromkeys(VAGUE, ("VAGO", 0)))
    doc = {
        "model": "test-model",
        "date": "2026-11-22",
        "codebook_sha256": hashlib.sha256(codebook_text.encode("utf-8")).hexdigest(),
        "seed": pixtext.SEED,
        "kappa": {"classes": 0.9, "groups": 0.95},
        "labels": {
            pixtext.text_key(t): {"class": classes[t][0], "specificity": classes[t][1]}
            for t in texts
        },
    }
    doc.update(header)
    return doc


def payments():
    return world.cgu_rows() + [
        world.pay(
            "200", "Maria Oliveira", world.PIX, "2017/08", "RO", "ARIQUEMES", "40,00", NO_PLAN
        )
    ]


def amendments_csv():
    data = [
        (CURRENT, "2016", "x", "Saúde", "900,00"),
        (CURRENT, "2016", "x", "Urbanismo", "100,00"),
        (OLDER, "2015", "x", "Urbanismo", "1,00"),
        (NO_PLAN, "2017", "x", "Encargos especiais", "40,00"),
        ("Sem informação", "2016", "x", "Saúde", "1,00"),
    ]
    return world.csv_bytes(AMENDMENT_HEADER, data, "latin-1")


def cgu_zip(pay_rows=None, plan_rows=None):
    return world.make_zip(
        {
            "EmendasParlamentares.csv": amendments_csv(),
            "EmendasParlamentares_PorFavorecido.csv": world.csv_bytes(
                world.CGU_HEADER, pay_rows if pay_rows is not None else payments(), "utf-8"
            ),
            "EmendasParlamentares_PlanodeTrabalhoTransferenciasEspeciais.csv": world.csv_bytes(
                PLAN_HEADER, plan_rows if plan_rows is not None else plans(), "latin-1"
            ),
        }
    )


def objects_manifests(manifests):
    general, cgu, results, candidates, municipalities, _, chamber, _ = manifests
    return general, cgu, results, candidates, municipalities, chamber


def reference(tmp_path, doc=None, codebook="# codebook\n"):
    folder = tmp_path / "reference"
    folder.mkdir(exist_ok=True)
    codebook_path = folder / "codebook.md"
    codebook_path.write_text(codebook, encoding="utf-8")
    labels_path = folder / "labels.yaml"
    labels_path.write_text(yaml.safe_dump(doc or labels_doc(codebook)), encoding="utf-8")
    return labels_path, codebook_path


def run(store, manifests, tmp_path, **kwargs):
    labels_path, codebook_path = kwargs.pop("paths", None) or reference(tmp_path)
    options = {
        "cycles": ("A",),
        "min_rows": 1,
        "max_rows": 100,
        "min_labels": 10,
        "coverage_from": 2017,
    }
    options.update(kwargs)
    tmp = tmp_path / "objects"
    tmp.mkdir(parents=True, exist_ok=True)
    return build(
        store,
        *objects_manifests(manifests),
        labels_path=labels_path,
        codebook_path=codebook_path,
        derived_root=DERIVED,
        sealed_root=SEALED,
        tmp_dir=tmp,
        code_commit="abc",
        created_at="2026-11-22T00:00:00+00:00",
        **options,
    )


def read(store, path):
    return pl.read_parquet(io.BytesIO(store.read_bytes(path)))


def both_halves(store, manifest):
    paths = [f["path"] for f in manifest["files"] + manifest["sealed_files"]]
    return pl.concat([read(store, p) for p in paths if p.endswith("objects_A.parquet")])


def row(table, deputy, cd_ibge):
    found = table.filter((pl.col("deputy") == deputy) & (pl.col("cd_ibge") == cd_ibge))
    assert found.height == 1
    return found.to_dicts()[0]


@pytest.fixture
def built(tmp_path):
    store = MemoryStore()
    manifests = world.stage(store, cgu=cgu_zip())
    panel_manifest = world.run(store, manifests, tmp_path)
    manifest = run(store, manifests, tmp_path)
    return store, manifest, world.whole_panel(store, panel_manifest), manifests


# --- 1. The rows and the instruments


def test_rows_are_the_panels_rows(built):
    store, manifest, panel, _ = built
    table = both_halves(store, manifest)
    assert table.schema == pl.Schema(ao.SCHEMA)
    assert sorted(zip(table["deputy"], table["cd_ibge"], strict=True)) == sorted(
        zip(panel["deputy"], panel["cd_ibge"], strict=True)
    )
    assert set(table["cycle"]) == {"A"}


def test_instruments_add_up_to_the_panels_totals(built):
    store, manifest, panel, _ = built
    table = both_halves(store, manifest).join(panel, on=["deputy", "cd_ibge"])
    for w in ao.WINDOWS:
        parts = sum(table[f"obj_{w}_{p}"] for p in ao.INSTRUMENTS)
        assert parts.to_list() == pytest.approx(table[f"amend_{w}_total"].to_list())
        assert table[f"obj_{w}_pix"].to_list() == pytest.approx(table[f"amend_{w}_pix"].to_list())


def test_health_is_the_amendments_largest_function(built):
    store, manifest, _, _ = built
    joao = row(both_halves(store, manifest), "1001", R1)
    # pre: 2015-02 (the older amendment, Urbanismo) and 2016-09 (the current one, Saúde)
    assert (joao["obj_pre_health"], joao["obj_pre_tied"]) == (2000.0, pytest.approx(1000.5))
    # post: the Pix payment of 2017-05 and 2018-09 (Saúde)
    assert joao["obj_post_pix"] == 500.0
    assert (joao["obj_post_health"], joao["obj_post_tied"]) == (pytest.approx(300.25), 0.0)


def test_read_functions_picks_the_largest_paid_function(tmp_path):
    path = tmp_path / "cgu.zip"
    path.write_bytes(cgu_zip())
    functions, counts = ao.read_functions(path)
    got = dict(zip(functions["amendment"], functions["health"], strict=True))
    assert got == {CURRENT: True, OLDER: False, NO_PLAN: False}
    assert counts == {"codes": 3, "multi_function": 1}


# --- 2. Pix by work plan


def test_pix_is_split_over_its_plans_by_value(built):
    store, manifest, _, _ = built
    joao = row(both_halves(store, manifest), "1001", R1)
    # plans of 300 (paving, legacy) and 100 (medicines); the state's plan is not R1's
    assert joao["obj_post_pix_obra_viaria"] == pytest.approx(375.0)
    assert joao["obj_post_pix_saude"] == pytest.approx(125.0)
    assert joao["obj_post_pix_no_plan"] == 0.0
    assert joao["obj_post_pix_visible"] == pytest.approx(375.0)
    assert joao["obj_post_pix_services"] == pytest.approx(125.0)
    assert (joao["obj_post_pix_spec2"], joao["obj_post_pix_spec1"]) == pytest.approx((375, 125))
    assert (joao["obj_post_pix_legacy"], joao["obj_post_pix_regular"]) == pytest.approx((375, 125))


def test_pix_with_no_plan_is_fungible(built):
    store, manifest, _, _ = built
    maria = row(both_halves(store, manifest), "1002", R2)
    assert maria["obj_post_pix"] == 40.0 and maria["obj_post_pix_no_plan"] == 40.0
    assert maria["obj_post_pix_fungible"] == 40.0 and maria["obj_post_pix_vago"] == 0.0


def test_every_pix_split_adds_up(built):
    store, manifest, _, _ = built
    table = both_halves(store, manifest)
    for w in ao.WINDOWS:
        for parts in ao.PIX_SPLITS.values():
            total = sum(table[f"obj_{w}_{p}"] for p in parts)
            assert total.to_list() == pytest.approx(table[f"obj_{w}_pix"].to_list())


def test_plan_shares_fall_back_to_counts_when_values_are_zero():
    plans_ = pl.DataFrame(
        {
            "amendment": ["1", "1"],
            "cd_ibge": ["9", "9"],
            "key": ["a", "b"],
            "legacy": [True, False],
            "value": [0.0, 0.0],
        }
    )
    predicted = pl.DataFrame({"key": ["a", "b"], "class": ["VAGO", "MISTO"], "specificity": [0, 1]})
    shares, zero = ao.plan_shares(plans_, predicted)
    assert zero == 1
    got = shares.to_dicts()[0]
    assert got["share_pix_vago"] == 0.5 and got["share_pix_misto"] == 0.5
    assert got["share_pix_legacy"] == 0.5 and got["share_pix_spec0"] == 0.5


# --- 3. The halves, the measurement file and the manifest


def test_halves_and_measurement(built):
    store, manifest, _, _ = built
    derived = [f["path"] for f in manifest["files"]]
    sealed = [f["path"] for f in manifest["sealed_files"]]
    assert all(p.startswith(DERIVED) for p in derived)
    assert all(p.startswith(SEALED) for p in sealed)
    assert sorted(p.rsplit("/", 1)[1] for p in derived) == [ao.MEASUREMENT, "objects_A.parquet"]
    assert [p.rsplit("/", 1)[1] for p in sealed] == ["objects_A.parquet"]
    explore = read(store, next(p for p in derived if p.endswith("objects_A.parquet")))
    assert set(explore["cd_ibge"]) <= {R1, C1}
    closed = read(store, sealed[0])
    assert not set(closed["cd_ibge"]) & {R1, C1}


def test_measurement_file(built):
    store, manifest, _, _ = built
    path = next(f["path"] for f in manifest["files"] if f["path"].endswith(ao.MEASUREMENT))
    meas = read(store, path)
    assert meas.schema == pl.Schema(ao.MEASUREMENT_SCHEMA)
    assert set(meas["measure"]) <= ao.MEASURES
    plain = meas.filter(
        pl.col("class").is_null() & pl.col("year").is_null() & pl.col("cycle").is_null()
    )
    one = dict(plain.select("measure", "value").iter_rows())
    assert one["n_labels"] == 30
    assert one["kappa_groups"] == 0.95 and one["kappa_classes"] == 0.9
    assert 0 <= one["cv_macro_f1_groups"] <= 1 and 0 <= one["cv_accuracy_classes"] <= 1
    with_plan = meas.filter(pl.col("measure") == "pix_value_with_plan")
    assert with_plan["cycle"].to_list() == ["A"] and with_plan["value"][0] == 1.0  # R1 only
    classes = meas.filter((pl.col("measure") == "class_value_share") & pl.col("year").is_null())
    assert sum(classes["value"]) == pytest.approx(1.0)


def test_no_text_cnpj_or_beneficiary_in_any_output_or_note(built):
    store, manifest, _, _ = built
    blobs = [store.read_bytes(f["path"]) for f in manifest["files"] + manifest["sealed_files"]]
    notes = manifest["notes"].upper()
    for needle in ["PAVIMENTACAO", "MEDICAMENTOS", "NECESSIDADES", SENTINEL_CNPJ, "RONDONIA"]:
        assert needle not in notes
        assert all(needle.encode() not in b for b in blobs)


def test_notes(built):
    _, manifest, _, _ = built
    notes = manifest["notes"].split("; ")
    assert any(n.startswith("labels=30, labels_found=30, label_model=test-model, ") for n in notes)
    assert "pix_rows_matched_to_a_plan=2017:1/2" in notes
    assert "amendment_codes=3, codes_with_several_functions=1" in notes
    assert "plan_keys_with_zero_value_split_by_count=0" in notes
    plan_note = "plan_rows=30, plan_rows_with_municipality=29, plan_rows_no_municipality=1, "
    assert plan_note + "plan_texts=30, legacy_plan_rows=1" in notes
    assert any(n.startswith("A: rows=") and "cells_floored_to_zero=0" in n for n in notes)


def test_a_second_run_is_unchanged(built, tmp_path):
    store, manifest, _, manifests = built
    write_manifest(manifest, store, tmp_path / "m.json")
    again = run(store, manifests, tmp_path)
    assert again["status"] == "unchanged" and again["gcs_prefix"] == manifest["gcs_prefix"]


# --- 4. The checks


def test_labels_of_another_codebook_stop_the_build(tmp_path):
    store = MemoryStore()
    manifests = world.stage(store, cgu=cgu_zip())
    doc = labels_doc("another codebook")
    with pytest.raises(BuildError, match="another codebook"):
        run(store, manifests, tmp_path, paths=reference(tmp_path, doc))


def test_too_few_labelled_keys_stop_the_build(tmp_path):
    store = MemoryStore()
    manifests = world.stage(store, cgu=cgu_zip())
    with pytest.raises(BuildError, match="30 labelled keys found among the plan texts"):
        run(store, manifests, tmp_path, min_labels=31)


def test_pix_mostly_without_plan_stops_the_build(tmp_path):
    extra = [
        world.pay(
            "200", "Maria Oliveira", world.PIX, "2017/09", "RO", "ARIQUEMES", "900,00", NO_PLAN
        )
    ]
    store = MemoryStore()
    manifests = world.stage(store, cgu=cgu_zip(pay_rows=payments() + extra))
    with pytest.raises(BuildError, match=r"2017: less than 80% .* \(1 of 3 Pix payment rows"):
        run(store, manifests, tmp_path)
    assert not [p for p in store.list("") if p.startswith((DERIVED, SEALED))]


def test_parts_that_do_not_add_up_stop():
    table = pl.DataFrame(
        {f"obj_{w}_{p}": [1.0] for w in ao.WINDOWS for p in ao.PARTS}
        | {"total_pre": [3.0], "total_post": [5.0]}
    )
    with pytest.raises(BuildError, match="instruments \\(post\\) do not add up"):
        ao.check_sums("A", table)


def test_rows_that_are_not_the_panels_stop():
    keys = pl.DataFrame({"deputy": ["1", "2"], "cd_ibge": ["9", "9"]})
    table = pl.DataFrame({"cycle": ["A"], "deputy": ["1"], "cd_ibge": ["9"]}).with_columns(
        pl.lit(0.0).alias(c) for c in ao.SCHEMA if c.startswith("obj_")
    )
    with pytest.raises(BuildError, match="1 rows, 2 panel rows, 0 not the panel's, 1 missing"):
        ao.check_rows({"A": table}, {"A": keys}, min_rows=1, max_rows=10)
    negative = table.with_columns(pl.lit(-1.0).alias("obj_pre_tied"))
    with pytest.raises(BuildError, match="obj_pre_tied below 0"):
        ao.check_rows({"A": negative}, {"A": keys.head(1)}, min_rows=1, max_rows=10)


def test_a_text_in_a_note_or_cell_is_found():
    table = pl.DataFrame({"cycle": ["A"], "deputy": ["1"], "cd_ibge": ["X Y"]})
    meas = pl.DataFrame(
        {"measure": ["n_labels"], "cycle": [None], "class": ["COMPRA DE TRATOR"]},
        schema={"measure": pl.Utf8, "cycle": pl.Utf8, "class": pl.Utf8},
    )
    texts = ["COMPRA DE TRATOR", "SHORT"]
    assert ao.text_in_outputs({"A": table}, meas, ["x=compra de trator"], texts) == 3
    assert ao.text_in_outputs({}, meas.clear(), ["SHORT"], texts) == 0


def test_the_build_reads_no_cnpj():
    selected = [*pixtext.PLAN_COLUMNS.values(), *ao.FUNCTION_COLUMNS.values()]
    assert not [c for c in selected if "CNPJ" in c]
