"""Progress storage in a single SQLite file (progress.db).

Tables
  mastery   - one row per concept: BKT probability + counts
  attempts  - every answer: question, topic, difficulty, session, round, correct, timestamp
  topic_state - per-topic weak flag / level / streaks, kept between sessions
  sessions  - each quiz session: scope, start/finish, summary
  cards     - SM-2 state for each flashcard
  explains  - explain-mode answers and Claude's grading
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from .bkt import BKTParams
from .session import Answer, TopicState
from .sm2 import CardState

SCHEMA = """
CREATE TABLE IF NOT EXISTS mastery (
    concept_id TEXT PRIMARY KEY,
    p          REAL NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    correct    INTEGER NOT NULL DEFAULT 0,
    updated    TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    concept_id  TEXT NOT NULL,
    question_id TEXT NOT NULL,
    qtype       TEXT NOT NULL,
    correct     INTEGER NOT NULL,
    p_before    REAL,
    p_after     REAL,
    detail      TEXT
);
CREATE TABLE IF NOT EXISTS cards (
    card_id    TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    ease       REAL NOT NULL,
    interval   INTEGER NOT NULL,
    reps       INTEGER NOT NULL,
    due        TEXT NOT NULL,
    last_seen  TEXT
);
CREATE TABLE IF NOT EXISTS topic_state (
    concept_id     TEXT PRIMARY KEY,
    weak           INTEGER NOT NULL DEFAULT 0,
    level          INTEGER NOT NULL DEFAULT 1,
    fail_streak    INTEGER NOT NULL DEFAULT 0,
    correct_streak INTEGER NOT NULL DEFAULT 0,
    last_seen      TEXT,
    missed_type    TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started   TEXT NOT NULL,
    finished  TEXT,
    scope     TEXT NOT NULL,
    summary   TEXT
);
CREATE TABLE IF NOT EXISTS explains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    concept_id  TEXT NOT NULL,
    question_id TEXT NOT NULL,
    answer      TEXT NOT NULL,
    score       INTEGER,
    feedback    TEXT
);
"""


class Progress:
    def __init__(self, path: str | Path = "progress.db"):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)
            # migrate progress files from earlier versions: add the session columns to attempts
            cols = {r["name"] for r in c.execute("PRAGMA table_info(attempts)")}
            for col, typ in (("difficulty", "INTEGER"), ("session_id", "INTEGER"), ("round", "INTEGER")):
                if col not in cols:
                    c.execute(f"ALTER TABLE attempts ADD COLUMN {col} {typ}")
            if "missed_type" not in {r["name"] for r in c.execute("PRAGMA table_info(topic_state)")}:
                c.execute("ALTER TABLE topic_state ADD COLUMN missed_type TEXT")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------ mastery
    def mastery(self) -> dict[str, float]:
        with self._conn() as c:
            return {r["concept_id"]: r["p"] for r in c.execute("SELECT concept_id, p FROM mastery")}

    def mastery_rows(self) -> dict[str, sqlite3.Row]:
        with self._conn() as c:
            return {r["concept_id"]: r for r in c.execute("SELECT * FROM mastery")}

    def record_attempt(self, concept_id: str, question_id: str, qtype: str,
                       correct: bool, p_before: float, p_after: float,
                       detail: dict | None = None, *, difficulty: int | None = None,
                       session_id: int | None = None, round_no: int | None = None) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute(
                "INSERT INTO attempts (ts, concept_id, question_id, qtype, correct, p_before, p_after, detail, "
                "difficulty, session_id, round) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now, concept_id, question_id, qtype, int(correct), p_before, p_after,
                 json.dumps(detail or {}), difficulty, session_id, round_no))
            c.execute(
                "INSERT INTO mastery (concept_id, p, attempts, correct, updated) VALUES (?,?,1,?,?) "
                "ON CONFLICT(concept_id) DO UPDATE SET p=excluded.p, attempts=attempts+1, "
                "correct=correct+excluded.correct, updated=excluded.updated",
                (concept_id, p_after, int(correct), now))
        return now

    def recent_question_ids(self, n: int = 10) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT question_id FROM attempts ORDER BY id DESC LIMIT ?", (n,))
            return [r["question_id"] for r in rows][::-1]

    def attempts(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._conn() as c:
            return list(c.execute("SELECT * FROM attempts ORDER BY id DESC LIMIT ?", (limit,)))

    # -------------------------------------------------------------- cards
    def card_state(self, card_id: str) -> CardState:
        with self._conn() as c:
            r = c.execute("SELECT * FROM cards WHERE card_id=?", (card_id,)).fetchone()
        if not r:
            return CardState()
        return CardState(ease=r["ease"], interval=r["interval"], reps=r["reps"],
                         due=date.fromisoformat(r["due"]))

    def save_card(self, card_id: str, concept_id: str, state: CardState) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO cards (card_id, concept_id, ease, interval, reps, due, last_seen) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(card_id) DO UPDATE SET ease=excluded.ease, "
                "interval=excluded.interval, reps=excluded.reps, due=excluded.due, last_seen=excluded.last_seen",
                (card_id, concept_id, state.ease, state.interval, state.reps,
                 state.due.isoformat(), date.today().isoformat()))

    def all_card_states(self) -> dict[str, CardState]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM cards").fetchall()
        return {r["card_id"]: CardState(r["ease"], r["interval"], r["reps"], date.fromisoformat(r["due"]))
                for r in rows}

    # ----------------------------------------------------------- explains
    def record_explain(self, concept_id: str, question_id: str, answer: str,
                       score: int | None, feedback: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO explains (ts, concept_id, question_id, answer, score, feedback) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), concept_id, question_id,
                 answer, score, json.dumps(feedback)))

    # ------------------------------------------------------ topic state
    def topic_states(self) -> dict[str, TopicState]:
        with self._conn() as c:
            return {r["concept_id"]: TopicState(bool(r["weak"]), r["level"], r["fail_streak"],
                                                r["correct_streak"], r["last_seen"], r["missed_type"])
                    for r in c.execute("SELECT * FROM topic_state")}

    def save_topic_state(self, concept_id: str, s: TopicState) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO topic_state (concept_id, weak, level, fail_streak, correct_streak, last_seen, missed_type) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(concept_id) DO UPDATE SET weak=excluded.weak, "
                "level=excluded.level, fail_streak=excluded.fail_streak, "
                "correct_streak=excluded.correct_streak, last_seen=excluded.last_seen, missed_type=excluded.missed_type",
                (concept_id, int(s.weak), s.level, s.fail_streak, s.correct_streak, s.last_seen, s.missed_type))

    def question_history(self) -> dict[str, str]:
        """question id -> when it was last answered (any session)."""
        with self._conn() as c:
            return {r["question_id"]: r["ts"] for r in
                    c.execute("SELECT question_id, MAX(ts) AS ts FROM attempts GROUP BY question_id")}

    # --------------------------------------------------------- sessions
    def start_session(self, scope: str) -> int:
        with self._conn() as c:
            cur = c.execute("INSERT INTO sessions (started, scope) VALUES (?, ?)",
                            (datetime.now().isoformat(timespec="seconds"), scope))
            return int(cur.lastrowid)

    def finish_session(self, session_id: int, summary: dict) -> None:
        with self._conn() as c:
            c.execute("UPDATE sessions SET finished=?, summary=? WHERE id=?",
                      (datetime.now().isoformat(timespec="seconds"), json.dumps(summary), session_id))

    def session_answers(self, session_id: int) -> list[Answer]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM attempts WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        return [Answer(r["question_id"], r["concept_id"], r["difficulty"] or 1, bool(r["correct"]),
                       r["round"] or 1, r["ts"], r["qtype"]) for r in rows]

    def last_session(self) -> sqlite3.Row | None:
        with self._conn() as c:
            return c.execute("SELECT * FROM sessions WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()

    # ------------------------------------------------------------- admin
    def reset(self) -> None:
        with self._conn() as c:
            c.executescript("DELETE FROM mastery; DELETE FROM attempts; DELETE FROM cards; DELETE FROM explains; "
                            "DELETE FROM topic_state; DELETE FROM sessions;")


def card_id(concept_id: str, index: int) -> str:
    return f"{concept_id}::card{index}"


def default_prior() -> float:
    return BKTParams().prior
