"""Explain-it questions written in the app: saved, merged into the bank, removable."""
import shutil
from pathlib import Path

import pytest

from engine.content import load_content, load_sources, validate
from engine.my_questions import add_explain_question, list_my_explain, remove_explain_question

ROOT = Path(__file__).resolve().parents[1]
SOURCES = load_sources(ROOT / "assets" / "sources")


@pytest.fixture
def content_dir(tmp_path):
    d = tmp_path / "content"
    d.mkdir()
    for f in (ROOT / "content").glob("*.json"):
        shutil.copy(f, d / f.name)
    return d


def test_explain_question_joins_an_existing_topic(content_dir):
    before = load_content(content_dir)
    q, err = add_explain_question(content_dir, before, SOURCES, week=9, new_topic="basel iii liquidity standards (LCR and NSFR)",
                                  key_points=["Banks ran short of liquidity in the GFC", "HQLA covers 30 days of stress"],
                                  model_answer="Because…")
    assert err == [] and q["id"] == "my_x9_1" and q["type"] == "explain"
    assert q["prompt"] == "Explain basel iii liquidity standards (LCR and NSFR)."
    after = load_content(content_dir)
    mine = [x for x in after["basel_liquidity"]["questions"] if x["id"] == "my_x9_1"]
    assert mine and mine[0]["_set"] == "My questions"
    assert validate(after, SOURCES) == []


def test_new_topic_typed_twice_is_one_topic(content_dir):
    concepts = load_content(content_dir)
    kp = ["Point one", "Point two"]
    q1, _ = add_explain_question(content_dir, concepts, SOURCES, week=10, new_topic="Deposit insurance",
                                 key_points=kp, model_answer="Ideal.")
    _, err = add_explain_question(content_dir, concepts, SOURCES, week=10, new_topic="deposit insurance",
                                  key_points=kp, model_answer="Another ideal answer.")
    assert err == [] and q1["prompt"] == "Explain deposit insurance."
    after = load_content(content_dir)
    assert after["deposit_insurance"]["week"] == 10 and len(after["deposit_insurance"]["questions"]) == 2
    assert len(list_my_explain(content_dir)) == 2


def test_problems_are_reported_and_nothing_saved(content_dir):
    concepts = load_content(content_dir)
    q, err = add_explain_question(content_dir, concepts, SOURCES, week=9, new_topic="  ",
                                  key_points=["", " "], model_answer="")
    assert q is None and len(err) == 3        # ideal answer, marking points, topic
    assert list_my_explain(content_dir) == []


def test_remove(content_dir):
    concepts = load_content(content_dir)
    q, _ = add_explain_question(content_dir, concepts, SOURCES, week=9, topic_id="bank_runs",
                                key_points=["a"], model_answer="ideal")
    remove_explain_question(content_dir, 9, q["id"])
    assert list_my_explain(content_dir) == []
    assert not (content_dir / "uploads" / "my_explain_week09.json").exists()


def test_question_wording_keeps_acronyms():
    from engine.my_questions import question_for
    assert question_for("Cell respiration") == "Explain cell respiration."
    assert question_for("LCR") == "Explain LCR."
