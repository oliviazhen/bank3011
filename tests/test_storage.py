import sqlite3

from engine.session import TopicState, update_topic
from engine.storage import Progress


def test_topic_state_and_sessions_round_trip(tmp_path):
    p = Progress(tmp_path / "p.db")
    sid = p.start_session("week:7")
    ts = p.record_attempt("ltv", "ltv_q2", "mcq", False, 0.1, 0.05, difficulty=2, session_id=sid, round_no=2)
    p.save_topic_state("ltv", update_topic(TopicState(), 2, False, ts, qtype="cloze"))
    p.finish_session(sid, {"score": [0, 1]})

    p2 = Progress(tmp_path / "p.db")                          # reopen: weak topics persist
    s = p2.topic_states()["ltv"]
    assert s.weak and s.level == 2 and s.fail_streak == 1 and s.missed_type == "cloze"
    [a] = p2.session_answers(sid)
    assert (a.question_id, a.topic, a.difficulty, a.round, a.correct) == ("ltv_q2", "ltv", 2, 2, False)
    assert p2.question_history() == {"ltv_q2": ts}
    assert p2.last_session()["scope"] == "week:7"


def test_old_progress_file_is_migrated(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, concept_id TEXT "
                "NOT NULL, question_id TEXT NOT NULL, qtype TEXT NOT NULL, correct INTEGER NOT NULL, p_before REAL, "
                "p_after REAL, detail TEXT)")
    con.execute("INSERT INTO attempts (ts, concept_id, question_id, qtype, correct) VALUES ('t','ltv','q','mcq',1)")
    con.commit(); con.close()
    p = Progress(db)                                           # must not crash; old rows kept
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(attempts)")}
    assert {"difficulty", "session_id", "round"} <= cols
    assert p.question_history() == {"q": "t"}


def test_topic_state_from_v3_is_migrated(tmp_path):
    db = tmp_path / "v3.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE topic_state (concept_id TEXT PRIMARY KEY, weak INTEGER NOT NULL DEFAULT 0, level INTEGER "
                "NOT NULL DEFAULT 1, fail_streak INTEGER NOT NULL DEFAULT 0, correct_streak INTEGER NOT NULL DEFAULT 0, "
                "last_seen TEXT)")
    con.execute("INSERT INTO topic_state VALUES ('ltv', 1, 2, 1, 0, 't')")
    con.commit(); con.close()
    s = Progress(db).topic_states()["ltv"]
    assert s.weak and s.level == 2 and s.missed_type is None
