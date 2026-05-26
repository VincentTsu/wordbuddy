"""
WordBuddy SQLite 数据库层
提供单词的增删改查和艾宾浩斯复习状态管理
"""

import sqlite3
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

from app.constants import EBBINGHAUS_INTERVALS

logger = logging.getLogger(__name__)


class Word:
    """单词数据模型"""
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
                self.is_mastered
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
    """SQLite 单词数据访问层（单例，持久连接）"""

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
        # 先关闭旧连接（强制重载时）
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        # 持久化连接，避免反复创建/销毁
        self._conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._initialized = True
        count = self._conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        logger.info(f"数据库已初始化: {db_path}，已有 {count} 个单词")

    def close(self):
        """关闭数据库连接（释放文件锁，用于同步前）"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._initialized = False
        logger.info("数据库连接已关闭（等待同步）")

    def _create_tables(self):
        self._conn.execute("""
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
                is_mastered      INTEGER DEFAULT 0
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_next_review ON words(next_review_date)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_is_mastered ON words(is_mastered)
        """)
        self._conn.commit()
        # 迁移旧 schema → 新 schema（兼容不同版本的 DB）
        self._migrate_schema()

    def _migrate_schema(self):
        """
        迁移旧版 DB 的列名到新版 schema。
        旧版列: added_date, stage, query_count
        新版列: created_at, review_stage, total_reviews, correct_reviews,
                last_reviewed_at, is_mastered
        """
        # 获取当前表的列名
        cursor = self._conn.execute("PRAGMA table_info(words)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        migrated = False

        # added_date → created_at
        if 'added_date' in existing_cols and 'created_at' not in existing_cols:
            self._conn.execute(
                "UPDATE words SET created_at = added_date WHERE created_at = '' OR created_at IS NULL"
            )
            self._conn.execute("ALTER TABLE words RENAME COLUMN added_date TO created_at")
            migrated = True

        # stage → review_stage
        if 'stage' in existing_cols and 'review_stage' not in existing_cols:
            self._conn.execute("ALTER TABLE words RENAME COLUMN stage TO review_stage")
            migrated = True

        # query_count → total_reviews
        if 'query_count' in existing_cols and 'total_reviews' not in existing_cols:
            self._conn.execute("ALTER TABLE words RENAME COLUMN query_count TO total_reviews")
            migrated = True

        # 如果缺少新列，添加它们（ALTER TABLE ADD COLUMN）
        new_cols = {
            'correct_reviews': 'INTEGER DEFAULT 0',
            'last_reviewed_at': "TEXT DEFAULT ''",
            'is_mastered': 'INTEGER DEFAULT 0',
            'english_definition': "TEXT DEFAULT ''",
        }
        for col, col_def in new_cols.items():
            if col not in existing_cols and col not in {'created_at', 'review_stage', 'total_reviews'}:
                try:
                    self._conn.execute(f"ALTER TABLE words ADD COLUMN {col} {col_def}")
                    migrated = True
                except Exception:
                    pass  # 列已存在则跳过

        if migrated:
            self._conn.commit()
            logger.info("数据库 schema 迁移完成")

    # ────────── 写操作 ──────────

    def add_or_update_word(self, data: Dict[str, Any]) -> Word:
        """添加单词；若已存在则更新释义（保留复习进度）"""
        now = datetime.now().isoformat()
        word_text = data.get("word", "").strip()
        if not word_text:
            raise ValueError("单词不能为空")

        examples_json = json.dumps(data.get("examples", []), ensure_ascii=False)
        synonyms_json = json.dumps(data.get("synonyms", []), ensure_ascii=False)

        existing = self._conn.execute(
            "SELECT id FROM words WHERE word = ? COLLATE NOCASE", (word_text,)
        ).fetchone()

        if existing:
            self._conn.execute("""
                UPDATE words SET
                    phonetic = ?, part_of_speech = ?, definition = ?,
                    english_definition = ?, examples_json = ?,
                    synonyms_json = ?, notes = ?
                WHERE word = ? COLLATE NOCASE
            """, (
                data.get("phonetic", ""),
                data.get("part_of_speech", ""),
                data.get("definition", ""),
                data.get("english_definition", ""),
                examples_json,
                synonyms_json,
                data.get("notes", ""),
                word_text,
            ))
        else:
            next_review = (date.today() + timedelta(days=EBBINGHAUS_INTERVALS[0])).isoformat()
            self._conn.execute("""
                INSERT INTO words (
                    word, phonetic, part_of_speech, definition,
                    english_definition, examples_json, synonyms_json,
                    notes, review_stage, next_review_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (
                word_text,
                data.get("phonetic", ""),
                data.get("part_of_speech", ""),
                data.get("definition", ""),
                data.get("english_definition", ""),
                examples_json,
                synonyms_json,
                data.get("notes", ""),
                next_review,
                now,
            ))
        self._conn.commit()
        logger.info(f"单词已保存: {word_text}")
        return self.get_word_by_text(word_text)

    def mark_reviewed(self, word_id: int, result: str):
        """
        处理复习结果，更新艾宾浩斯阶段和下次复习时间
        :param word_id: 单词 ID
        :param result: "remembered" | "fuzzy" | "forgotten"
        """
        if self._conn is None:
            logger.warning("mark_reviewed: DB 连接未初始化，跳过")
            return

        row = self._conn.execute(
            "SELECT review_stage, total_reviews, correct_reviews FROM words WHERE id = ?",
            (word_id,)
        ).fetchone()
        if not row:
            return

        stage = row["review_stage"]
        total = row["total_reviews"] + 1
        correct = row["correct_reviews"] + (1 if result == "remembered" else 0)

        if result == "remembered":
            # 记住了 → 正常推进
            new_stage = min(stage + 1, len(EBBINGHAUS_INTERVALS))
        elif result == "fuzzy":
            # 模糊 → 不退阶，明天再复习（固定 1 天间隔）
            new_stage = stage
        else:
            # 没记住 → 退回上一阶段（最低 0）
            new_stage = max(stage - 1, 0)

        is_mastered = 1 if new_stage >= len(EBBINGHAUS_INTERVALS) else 0

        if is_mastered:
            next_review = ""
        elif result == "fuzzy":
            # 模糊：固定明天再复习，不按阶段间隔
            next_review = (date.today() + timedelta(days=1)).isoformat()
        else:
            days = EBBINGHAUS_INTERVALS[new_stage]
            next_review = (date.today() + timedelta(days=days)).isoformat()

        now = datetime.now().isoformat()
        self._conn.execute("""
            UPDATE words SET
                review_stage = ?, next_review_date = ?, is_mastered = ?,
                total_reviews = ?, correct_reviews = ?, last_reviewed_at = ?
            WHERE id = ?
        """, (new_stage, next_review, is_mastered, total, correct, now, word_id))

        # 使用独立事务提交，避免与后台 WAL checkpoint 冲突
        # isolation_level=None（autocommit）时不需要 commit()，
        # 但当前是默认 deferred 模式，需要 commit
        try:
            self._conn.commit()
        except sqlite3.OperationalError as e:
            # SQLITE_BUSY：后台正在 checkpoint，稍等后重试一次
            if "database is locked" in str(e).lower() or "busy" in str(e).lower():
                import time
                logger.warning(f"mark_reviewed commit 遇到锁争用，100ms 后重试: {e}")
                time.sleep(0.1)
                try:
                    self._conn.commit()
                except Exception as e2:
                    logger.error(f"mark_reviewed commit 重试失败: {e2}")
                    raise
            else:
                raise

    def delete_word(self, word_id: int):
        self._conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
        self._conn.commit()

    # ────────── 读操作 ──────────

    def get_word_by_text(self, word: str) -> Optional[Word]:
        row = self._conn.execute(
            "SELECT * FROM words WHERE word = ? COLLATE NOCASE", (word,)
        ).fetchone()
        return Word(tuple(row)) if row else None

    def get_word_by_id(self, word_id: int) -> Optional[Word]:
        row = self._conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
        return Word(tuple(row)) if row else None

    def get_due_for_review(self) -> List[Word]:
        """获取今天及之前到期、尚未掌握的单词列表（随机打乱顺序）"""
        today = date.today().isoformat()
        rows = self._conn.execute("""
            SELECT * FROM words
            WHERE is_mastered = 0
              AND next_review_date != ''
              AND next_review_date <= ?
            ORDER BY RANDOM()
        """, (today,)).fetchall()
        return [Word(tuple(r)) for r in rows]

    def get_all_words(self, search: str = "", page: int = 1, page_size: int = 50):
        """分页获取所有单词，支持搜索过滤"""
        offset = (page - 1) * page_size
        if search:
            pattern = f"%{search}%"
            rows = self._conn.execute("""
                SELECT * FROM words
                WHERE word LIKE ? OR definition LIKE ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (pattern, pattern, page_size, offset)).fetchall()
            total = self._conn.execute("""
                SELECT COUNT(*) FROM words
                WHERE word LIKE ? OR definition LIKE ?
            """, (pattern, pattern)).fetchone()[0]
        else:
            rows = self._conn.execute("""
                SELECT * FROM words
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (page_size, offset)).fetchall()
            total = self._conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]

        return [Word(tuple(r)) for r in rows], total

    def get_stats(self) -> Dict[str, int]:
        """统计信息"""
        today = date.today().isoformat()
        total = self._conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        mastered = self._conn.execute(
            "SELECT COUNT(*) FROM words WHERE is_mastered = 1"
        ).fetchone()[0]
        due_today = self._conn.execute("""
            SELECT COUNT(*) FROM words
            WHERE is_mastered = 0
              AND next_review_date != ''
              AND next_review_date <= ?
        """, (today,)).fetchone()[0]
        return {
            "total": total,
            "mastered": mastered,
            "due_today": due_today,
            "learning": total - mastered,
        }


# 全局单例
word_repo = WordRepository()
