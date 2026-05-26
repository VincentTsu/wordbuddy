"""
WordBuddy 艾宾浩斯复习调度服务
管理复习计划、查询待复习单词
"""

import logging
from datetime import date
from typing import List, Optional

from app.db.repository import word_repo, Word
from app.constants import EBBINGHAUS_INTERVALS, REVIEW_STAGE_LABELS

logger = logging.getLogger(__name__)


class ReviewService:
    """艾宾浩斯记忆法复习调度服务"""

    def __init__(self):
        self._review_queue: List[Word] = []
        self._queue_loaded_date: Optional[date] = None
        self._current_review_word: Optional[Word] = None

    def get_due_words(self, force_refresh: bool = False) -> List[Word]:
        """
        获取今天待复习的单词列表
        :param force_refresh: 是否强制刷新（默认：当天只加载一次）
        """
        today = date.today()
        if force_refresh or self._queue_loaded_date != today:
            self._review_queue = word_repo.get_due_for_review()
            self._queue_loaded_date = today
            logger.info(f"加载待复习单词: {len(self._review_queue)} 个")
        return self._review_queue

    def get_next_review_word(self) -> Optional[Word]:
        """获取下一个待复习的单词（队列里的第一个）"""
        words = self.get_due_words()
        if not words:
            self._current_review_word = None
            return None
        # handle_review_result() 已从队列移除已处理的词
        # 直接取第一个即是下一个待复习词
        self._current_review_word = words[0]
        return self._current_review_word

    def handle_review_result(self, word_id: int, result: str):
        """
        处理复习结果
        :param word_id: 单词 ID
        :param result: "remembered" | "fuzzy" | "forgotten"
        """
        word_repo.mark_reviewed(word_id, result)

        # 从当天队列中移除
        self._review_queue = [w for w in self._review_queue if w.id != word_id]

        if word_id == getattr(self._current_review_word, "id", None):
            self._current_review_word = None

        labels = {"remembered": "✓ 记住", "fuzzy": "~ 模糊", "forgotten": "✗ 未记住"}
        action = labels.get(result, result)
        logger.info(f"复习结果 [{action}]: word_id={word_id}")

    def get_due_count(self) -> int:
        """获取今日待复习数量"""
        return word_repo.get_stats()["due_today"]

    def get_stage_label(self, stage: int) -> str:
        """获取复习阶段文字描述"""
        if stage < len(REVIEW_STAGE_LABELS):
            return REVIEW_STAGE_LABELS[stage]
        return REVIEW_STAGE_LABELS[-1]

    def get_next_review_description(self, stage: int, result: str) -> str:
        """获取下次复习描述"""
        if result == "remembered":
            new_stage = min(stage + 1, len(EBBINGHAUS_INTERVALS))
        elif result == "fuzzy":
            new_stage = stage
        else:
            new_stage = max(stage - 1, 0)

        if new_stage >= len(EBBINGHAUS_INTERVALS):
            return "已完全掌握！"
        days = EBBINGHAUS_INTERVALS[new_stage]
        return f"{days} 天后再次复习"

    def reset_daily_queue(self):
        """重置当天复习队列（用于日期切换）"""
        self._review_queue = []
        self._queue_loaded_date = None
        self._current_review_word = None

    def load_random_words(self, count: int = 10) -> List[Word]:
        """
        手动复习：从所有未掌握的单词中随机选取指定数量
        不受 next_review_date 限制，纯粹随机推送
        """
        self._review_queue = []
        self._queue_loaded_date = date.today()  # 设为今天，防止 get_due_words() 重新查询覆盖
        self._current_review_word = None

        rows = word_repo._conn.execute("""
            SELECT * FROM words
            WHERE is_mastered = 0
            ORDER BY RANDOM()
            LIMIT ?
        """, (count,)).fetchall()
        self._review_queue = [Word(tuple(r)) for r in rows]
        logger.info(f"手动复习：随机选取 {len(self._review_queue)} 个单词")
        return self._review_queue


# 全局单例
review_service = ReviewService()
