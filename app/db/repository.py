"""
WordBuddy SQLite database layer
Word CRUD + Ebbinghaus review + soft-delete + updated_at for timestamp-based sync merge.
"""

import sqlite3
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

from app.constants import EBBINGHAUS_INTERVALS

logger = logging.getLogger(__name__)

NOT_DELETED = "deleted_at = ''"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Word:
    """Word data model"""

    def __init__(self, row: tuple = None, **kwargs):
        if row:
            (
                self.id,
                self.word,
                self.phonetic,
                self.part_of_speech,
                self.definition,
                self.english_definition,
                self.examples_json,
                self.synonyms_json,
                self.notes,
                self.review_stage,
                self.next_review_date,
                self.total_reviews,
                self.correct_reviews,
                self.created_at,
                self.last_reviewed_at,
                self.is_mastered,
                self.updated_at,
                self.deleted_at,
            ) = row
        else:
            self.id = kwargs.get("id")
            self.word = kwargs.get("word", "")
            self.phonetic = kwargs.get("phonetic", "")
            self.part_of_speech = kwargs.get("part_of_speech", "")
            self.definition = kwargs.get("definition", "")
            self.english_definition = kwargs.get("english_definition", "")
            self.examples_json = kwargs.get("examples_json", "[]")
            self.synonyms_json = kwargs.get("synonyms_json", "[]")
            self.notes = kwargs.get("notes", "")
            self.review_stage = kwargs.get("review_stage", 0)
            self.next_review_date = kwargs.get("next_review_date", "")
            self.total_reviews = kwargs.get("total_reviews", 0)
            self.correct_reviews = kwargs.get("correct_reviews", 0)
            self.created_at = kwargs.get("created_at", "")
            self.last_reviewed_at = kwargs.get("last_reviewed_at", "")
            self.is_mastered = kwargs.get("is_mastered", 0)
            self.updated_at = kwargs.get("updated_at", "")
            self.deleted_at = kwargs.get("deleted_at", "")

    @property
    def examples(self) -> List[str]:
        try:
            return json.loads(self.examples_json or "[]")
        except Exception:
            return []

    @property
    def synonyms(self) -> List[str]:
        try:
            return json.loads(self.synonyms_json or "[]")
        except Exception:
            return []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "word": self.word,
            "phonetic": self.phonetic,
            "part_of_speech": self.part_of_speech,
            "definition": self.definition,
            "english_definition": self.english_definition,
            "examples": self.examples,
            "synonyms": self.synonyms,
            "notes": self.notes,
            "review_stage": self.review_stage,
            "next_review_date": self.next_review_date,
            "total_reviews": self.total_reviews,
            "correct_reviews": self.correct_reviews,
            "created_at": self.created_at,
            "last_reviewed_at": self.last_reviewed_at,
            "is_mastered": bool(self.is_mastered),
        }


