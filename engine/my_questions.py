"""Explain-it questions written in the app.

Saved one file per week to content/uploads/my_explain_weekNN.json, in the same shape as an uploaded
set, so load_content merges them in like any other upload (tagged with the set name "My questions").
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .content import UPLOADS_SUBDIR
from .importer import slug

MY_SET = "My questions"
MIN_KEY_POINTS = 1


def my_explain_path(content_dir: str | Path, week: int) -> Path:
    return Path(content_dir) / UPLOADS_SUBDIR / f"my_explain_week{int(week):02d}.json"


def _read(content_dir: str | Path, week: int) -> dict:
    path = my_explain_path(content_dir, week)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"set_name": MY_SET, "week": int(week), "source_file": "written in the app",
            "uploaded": datetime.now().strftime("%Y%m%d-%H%M%S"), "concepts": []}


def _write(content_dir: str | Path, week: int, data: dict) -> None:
    path = my_explain_path(content_dir, week)
    data["concepts"] = [c for c in data["concepts"] if c.get("questions")]
    if not data["concepts"]:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def my_topics(content_dir: str | Path, week: int) -> dict[str, str]:
    """Topics created by your own questions this week (id -> name), even before the app reloads."""
    return {c["id"]: c["name"] for c in _read(content_dir, week)["concepts"] if c.get("name")}


def list_my_explain(content_dir: str | Path) -> list[dict]:
    """Every explain question you've written: [{'week', 'topic', 'question'}]."""
    out = []
    for path in sorted((Path(content_dir) / UPLOADS_SUBDIR).glob("my_explain_week*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out += [{"week": data["week"], "topic": c["id"], "question": q}
                for c in data["concepts"] for q in c.get("questions", [])]
    return out


def question_for(topic: str) -> str:
    """The question shown for a topic: 'Explain cell respiration.' (keeps acronyms such as LCR as typed)."""
    topic = topic.strip().rstrip(".")
    if len(topic) > 1 and topic[0].isupper() and not topic[1].isupper():
        topic = topic[0].lower() + topic[1:]
    return f"Explain {topic}."


def add_explain_question(content_dir: str | Path, concepts: dict[str, dict], sources: dict | None, *,
                         week: int, key_points: list[str], model_answer: str = "", prompt: str | None = None,
                         source: dict | None = None, topic_id: str | None = None,
                         new_topic: str | None = None) -> tuple[dict | None, list[str]]:
    """Check and save one explain question. Returns (question, []) or (None, reasons).

    Without a prompt, the question is "Explain <topic>." The ideal answer (model_answer) is required.
    """
    week = int(week)
    topic_label = new_topic or (concepts.get(topic_id, {}).get("name") if topic_id else "") or ""
    prompt = (prompt or (question_for(topic_label) if topic_label.strip() else "")).strip()
    key_points = [k.strip().lstrip("•-* ").strip() for k in key_points if k and k.strip()]
    errors = []
    if not (model_answer or "").strip():
        errors.append("Write the ideal answer.")
    if len(key_points) < MIN_KEY_POINTS:
        errors.append("Add at least one marking point.")
    if source:
        doc = (sources or {}).get(source.get("doc"))
        if not doc:
            errors.append("That lecture isn't in the app.")
        elif not 1 <= int(source.get("page", 0)) <= int(doc["pages"]):
            errors.append(f"Choose a slide between 1 and {doc['pages']}.")

    data = _read(content_dir, week)
    mine = {c["id"]: c for c in data["concepts"]}
    if not topic_id:
        new_topic = (new_topic or "").strip()
        if not new_topic:
            errors.append("Type a topic.")
        else:   # a "new" name that already exists in this week joins that topic
            same = [cid for cid, c in {**concepts, **mine}.items()
                    if int(c.get("week", week)) == week and slug(new_topic) in (slug(cid), slug(c.get("name", "")))]
            topic_id = same[0] if same else None
    elif topic_id not in concepts and topic_id not in mine:
        errors.append("That topic doesn't exist.")
    if errors:
        return None, errors

    if topic_id is None:                          # create a new topic in this week
        topic_id = base = slug(new_topic)
        if topic_id in concepts:
            topic_id = base = f"{base}_w{week}"
        n = 2
        while topic_id in concepts or topic_id in mine:
            topic_id, n = f"{base}_{n}", n + 1
        mine[topic_id] = {"id": topic_id, "name": new_topic, "week": week,
                          "definition": "A topic you added with your own questions.",
                          "prerequisites": [], "cards": [], "misconceptions": [], "questions": []}
        data["concepts"].append(mine[topic_id])
    elif topic_id not in mine:                    # add to an existing topic
        mine[topic_id] = {"id": topic_id, "questions": []}
        data["concepts"].append(mine[topic_id])

    used = {q["id"] for c in concepts.values() for q in c["questions"]} | \
           {q["id"] for c in data["concepts"] for q in c.get("questions", [])}
    n = 1
    while f"my_x{week}_{n}" in used:
        n += 1
    q = {"id": f"my_x{week}_{n}", "type": "explain", "prompt": prompt, "key_points": key_points}
    if model_answer and model_answer.strip():
        q["model_answer"] = model_answer.strip()
    if source:
        q["sources"] = [{"doc": source["doc"], "page": int(source["page"])}]
    mine[topic_id]["questions"].append(q)
    _write(content_dir, week, data)
    return q, []


def remove_explain_question(content_dir: str | Path, week: int, qid: str) -> None:
    data = _read(content_dir, week)
    for c in data["concepts"]:
        c["questions"] = [q for q in c.get("questions", []) if q["id"] != qid]
    _write(content_dir, week, data)
