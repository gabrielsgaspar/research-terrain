import json
import re
from pathlib import Path

import polars as pl
import pytest

from terrain.explore import (
    EXPLORE_LIST,
    EXPLORE_LIST_NON_AMAZON,
    NATIONAL_IDEAS,
    ExploreError,
    exploration_municipalities,
    idea_of,
    output_prefix,
    restrict,
    write_results,
)
from terrain.storage import MemoryStore

REPO = Path(__file__).resolve().parents[1]


def store_with(text: str) -> MemoryStore:
    store = MemoryStore()
    store.create(EXPLORE_LIST, text.encode("utf-8"))
    return store


def test_exploration_list_is_read_and_checked():
    codes = exploration_municipalities(store_with("code_ibge\n1500107\n1500131\n"))
    assert codes == {"1500107", "1500131"}
    for bad in ("code_ibge\n", "code,uf\n1500107,PA\n", "code_ibge\n150\n"):
        with pytest.raises(ExploreError):
            exploration_municipalities(store_with(bad))


def test_a_missing_list_stops_the_run():
    with pytest.raises(ExploreError, match="sealed"):
        exploration_municipalities(MemoryStore())


def test_national_list_is_the_union_of_both_lists():
    store = store_with("code_ibge\n1500107\n1500131\n")
    store.create(EXPLORE_LIST_NON_AMAZON, b"code_ibge\n3550308\n")
    assert exploration_municipalities(store) == {"1500107", "1500131"}
    assert exploration_municipalities(store, national=True) == {"1500107", "1500131", "3550308"}


def test_national_list_needs_both_lists_and_no_overlap():
    with pytest.raises(ExploreError, match="explore_municipalities_non_amazon"):
        exploration_municipalities(store_with("code_ibge\n1500107\n"), national=True)
    store = store_with("code_ibge\n1500107\n")
    store.create(EXPLORE_LIST_NON_AMAZON, b"code_ibge\n1500107\n3550308\n")
    with pytest.raises(ExploreError, match="in both"):
        exploration_municipalities(store, national=True)
    store = store_with("code_ibge\n1500107\n")
    store.create(EXPLORE_LIST_NON_AMAZON, b"code\n3550308\n")
    with pytest.raises(ExploreError, match="exactly one column"):
        exploration_municipalities(store, national=True)


def test_restrict_keeps_only_the_exploration_half():
    df = pl.DataFrame({"cd_ibge": ["1500107", "1500131", "1500206"], "x": [1, 2, 3]})
    kept = restrict(df, frozenset({"1500107", "1500206"}))
    assert kept["cd_ibge"].to_list() == ["1500107", "1500206"]
    with pytest.raises(ExploreError):
        restrict(df.rename({"cd_ibge": "code"}), frozenset({"1500107"}))


def test_names_and_prefixes():
    assert idea_of("0001_feasibility_census") == "0001"
    prefix = output_prefix("0001_feasibility_census", "123")
    assert prefix == "data/explore/0001/0001_feasibility_census/123/"
    for bad in ("feasibility", "1_census", "0001-census", "0001_Census"):
        with pytest.raises(ExploreError):
            idea_of(bad)
    with pytest.raises(ExploreError):
        output_prefix("0001_feasibility_census", "../x")


def test_write_results_enforces_limits(tmp_path):
    write_results(tmp_path, "# Result\nfine", {"n": 1})
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["n"] == 1
    with pytest.raises(ExploreError):
        write_results(tmp_path, "x" * 20_001, {})
    with pytest.raises(ExploreError):
        write_results(tmp_path, "ok", {"big": "y" * 200_001})


def _chunk(kind: bytes, body: bytes) -> bytes:
    import struct
    import zlib

    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _png(size: int | None = None, extra: bytes = b"") -> bytes:
    """A valid 1x1 PNG; `size` pads it to that many bytes with a text chunk."""
    import struct
    import zlib

    head = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    tail = _chunk(b"IDAT", zlib.compress(b"\x00\x00")) + _chunk(b"IEND", b"")
    if size is not None:
        extra += _chunk(b"tEXt", b"x" * (size - len(head) - len(tail) - len(extra) - 12))
    return head + extra + tail


