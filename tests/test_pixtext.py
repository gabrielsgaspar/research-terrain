"""Pix work-plan texts: keys, plan municipalities, the sample, the labels and the classifier.

Every text, name and value is made up inside this file.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import polars as pl
import pytest
import yaml
from test_build_amendments_panel import csv_bytes, make_zip

from terrain import pixtext
from terrain.builds.polling_place_tenure import BuildError

REPO = Path(__file__).resolve().parents[1]
CODEBOOK = REPO / "data" / "reference" / "pix_object_codebook.md"
LABELS = REPO / "data" / "reference" / "pix_object_labels.yaml"

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
SENTINEL_CNPJ = "99888777000166"


def plan(code, beneficiary, uf, text, value, status="Aprovado"):
    return [
        code,
        "x",
        "09032024",
        status,
        SENTINEL_CNPJ,
        beneficiary,
        uf,
        "p",
        "CIENTE",
        text,
        value,
    ]


def plan_zip(data):
    body = csv_bytes(PLAN_HEADER, data)
    return make_zip({"EmendasParlamentares_PlanodeTrabalhoTransferenciasEspeciais.csv": body})


# --- Text


def test_norm_text_strips_collapses_upper_cases_and_cuts():
    assert pixtext.norm_text("  pavimentação   de\n ruas ") == "PAVIMENTAÇÃO DE RUAS"
    assert pixtext.norm_text(None) == ""
    long = "a" * 700
    assert pixtext.norm_text(long) == "A" * 600


def test_text_key_is_the_sha256_of_the_normalised_text():
    expected = hashlib.sha256(b"COMPRA DE TRATOR").hexdigest()
    assert pixtext.text_key(" compra  de trator") == expected
    assert pixtext.text_key("Compra de trator") == pixtext.text_key("COMPRA DE TRATOR")


@pytest.mark.parametrize(
    ("beneficiary", "uf", "expected"),
    [
        ("MUNICIPIO DE ALTA FLORESTA D'OESTE", "RO", "ALTA FLORESTA DOESTE"),
        ("MUNICÍPIO DE SÃO JOSÉ DO RIO PRETO", "SP", "SAO JOSE DO RIO PRETO"),
        ("MUNICIPIO DO CONDE", "PB", "CONDE"),
        ("MUNICIPIO DE DOM ELISEU", "PA", "DOM ELISEU"),
        ("Santa Rita", "PB", "SANTA RITA"),
        ("ESTADO DE MINAS GERAIS", "MG", None),
        ("ESTADO DO ACRE", "AC", None),
        ("DISTRITO FEDERAL", "DF", None),
        ("", "RO", None),
    ],
)
def test_plan_municipality(beneficiary, uf, expected):
    assert pixtext.plan_municipality(beneficiary, uf) == expected


def test_read_plans(tmp_path):
    data = [
        plan("202412340001", "MUNICIPIO DE CABIXI", "RO", " compra de trator ", "1.000,50"),
        plan("202112340002", "ESTADO DE RONDONIA", "RO", "x", "10,00"),
        plan(
            "202212340003",
            "MUNICIPIO DE NOWHERE",
            "ro",
            "y",
            "20,00",
            "Legado ADPF 854 STF / NT - TCU",
        ),
    ]
    path = tmp_path / "e.zip"
    path.write_bytes(plan_zip(data))
    plans = pixtext.read_plans(path)
    assert "CNPJ" not in " ".join(plans.columns)
    assert SENTINEL_CNPJ not in str(plans.to_dicts())
    assert plans["year"].to_list() == [2024, 2021, 2022]
    assert plans["legacy"].to_list() == [False, False, True]
    assert plans["value"].to_list() == [1000.5, 10.0, 20.0]
    assert plans["name_key"].to_list() == ["CABIXI", None, "NOWHERE"]
    assert plans["text"][0] == "COMPRA DE TRATOR"
    assert plans["key"][0] == pixtext.text_key("compra de trator")
    munis = pl.DataFrame(
        {"cd_ibge": ["1100031"], "uf": ["RO"], "name_ibge": ["Cabixi"]},
    )
    matched = pixtext.plans_with_municipality(plans, munis)
    assert matched["cd_ibge"].to_list() == ["1100031", None, None]


def test_read_plans_stops_on_a_bad_value_or_code(tmp_path):
    path = tmp_path / "e.zip"
    path.write_bytes(plan_zip([plan("202412340001", "MUNICIPIO DE X", "RO", "t", "abc")]))
    with pytest.raises(BuildError, match="Valor"):
        pixtext.read_plans(path)
    path.write_bytes(plan_zip([plan("2024", "MUNICIPIO DE X", "RO", "t", "1,00")]))
    with pytest.raises(BuildError, match="12 digits"):
        pixtext.read_plans(path)


# --- The sample


def keys_frame(n_per_year):
    rows = [
        (hashlib.sha256(f"{y}-{i}".encode()).hexdigest(), y)
        for y, n in n_per_year.items()
        for i in range(n)
    ]
    return pl.DataFrame(rows, schema={"key": pl.Utf8, "year": pl.Int64}, orient="row")


def test_sample_is_stratified_by_year_and_reproducible():
    keys = keys_frame({2020: 100, 2021: 300, 2022: 600})
    chosen, second = pixtext.sample_keys(keys, 100, 20, seed=7)
    assert len(chosen) == len(set(chosen)) == 100
    assert set(second) <= set(chosen) and len(second) == 20
    years = dict(keys.iter_rows())
    per_year = {y: sum(1 for k in chosen if years[k] == y) for y in (2020, 2021, 2022)}
    assert per_year == {2020: 10, 2021: 30, 2022: 60}
    assert pixtext.sample_keys(keys, 100, 20, seed=7) == (chosen, second)
    assert pixtext.sample_keys(keys, 100, 20, seed=8)[0] != chosen


def test_sample_largest_remainders_add_up():
    keys = keys_frame({2020: 1, 2021: 1, 2022: 1})
    chosen, _ = pixtext.sample_keys(keys, 2, 1)
    assert len(chosen) == 2
    with pytest.raises(ValueError):
        pixtext.sample_keys(keys, 4, 1)


def test_sample_script_writes_keys_and_texts_only(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "pix_label_sample", REPO / "scripts" / "pix_label_sample.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["pix_label_sample"] = module
    spec.loader.exec_module(module)
    module.N_TEXTS, module.N_SECOND = 3, 1
    plans = pl.DataFrame(
        {
            "cd_ibge": ["1", "1", "2", "3", "1"],
            "key": ["a", "b", "c", "d", "a"],
            "text": ["TA", "TB", "TC", "TD", "TA"],
            "year": [2021, 2022, 2022, 2023, 2020],
        }
    )
    keys = module.exploration_keys(plans, frozenset({"1", "2"}))
    assert keys.sort("key").select("key", "year").rows() == [("a", 2020), ("b", 2022), ("c", 2022)]
    chosen, second = module.write_sample(keys, tmp_path)
    lines = (tmp_path / "sample.jsonl").read_text(encoding="utf-8").splitlines()
    assert [set(json.loads(x)) for x in lines] == [{"key", "text"}] * 3
    assert sorted(json.loads(x)["key"] for x in lines) == chosen == ["a", "b", "c"]
    assert (tmp_path / "second_pass.txt").read_text(encoding="utf-8").split() == second
    # the extension draws only keys not yet labelled, with its own seed
    rest = module.unlabelled(keys, {"a"})
    assert sorted(rest["key"]) == ["b", "c"]
    module.N_TEXTS, module.N_SECOND = 2, 1
    again, _ = module.write_sample(rest, tmp_path / "more", module.EXTEND_SEED)
    assert again == ["b", "c"] and module.EXTEND_SEED == pixtext.SEED + 1


# --- Labels


def test_kappas_on_classes_and_groups():
    first = ["OBRA_VIARIA", "OBRA_PREDIAL", "SAUDE", "VAGO"]
    second = ["OBRA_PREDIAL", "OBRA_PREDIAL", "SAUDE", "VAGO"]
    k = pixtext.kappas(first, second)
    assert k["groups"] == pytest.approx(1.0)
    assert k["classes"] < 1.0


def test_groups_cover_every_class():
    assert set(pixtext.GROUPS) == set(pixtext.CLASSES)
    assert set(pixtext.GROUPS.values()) == set(pixtext.GROUP_NAMES)


def test_codebook_names_every_class():
    text = CODEBOOK.read_text(encoding="utf-8")
    for name in pixtext.CLASSES:
        assert f"`{name}`" in text


def write_labels(path, labels, **header):
    doc = {
        "model": "m",
        "date": "2026-11-22",
        "codebook_sha256": "0" * 64,
        "seed": pixtext.SEED,
        **header,
        "labels": labels,
    }
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def test_load_labels_refuses_unknown_classes(tmp_path):
    path = tmp_path / "l.yaml"
    key = "a" * 64
    write_labels(path, {key: {"class": "SAUDE", "specificity": 1}})
    assert pixtext.load_labels(path)["labels"][key]["class"] == "SAUDE"
    write_labels(path, {key: {"class": "OTHER", "specificity": 1}})
    with pytest.raises(BuildError, match="unknown class"):
        pixtext.load_labels(path)
    write_labels(path, {"short": {"class": "SAUDE", "specificity": 1}})
    with pytest.raises(BuildError, match="SHA-256"):
        pixtext.load_labels(path)
    write_labels(path, {key: {"class": "SAUDE", "specificity": 1, "second": "X"}})
    with pytest.raises(BuildError, match="second-pass"):
        pixtext.load_labels(path)


def test_the_committed_label_file_holds_no_text():
    if not LABELS.exists():
        pytest.skip("labels not written yet")
    doc = pixtext.load_labels(LABELS)
    assert doc["codebook_sha256"] == hashlib.sha256(CODEBOOK.read_bytes()).hexdigest()
    for entry in doc["labels"].values():
        assert set(entry) <= {"class", "specificity", "second"}


# --- The classifier


TRAIN = [
    ("PAVIMENTACAO ASFALTICA DE RUAS", "OBRA_VIARIA"),
    ("PAVIMENTACAO DE ESTRADAS VICINAIS", "OBRA_VIARIA"),
    ("RECAPEAMENTO ASFALTICO DE VIAS", "OBRA_VIARIA"),
    ("CALCAMENTO E DRENAGEM DE RUAS", "OBRA_VIARIA"),
    ("CONSTRUCAO DE PONTE E BUEIROS", "OBRA_VIARIA"),
    ("AQUISICAO DE TRATOR AGRICOLA", "MAQUINAS"),
    ("AQUISICAO DE CAMINHAO CACAMBA", "MAQUINAS"),
    ("AQUISICAO DE AMBULANCIA", "MAQUINAS"),
    ("AQUISICAO DE RETROESCAVADEIRA", "MAQUINAS"),
    ("COMPRA DE ONIBUS ESCOLAR", "MAQUINAS"),
    ("CUSTEIO DA ATENCAO BASICA EM SAUDE", "SAUDE"),
    ("AQUISICAO DE MEDICAMENTOS", "SAUDE"),
    ("REALIZACAO DE EXAMES E CONSULTAS", "SAUDE"),
    ("CUSTEIO DOS SERVICOS DE SAUDE", "SAUDE"),
    ("PROCEDIMENTOS E CIRURGIAS ELETIVAS", "SAUDE"),
]


def test_classifier_is_deterministic_and_learns():
    texts, labels = zip(*TRAIN, strict=True)
    new = ["PAVIMENTACAO DE RUAS DO BAIRRO", "AQUISICAO DE TRATOR", "MEDICAMENTOS E EXAMES"]
    first = pixtext.fit_predict(texts, labels, new)
    assert first == ["OBRA_VIARIA", "MAQUINAS", "SAUDE"]
    assert pixtext.fit_predict(texts, labels, new) == first


def test_cross_validation_is_reproducible():
    texts, labels = zip(*TRAIN, strict=True)
    a = pixtext.cross_validate(texts, labels)
    assert a == pixtext.cross_validate(texts, labels)
    assert len(a) == len(labels)
    s = pixtext.scores(labels, a)
    assert 0 <= s["macro_f1"] <= 1 and 0 <= s["accuracy"] <= 1


def test_classifier_settings():
    clf = pixtext.make_classifier()
    chars, words = (t for _, t in clf.named_steps["features"].transformer_list)
    assert chars.analyzer == "char_wb" and chars.ngram_range == (2, 5)
    assert words.analyzer == "word" and words.ngram_range == (1, 2)
    model = clf.named_steps["model"]
    assert model.class_weight == "balanced" and model.random_state == pixtext.SEED
