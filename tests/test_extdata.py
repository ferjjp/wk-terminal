import json

import pytest

from wanikani_tui import extdata

KANJI = {
    "村": {"readings": ["そん"], "semantic": "⽊", "phonetic": "寸", "type": "comp_phonetic", "category": "jouyou"},
    "情": {"readings": ["じょう", "せい"], "semantic": "心", "phonetic": "青", "type": "comp_phonetic"},
    "水": {"readings": ["すい"], "type": "hieroglyph"},
    "青": {"readings": ["せい", "しょう"], "semantic": "月", "phonetic": "生", "type": "comp_phonetic"},
}
PHON = {
    "寸": {"readings": ["すん", "そん"], "compounds": ["村"], "non_compounds": ["討", "耐"], "wk-radical": "measurement"},
    "青": {"readings": ["せい", "しょう"], "compounds": ["情", "清", "精"], "non_compounds": [], "wk-radical": "blue"},
}
NOTO = {"人": [{"kan": "入", "score": 0.636}, {"kan": "大", "score": 0.341}, {"kan": "太", "score": 0.15}]}
KEI = {"人": ["仁"]}
MANUAL = {"人": ["火"]}


@pytest.fixture(autouse=True)
def fake_datasets(tmp_path, monkeypatch):
    monkeypatch.setattr(extdata, "ext_dir", lambda: tmp_path)
    extdata._read.cache_clear()
    for name, data in {"keisei_kanji": KANJI, "keisei_phonetic": PHON, "niai_noto": NOTO, "niai_keisei": KEI, "niai_manual": MANUAL}.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False))


def test_keisei_compound():
    info = extdata.keisei_info("村", fetch=None)
    assert info["phonetic"] == "寸" and info["semantic"] == "⽊"
    assert info["compounds"] == [] and info["non_compounds"] == ["討", "耐"]
    assert info["quality"] == "天"  # そん is a reading of 寸
    assert info["type_label"].startswith("phonetic-semantic")


def test_keisei_mark_and_quality():
    info = extdata.keisei_info("青", fetch=None)
    assert info["as_mark"]["compounds"] == ["情", "清", "精"]
    j = extdata.keisei_info("情", fetch=None)
    assert j["quality"] == "天"  # じょう ~ しょう once dakuten is ignored, せい matches directly
    assert extdata.keisei_quality(["せい", "なさけ"], ["せい"]) == "上"
    assert extdata.keisei_quality(["a", "b", "c"], ["a"]) == "中"
    assert extdata.keisei_quality(["か"], ["き"]) == "下"
    assert extdata.keisei_quality(["がい"], ["かい"]) == "天"  # dakuten counts as a match


def test_keisei_non_compound_kanji():
    info = extdata.keisei_info("水", fetch=None)
    assert info["type"] == "hieroglyph" and "phonetic" not in info
    assert extdata.keisei_info("龍", fetch=None) is None


def test_niai_merge_and_cutoff():
    sims = extdata.niai_similar("人", fetch=None)
    assert sims[0] == ("火", 0.9)                         # manual source, base 0.9
    assert ("入", pytest.approx(0.736)) in sims            # noto 0.636 + 0.1
    assert ("仁", 0.65) in sims                            # keisei list, base 0.65
    assert all(ch != "太" for ch, _ in sims)               # 0.25 < cutoff 0.3


def test_missing_dataset_offline(tmp_path):
    (tmp_path / "niai_noto.json").unlink()
    (tmp_path / "niai_keisei.json").unlink()
    (tmp_path / "niai_manual.json").unlink()
    assert extdata.niai_similar("人", fetch=None) is None   # no data at all, no fetcher
    calls = []

    def bad_fetch(url):
        calls.append(url)
        return b"<html>not json</html>"

    assert extdata.niai_similar("人", fetch=bad_fetch) is None
    assert calls and not (tmp_path / "niai_noto.json").exists()  # invalid payload is not cached