class WordRepository:
    """SQLite word repository (singleton, persistent connection)"""

    _instance = None
    _conn: Optional[sqlite3.Connection] = None

    def __new__(cls, db_path: Path = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def initialize(self, db_path: Path, force: bool = False):
        if self._initialized and not force:
            return
        self.db_path = db_path
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate()
        self._initialized = True
        count = self._conn.execute(f"SELECT COUNT(*) FROM words WHERE {NOT_DELETED}").fetchone()[0]
        logger.info(f"Database initialized: {db_path}, {count} words")

    def close(self):
        if self._conn is not None:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ────────── Schema ──────────

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS words (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                word             TEXT NOT NULL UNIQUE COLLATE NOCASE,
                phonetic         TEXT DEFAULT '',
                part_of_speech   TEXT DEFAULT '',
                definition       TEXT DEFAULT '',
                english_definition TEXT DEFAULT '',
                examples_json    TEXT DEFAULT '[]',
                synonyms_json    TEXT DEFAULT '[]',
                notes            TEXT DEFAULT '',
                review_stage     INTEGER DEFAULT 0,
                next_review_date TEXT DEFAULT '',
                total_reviews    INTEGER DEFAULT 0,
                correct_reviews  INTEGER DEFAULT 0,
                created_at       TEXT NOT NULL,
                last_reviewed_at TEXT DEFAULT '',
                is_mastered      INTEGER DEFAULT 0,
                updated_at       TEXT DEFAULT '',
                deleted_at       TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_next_review ON words(next_review_date);
            CREATE INDEX IF NOT EXISTS idx_is_mastered ON words(is_mastered);
        """)

    def _migrate(self):
        """Add columns that may be missing from older schema versions."""
        for col, defn in [
            ("english_definition", "TEXT DEFAULT ''"),
            ("correct_reviews", "INTEGER DEFAULT 0"),
            ("last_reviewed_at", "TEXT DEFAULT ''"),
            ("is_mastered", "INTEGER DEFAULT 0"),
            ("updated_at", "TEXT DEFAULT ''"),
            ("deleted_at", "TEXT DEFAULT ''"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE words ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass  # column already exists


        # Create index on deleted_at after column migration
        try:
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_deleted_at ON words(deleted_at)")
        except sqlite3.OperationalError:
            pass
    # ────────── Write operations ──────────

    def add_or_update_word(self, data: Dict[str, Any]):
        word_text = data.get("word", "").strip()
        if not word_text:
            raise ValueError("Word cannot be empty")

        now = _now_iso()
        existing = self._conn.execute(
            "SELECT id FROM words WHERE word = ? COLLATE NOCASE", (word_text,)
        ).fetchone()

        if existing:
            self._conn.execute("""
                UPDATE words SET
                    phonetic = ?, part_of_speech = ?, definition = ?,
                    english_definition = ?, examples_json = ?, synonyms_json = ?,
                    notes = ?, updated_at = ?, deleted_at = ''
                WHERE id = ?
            """, (
                data.get("phonetic", ""),
                data.get("part_of_speech", ""),
                data.get("definition", ""),
                data.get("english_definition", ""),
                json.dumps(data.get("examples", []), ensure_ascii=False),
                json.dumps(data.get("synonyms", []), ensure_ascii=False),
                data.get("notes", ""),
                now,
                existing[0],
            ))
        else:
            self._conn.execute("""
                INSERT INTO words (
                    word, phonetic, part_of_speech, definition,
                    english_definition, examples_json, synonyms_json,
                    notes, review_stage, next_review_date,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """, (
                word_text,
                data.get("phonetic", ""),
                data.get("part_of_speech", ""),
                data.get("definition", ""),
                data.get("english_definition", ""),
                json.dumps(data.get("examples", []), ensure_ascii=False),
                json.dumps(data.get("synonyms", []), ensure_ascii=False),
                data.get("notes", ""),
                (date.today() + timedelta(days=EBBINGHAUS_INTERVALS[0])).isoformat(),
                now,
                now,
            ))
        self._conn.commit()

    def mark_reviewed(self, word_id: int, result: str):
        """result: 'known' | 'fuzzy' | 'forgot'"""
        row = self._conn.execute(
            f"SELECT * FROM words WHERE id = ? AND {NOT_DELETED}", (word_id,)
        ).fetchone()
        if not row:
            return

        word = Word(tuple(row))
        total = word.total_reviews + 1
        correct = word.correct_reviews + (1 if result == "known" else 0)

        if result == "known":
            new_stage = word.review_stage + 1
        elif result == "forgot":
            new_stage = max(word.review_stage - 1, 0)
        else:
            new_stage = word.review_stage

        is_mastered = 1 if new_stage >= len(EBBINGHAUS_INTERVALS) else 0

        if is_mastered:
            next_review = ""
        elif result == "fuzzy":
            next_review = (date.today() + timedelta(days=1)).isoformat()
        else:
            days = EBBINGHAUS_INTERVALS[new_stage]
            next_review = (date.today() + timedelta(days=days)).isoformat()

        now = _now_iso()
        self._conn.execute("""
            UPDATE words SET
                review_stage = ?, next_review_date = ?, is_mastered = ?,
                total_reviews = ?, correct_reviews = ?, last_reviewed_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (new_stage, next_review, is_mastered, total, correct, now, now, word_id))

        try:
            self._conn.commit()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower() or "busy" in str(e).lower():
                import time
                logger.warning(f"mark_reviewed commit conflict, retrying: {e}")
                time.sleep(0.1)
                try:
                    self._conn.commit()
                except Exception as e2:
                    logger.error(f"mark_reviewed commit retry failed: {e2}")
                    raise
            else:
                raise

    def delete_word(self, word_id: int):
        """Soft-delete: sets deleted_at + updated_at so sync propagates it."""
        now = _now_iso()
        self._conn.execute(
            "UPDATE words SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, word_id),
        )
        self._conn.commit()

    # ────────── Read operations ──────────

    def get_word_by_text(self, word: str) -> Optional[Word]:
        row = self._conn.execute(
            f"SELECT * FROM words WHERE word = ? COLLATE NOCASE AND {NOT_DELETED}",
            (word,),
        ).fetchone()
        return Word(tuple(row)) if row else None

    def get_word_by_id(self, word_id: int) -> Optional[Word]:
        row = self._conn.execute(
            f"SELECT * FROM words WHERE id = ? AND {NOT_DELETED}", (word_id,)
        ).fetchone()
        return Word(tuple(row)) if row else None

    def get_due_for_review(self) -> List[Word]:
        today = date.today().isoformat()
        rows = self._conn.execute(f"""
            SELECT * FROM words
            WHERE {NOT_DELETED}
              AND is_mastered = 0
              AND next_review_date != ''
              AND next_review_date <= ?
            ORDER BY RANDOM()
        """, (today,)).fetchall()
        return [Word(tuple(r)) for r in rows]

    def get_all_words(self, search: str = "", page: int = 1, page_size: int = 50):
        offset = (page - 1) * page_size
        if search:
            pattern = f"%{search}%"
            rows = self._conn.execute(f"""
                SELECT * FROM words
                WHERE {NOT_DELETED} AND (word LIKE ? OR definition LIKE ?)
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (pattern, pattern, page_size, offset)).fetchall()
            total = self._conn.execute(f"""
                SELECT COUNT(*) FROM words
                WHERE {NOT_DELETED} AND (word LIKE ? OR definition LIKE ?)
            """, (pattern, pattern)).fetchone()[0]
        else:
            rows = self._conn.execute(f"""
                SELECT * FROM words
                WHERE {NOT_DELETED}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (page_size, offset)).fetchall()
            total = self._conn.execute(f"SELECT COUNT(*) FROM words WHERE {NOT_DELETED}").fetchone()[0]
        return [Word(tuple(r)) for r in rows], total

    def get_stats(self) -> Dict[str, int]:
        today = date.today().isoformat()
        total = self._conn.execute(f"SELECT COUNT(*) FROM words WHERE {NOT_DELETED}").fetchone()[0]
        mastered = self._conn.execute(
            f"SELECT COUNT(*) FROM words WHERE {NOT_DELETED} AND is_mastered = 1"
        ).fetchone()[0]
        due_today = self._conn.execute(f"""
            SELECT COUNT(*) FROM words
            WHERE {NOT_DELETED}
              AND is_mastered = 0
              AND next_review_date != ''
              AND next_review_date <= ?
        """, (today,)).fetchone()[0]
        return {
            "total": total,
            "mastered": mastered,
            "due_today": due_today,
            "learning": total - mastered,
        }


# Global singleton
word_repo = WordRepository()