def test_figures_keep_the_count_size_and_png_limits(tmp_path):
    from terrain.explore_figures import FIGURE_MAX_BYTES, check_figures, stage_figures

    assert check_figures(tmp_path) == []
    folder = tmp_path / "figures"
    folder.mkdir()
    (folder / "b.png").write_bytes(_png())
    (folder / "a.png").write_bytes(_png(FIGURE_MAX_BYTES))
    assert check_figures(tmp_path) == ["a.png", "b.png"]
    (folder / "a.png").write_bytes(_png(FIGURE_MAX_BYTES + 1))
    with pytest.raises(ExploreError, match="over 400 KB"):
        check_figures(tmp_path)
    (folder / "a.png").unlink()
    (folder / "notes.txt").write_bytes(b"no")
    with pytest.raises(ExploreError, match="not a PNG file name"):
        check_figures(tmp_path)
    (folder / "notes.txt").unlink()
    (folder / "c.png").write_bytes(b"not a png")
    with pytest.raises(ExploreError, match="is not a PNG"):
        check_figures(tmp_path)
    (folder / "c.png").unlink()
    (folder / "more").mkdir()
    with pytest.raises(ExploreError, match="only PNG"):
        check_figures(tmp_path)
    (folder / "more").rmdir()
    for i in range(8):
        (folder / f"f{i}.png").write_bytes(_png())
    with pytest.raises(ExploreError, match="at most 8"):
        check_figures(tmp_path)

    record = tmp_path / "record"
    record.mkdir()
    (record / "99.md").write_text("# run\n", encoding="utf-8")
    out = tmp_path / "out"
    (out / "figures").mkdir(parents=True)
    (out / "figures" / "money.png").write_bytes(_png())
    assert stage_figures(out, record, "99") == ["money.png"]
    text = (record / "99.md").read_text(encoding="utf-8")
    assert "[money.png](99/figures/money.png)" in text
    assert (record / "99" / "figures" / "money.png").read_bytes().startswith(b"\x89PNG")
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "1.md").write_text("x\n", encoding="utf-8")
    assert stage_figures(tmp_path / "none", bare, "1") == []
    assert (bare / "1.md").read_text(encoding="utf-8") == "x\n"


def test_a_figure_keeps_only_its_picture(tmp_path):
    """Text, unknown chunks and bytes after IEND never reach Git."""
    import struct

    from terrain.explore_figures import clean_png, stage_figures

    plain = _png()
    assert clean_png(plain) == plain
    phys = _chunk(b"pHYs", struct.pack(">IIB", 11811, 11811, 1))
    tagged = _png(extra=phys + _chunk(b"tEXt", b"Software\x00matplotlib"))
    assert clean_png(tagged) == _png(extra=phys)
    assert b"matplotlib" not in clean_png(_png(extra=_chunk(b"zTXt", b"k\x00\x00x")))
    assert b"hidden" not in clean_png(_png(extra=_chunk(b"prVt", b"hidden")))
    for bad, words in (
        (plain + b"hidden", "bytes after its end"),
        (_png(extra=_chunk(b"XXXX", b"hidden")), "may not hold"),
        (_png(extra=_chunk(b"pHYs", b"hidden")), "wrong size"),
        (plain[:-4] + b"\x00\x00\x00\x00", "checksum"),
        (plain[:15], "ends inside a chunk"),
        (plain[:30], "malformed"),
        (b"\x89PNG\r\n\x1a\n" + _chunk(b"IEND", b""), "start with IHDR"),
        (b"not a png", "is not a PNG"),
    ):
        with pytest.raises(ExploreError, match=words):
            clean_png(bad)

    out = tmp_path / "out"
    (out / "figures").mkdir(parents=True)
    (out / "figures" / "a.png").write_bytes(tagged)
    record = tmp_path / "record"
    record.mkdir()
    (record / "7.md").write_text("# run\n", encoding="utf-8")
    assert stage_figures(out, record, "7") == ["a.png"]
    assert (record / "7" / "figures" / "a.png").read_bytes() == _png(extra=phys)


def test_the_figure_checker_is_owned():
    owners = (REPO / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    assert "/src/terrain/explore_figures.py @gabrielsgaspar" in owners.splitlines()


def test_explore_run_workflow_commits_figures_and_keeps_its_permissions():
    text = (REPO / ".github" / "workflows" / "explore-run.yml").read_text(encoding="utf-8")
    record = text.split("  record:", 1)[1]
    assert "check_figures" in text and "stage_figures" in text
    assert 'git add -- "research/explore-runs/${idea}/${GITHUB_RUN_ID}/figures"' in record
    assert "id-token" not in record
    assert "permission-contents: write" not in record.split("Get a GitHub App token", 1)[0]


def test_every_explore_script_restricts_to_the_exploration_half():
    for script in sorted((REPO / "explore").glob("*.py")):
        source = script.read_text(encoding="utf-8")
        assert re.fullmatch(r"\d{4}_[a-z0-9_]{1,60}\.py", script.name), f"{script.name}: bad name"
        for needed in ("exploration_municipalities(", "restrict("):
            assert needed in source, f"{script.name} must call {needed[:-1]}"


def test_explore_scripts_fit_poisson_only_through_terrain_poisson():
    # pyfixest.fepois can fail on one machine and not another (see terrain/poisson.py)
    direct = re.compile(r"\b(pf|pyfixest)\.fepois\b|from\s+pyfixest[\w.]*\s+import[^\n]*\bfepois\b")
    for script in sorted((REPO / "explore").glob("*.py")):
        source = script.read_text(encoding="utf-8")
        assert not direct.search(source), (
            f"{script.name}: fit Poisson models with terrain.poisson.fepois, not pyfixest.fepois"
        )


def test_national_idea_scripts_read_both_exploration_lists():
    for idea in NATIONAL_IDEAS:
        for script in sorted((REPO / "explore").glob(f"{idea}_*.py")):
            source = script.read_text(encoding="utf-8")
            assert "national=True" in source, (
                f"{script.name}: idea {idea} is national (decision 0011); call "
                "exploration_municipalities(store, national=True)"
            )
