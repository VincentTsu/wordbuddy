"""
WordBuddy 艾宾浩斯复习弹窗
简约设计：无边框卡片 + 自适应高度 + 长内容自动换行
"""

import logging
import random
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QSizePolicy, QScrollArea, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QThread
from PyQt6.QtGui import QFont, QColor, QGuiApplication, QShortcut, QKeySequence

from app.db.repository import Word
from app.services.review_service import review_service
from app.constants import REVIEW_STAGE_LABELS, EBBINGHAUS_INTERVALS

logger = logging.getLogger(__name__)

# ── 设计 token ──────────────────────────────────────────────
C_BG          = "#FFFFFF"
C_BORDER      = "#EBEBEB"
C_WORD        = "#111111"
C_PHONETIC    = "#999999"
C_POS_BG      = "#F3F4F6"
C_POS_FG      = "#6B7280"
C_DEF         = "#374151"
C_EXAMPLE     = "#9CA3AF"
C_STAGE       = "#D1D5DB"
C_FORGET_BG   = "#FEF2F2"
C_FORGET_FG   = "#EF4444"
C_FORGET_HO   = "#FEE2E2"
C_REMEMBER_BG = "#F0FDF4"
C_REMEMBER_FG = "#22C55E"
C_REMEMBER_HO = "#DCFCE7"
C_FILL_BG    = "#EEF2FF"
C_FILL_FG    = "#4F46E5"
C_FILL_HO    = "#E0E7FF"
C_BLANK_BG   = "#FEF9C3"
C_BLANK_FG   = "#92400E"
FONT          = "'Segoe UI', 'Microsoft YaHei UI', sans-serif"
WIN_W         = 400          # 固定宽度
WIN_MAX_H     = 560          # 最大高度（填空模式需要更多空间）


class SentenceWorker(QThread):
    """后台线程：调用 LLM 生成例句"""
    done = pyqtSignal(dict, str)   # ({"sentence": ..., "translation": ...}, error_msg)

    def __init__(self, word: str):
        super().__init__()
        self._word = word

    def run(self):
        try:
            from app.services.llm_service import llm_service
            result = llm_service.generate_sentence(self._word)
            self.done.emit(result, "")
        except Exception as e:
            self.done.emit({"sentence": f"[{self._word}]", "translation": ""}, str(e))


class ReviewDialog(QWidget):
    """艾宾浩斯复习弹窗（继承 QWidget，避免关闭时触发 Qt 退出）"""

    review_done    = pyqtSignal(int, str)   # (word_id, result: "remembered"|"fuzzy"|"forgotten")
    all_done       = pyqtSignal()
    closed         = pyqtSignal()           # 用户手动关闭窗口（点 X）
    snooze         = pyqtSignal()           # 用户点击"稍后提醒"
    word_deleted   = pyqtSignal(int)        # (word_id) 用户在复习中删除了单词

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_word: Optional[Word] = None
        self._fill_mode = False        # 当前是否为填空模式
        self._sentence_worker = None   # 后台生成例句线程
        self._pending_sentence = None  # 预加载的例句数据
        self._correct_word = ""        # 填空模式的正确答案
        self._answer_revealed = False  # 释义是否已揭示
        self._init_ui()
        self._bind_shortcuts()

    # ──────────────────────────────────────────────────────────
    # 键盘快捷键
    # ──────────────────────────────────────────────────────────
    def _bind_shortcuts(self):
        """绑定键盘快捷键：空格/回车揭示，1/2/3 对应三档评价"""
        # 空格 / 回车 → 揭示释义
        self._reveal_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._reveal_shortcut.activated.connect(self._try_reveal)
        self._enter_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        self._enter_shortcut.activated.connect(self._try_reveal)

        # 1 = 没记住，2 = 模糊，3 = 记住了
        self._key1 = QShortcut(QKeySequence(Qt.Key.Key_1), self)
        self._key1.activated.connect(lambda: self._handle_result("forgotten"))
        self._key2 = QShortcut(QKeySequence(Qt.Key.Key_2), self)
        self._key2.activated.connect(lambda: self._handle_result("fuzzy"))
        self._key3 = QShortcut(QKeySequence(Qt.Key.Key_3), self)
        self._key3.activated.connect(lambda: self._handle_result("remembered"))

    def _try_reveal(self):
        """如果释义还未揭示，则揭示；填空模式下回车检查答案"""
        if self._fill_mode:
            self._check_fill_answer()
            return
        if not self._answer_widget.isVisible():
            self._reveal_answer()

    # ──────────────────────────────────────────────────────────
    # 构建 UI
    # ──────────────────────────────────────────────────────────
    def _init_ui(self):
        self.setWindowTitle("WordBuddy")
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.FramelessWindowHint       # 无边框，自己画边框
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 最外层：透明背景，用于阴影留白
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 16)   # 留阴影空间
        outer.setSpacing(0)

        # 卡片容器
        self._card = QFrame()
        self._card.setObjectName("card")
        self._card.setStyleSheet(f"""
            QFrame#card {{
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 16px;
            }}
        """)
        # 软阴影
        try:
            from PyQt6.QtWidgets import QGraphicsDropShadowEffect
            sh = QGraphicsDropShadowEffect()
            sh.setBlurRadius(32)
            sh.setOffset(0, 8)
            sh.setColor(QColor(0, 0, 0, 28))
            self._card.setGraphicsEffect(sh)
        except Exception:
            pass

        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ── 顶部窄条（进度 + 稍后提醒 + 阶段） ──
        top_bar = QWidget()
        top_bar.setFixedHeight(36)
        top_bar.setStyleSheet("background: transparent;")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(20, 0, 16, 0)

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 11px;
            color: {C_STAGE};
            letter-spacing: 0.5px;
        """)
        top_bar_layout.addWidget(self.progress_label)
        top_bar_layout.addStretch()

        # 稍后提醒按钮（30 分钟后再弹）
        self.snooze_btn = QPushButton("稍后")
        self.snooze_btn.setFixedSize(44, 22)
        self.snooze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snooze_btn.setToolTip("稍后提醒（30 分钟后）")
        self.snooze_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT};
                font-size: 11px;
                color: #9CA3AF;
                background: transparent;
                border: 1px solid #E5E7EB;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                color: #6B7280;
                background: #F3F4F6;
                border-color: #D1D5DB;
            }}
            QPushButton:pressed {{ background: #E5E7EB; }}
        """)
        self.snooze_btn.clicked.connect(self._on_snooze)
        top_bar_layout.addWidget(self.snooze_btn)

        top_bar_layout.addSpacing(8)

        self.stage_label = QLabel()
        self.stage_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 11px;
            color: {C_STAGE};
        """)
        top_bar_layout.addWidget(self.stage_label)
        card_layout.addWidget(top_bar)

        # 分隔线
        divider_top = QFrame()
        divider_top.setFrameShape(QFrame.Shape.HLine)
        divider_top.setStyleSheet(f"background: {C_BORDER}; max-height: 1px; border: none;")
        card_layout.addWidget(divider_top)

        # ── 内容区（可滚动） ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                width: 4px; background: transparent; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #E5E7EB; border-radius: 2px; min-height: 24px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 12, 24, 12)
        content_layout.setSpacing(6)

        # 单词（大字）
        self.word_label = QLabel()
        self.word_label.setWordWrap(True)
        self.word_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.word_label.setStyleSheet(f"""
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 30px;
            font-weight: 700;
            color: {C_WORD};
            line-height: 1.3;
        """)
        content_layout.addWidget(self.word_label)

        # 音标 + 词性（同一行）
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        meta_row.setContentsMargins(0, 0, 0, 0)

        self.phonetic_label = QLabel()
        self.phonetic_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 13px;
            color: {C_PHONETIC};
        """)
        meta_row.addWidget(self.phonetic_label)

        self.pos_label = QLabel()
        self.pos_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 11px;
            font-weight: 600;
            color: {C_POS_FG};
            background: {C_POS_BG};
            border-radius: 4px;
            padding: 1px 7px;
        """)
        self.pos_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        meta_row.addWidget(self.pos_label)
        meta_row.addStretch()
        content_layout.addLayout(meta_row)

        # 分隔线（细）
        sep = QFrame()
        sep.setObjectName("content_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {C_BORDER}; max-height: 1px; border: none; margin: 4px 0;")
        content_layout.addWidget(sep)

        # 点击揭示释义按钮
        self.reveal_btn = QPushButton("点击查看释义")
        self.reveal_btn.setFixedHeight(36)
        self.reveal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reveal_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT};
                font-size: 12px;
                color: #9CA3AF;
                background: #F9FAFB;
                border: 1px dashed #D1D5DB;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                color: #6B7280;
                background: #F3F4F6;
                border-color: #9CA3AF;
            }}
            QPushButton:pressed {{
                background: #E5E7EB;
            }}
        """)
        self.reveal_btn.clicked.connect(self._reveal_answer)
        content_layout.addWidget(self.reveal_btn)

        # ── 填空模式 UI（默认隐藏） ──
        self._fill_widget = QWidget()
        self._fill_widget.setStyleSheet("background: transparent;")
        fill_layout = QVBoxLayout(self._fill_widget)
        fill_layout.setContentsMargins(0, 0, 0, 0)
        fill_layout.setSpacing(4)

        # 例句（带填空）+ 中文翻译
        self.fill_sentence_label = QLabel()
        self.fill_sentence_label.setWordWrap(True)
        self.fill_sentence_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.fill_sentence_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 13px;
            color: {C_DEF};
            line-height: 1.6;
        """)
        fill_layout.addWidget(self.fill_sentence_label)

        self.fill_translation_label = QLabel()
        self.fill_translation_label.setWordWrap(True)
        self.fill_translation_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.fill_translation_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 12px;
            color: {C_EXAMPLE};
        """)
        fill_layout.addWidget(self.fill_translation_label)

        # 输入框 + 检查按钮（同一行，紧凑）
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.setContentsMargins(0, 2, 0, 0)

        self.fill_input = QLineEdit()
        self.fill_input.setFixedHeight(36)
        self.fill_input.setPlaceholderText("拼写这个单词...")
        self.fill_input.setStyleSheet(f"""
            QLineEdit {{
                font-family: 'Georgia', 'Times New Roman', serif;
                font-size: 15px;
                color: {C_FILL_FG};
                background: white;
                border: 2px solid #C7D2FE;
                border-radius: 8px;
                padding: 0 12px;
            }}
            QLineEdit:focus {{
                border-color: {C_FILL_FG};
                background: {C_FILL_BG};
            }}
        """)
        self.fill_input.returnPressed.connect(self._check_fill_answer)
        input_row.addWidget(self.fill_input, 1)

        self.fill_check_btn = QPushButton("检查")
        self.fill_check_btn.setFixedHeight(36)
        self.fill_check_btn.setFixedWidth(60)
        self.fill_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fill_check_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT};
                font-size: 13px;
                font-weight: 600;
                color: white;
                background: {C_FILL_FG};
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{ background: #6366F1; }}
            QPushButton:pressed {{ background: #4338CA; }}
            QPushButton:disabled {{ background: #A5B4FC; }}
        """)
        self.fill_check_btn.clicked.connect(self._check_fill_answer)
        input_row.addWidget(self.fill_check_btn)
        fill_layout.addLayout(input_row)

        # 检查结果反馈（内联）
        self.fill_result_label = QLabel()
        self.fill_result_label.setWordWrap(True)
        self.fill_result_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 13px;
            line-height: 1.5;
        """)
        self.fill_result_label.hide()
        fill_layout.addWidget(self.fill_result_label)

        self._fill_widget.hide()
        content_layout.addWidget(self._fill_widget)

        # 释义区域（初始隐藏）
        self._answer_widget = QWidget()
        self._answer_widget.setStyleSheet("background: transparent;")
        answer_layout = QVBoxLayout(self._answer_widget)
        answer_layout.setContentsMargins(0, 0, 0, 0)
        answer_layout.setSpacing(4)

        self.definition_label = QLabel()
        self.definition_label.setWordWrap(True)
        self.definition_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.definition_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 14px;
            color: {C_DEF};
            line-height: 1.6;
        """)
        answer_layout.addWidget(self.definition_label)

        # 例句
        self.example_label = QLabel()
        self.example_label.setWordWrap(True)
        self.example_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.example_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 12px;
            color: {C_EXAMPLE};
            font-style: italic;
            padding-top: 2px;
        """)
        answer_layout.addWidget(self.example_label)

        self._answer_widget.hide()
        content_layout.addWidget(self._answer_widget)
        content_layout.addStretch()

        scroll.setWidget(content_widget)
        card_layout.addWidget(scroll, 1)   # stretch=1，填满剩余空间

        # 分隔线
        divider_bot = QFrame()
        divider_bot.setFrameShape(QFrame.Shape.HLine)
        divider_bot.setStyleSheet(f"background: {C_BORDER}; max-height: 1px; border: none;")
        card_layout.addWidget(divider_bot)

        # ── 按钮区 ──
        btn_area = QWidget()
        btn_area.setFixedHeight(68)
        btn_area.setStyleSheet("background: transparent;")
        btn_layout = QHBoxLayout(btn_area)
        btn_layout.setContentsMargins(16, 12, 16, 12)
        btn_layout.setSpacing(8)

        self.forgotten_btn = QPushButton("没记住")
        self.forgotten_btn.setFixedHeight(44)
        self.forgotten_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forgotten_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT};
                font-size: 13px;
                font-weight: 600;
                color: {C_FORGET_FG};
                background: {C_FORGET_BG};
                border: 1px solid #FECACA;
                border-radius: 10px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover  {{ background: {C_FORGET_HO}; }}
            QPushButton:pressed {{ background: #FECACA; }}
        """)
        self.forgotten_btn.clicked.connect(lambda: self._handle_result("forgotten"))

        # 模糊按钮（中间选项）
        C_FUZZY_BG = "#FFFBEB"
        C_FUZZY_FG = "#D97706"
        C_FUZZY_HO = "#FEF3C7"
        self.fuzzy_btn = QPushButton("模糊")
        self.fuzzy_btn.setFixedHeight(44)
        self.fuzzy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fuzzy_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT};
                font-size: 13px;
                font-weight: 600;
                color: {C_FUZZY_FG};
                background: {C_FUZZY_BG};
                border: 1px solid #FDE68A;
                border-radius: 10px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover  {{ background: {C_FUZZY_HO}; }}
            QPushButton:pressed {{ background: #FDE68A; }}
        """)
        self.fuzzy_btn.clicked.connect(lambda: self._handle_result("fuzzy"))

        self.remember_btn = QPushButton("记住了")
        self.remember_btn.setFixedHeight(44)
        self.remember_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remember_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT};
                font-size: 13px;
                font-weight: 600;
                color: {C_REMEMBER_FG};
                background: {C_REMEMBER_BG};
                border: 1px solid #BBF7D0;
                border-radius: 10px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover  {{ background: {C_REMEMBER_HO}; }}
            QPushButton:pressed {{ background: #BBF7D0; }}
        """)
        self.remember_btn.clicked.connect(lambda: self._handle_result("remembered"))

        btn_layout.addWidget(self.forgotten_btn)
        btn_layout.addWidget(self.fuzzy_btn)
        btn_layout.addWidget(self.remember_btn)

        # 删除按钮（右侧）
        self.delete_btn = QPushButton("🗑")
        self.delete_btn.setFixedSize(36, 36)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setToolTip("删除此单词")
        self.delete_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT};
                font-size: 14px;
                color: #9CA3AF;
                background: transparent;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                color: #EF4444;
                background: #FEF2F2;
                border-color: #FECACA;
            }}
            QPushButton:pressed {{
                background: #FEE2E2;
            }}
            QPushButton:disabled {{
                color: #D1D5DB;
                border-color: #F3F4F6;
            }}
        """)
        self.delete_btn.clicked.connect(self._on_delete_word)
        btn_layout.addWidget(self.delete_btn)
        card_layout.addWidget(btn_area)

        # 初始宽度
        self.setFixedWidth(WIN_W + 24)   # +24 = 两侧阴影边距

    # ──────────────────────────────────────────────────────────
    # 加载单词
    # ──────────────────────────────────────────────────────────
    def load_word(self, word: Word):
        """加载要复习的单词，并自适应高度"""
        self._current_word = word
        self._answer_revealed = False

        # 强制恢复按钮状态（防止上次复习完成时按钮未被 enable 就 hide 了窗口，
        # 导致第二天再次 show 时按钮仍是 disabled）
        self._enable_buttons()

        # ── 决定本次复习模式 ──
        from app.config import config
        fill_ratio = config.fill_ratio  # 0~100
        self._fill_mode = fill_ratio > 0 and random.randint(1, 100) <= fill_ratio

        if self._fill_mode:
            self._load_fill_mode(word)
        else:
            self._load_normal_mode(word)

        # 阶段 / 进度
        stage = word.review_stage
        total = len(EBBINGHAUS_INTERVALS)
        if stage < total:
            self.stage_label.setText(f"第 {stage + 1} / {total} 阶段")
        else:
            self.stage_label.setText("已掌握")

        # get_due_words() 返回的是已从队列移除当前词后的剩余列表
        due_count = len(review_service.get_due_words())
        self.progress_label.setText(f"今日剩余  {due_count}")

        # 自适应高度并定位
        self._adjust_height()
        self._position_bottom_right()

    def _load_normal_mode(self, word: Word):
        """普通认词模式：显示英文单词 → 揭示中文释义"""
        self._fill_widget.hide()
        # 恢复填空模式可能隐藏的元素
        self.word_label.show()
        self.word_label.setText(word.word)
        self.phonetic_label.setText(word.phonetic or "")
        self.phonetic_label.setVisible(bool(word.phonetic))
        pos = word.part_of_speech or ""
        self.pos_label.setText(pos)
        self.pos_label.setVisible(bool(pos))
        sep = self.findChild(QFrame, "content_sep")
        if sep:
            sep.show()
        # 预加载释义/例句文本，但先隐藏
        self.definition_label.setText(word.definition or word.english_definition or "")
        examples = word.examples
        if examples:
            self.example_label.setText("\u201c" + examples[0] + "\u201d")
            self.example_label.show()
        else:
            self.example_label.hide()
        # 隐藏释义区域，显示揭示按钮
        self._answer_widget.hide()
        self.reveal_btn.show()

    def _load_fill_mode(self, word: Word):
        """填空输出模式：直接显示中文释义 + 填空例句 + 输入框，不显示英文单词"""
        # 隐藏英文单词、音标、词性、分隔线（答案不能泄露）
        self.word_label.hide()
        self.phonetic_label.hide()
        self.pos_label.hide()
        sep = self.findChild(QFrame, "content_sep")
        if sep:
            sep.hide()

        self.reveal_btn.hide()
        self._correct_word = word.word

        # 隐藏检查结果，重置输入框
        self.fill_result_label.hide()
        self.fill_result_label.setText("")
        self.fill_input.clear()
        self.fill_input.setEnabled(True)
        self.fill_check_btn.setEnabled(True)

        # 显示中文释义（复用正常模式的释义 label，直接展示）
        defn = word.definition or word.english_definition or ""
        self.definition_label.setText(defn)
        self.example_label.hide()  # 填空模式不需要例句 label（用填空例句代替）
        self._answer_widget.show()

        # 先用词库已有例句做填空（立即显示，零等待）
        import re
        examples = word.examples
        if examples:
            blank = re.sub(
                r'\b' + re.escape(word.word) + r'\b',
                '______',
                examples[0],
                count=1,
                flags=re.IGNORECASE
            )
            self.fill_sentence_label.setText(blank)
            self.fill_sentence_label.show()
        else:
            self.fill_sentence_label.setText("...")
            self.fill_sentence_label.show()

        self.fill_translation_label.hide()

        # 显示填空 UI（输入框 + 检查按钮）
        self._fill_widget.show()
        self.fill_input.setFocus()
        self._adjust_height()

        # 如果有预加载的 LLM 例句，静默替换
        if self._pending_sentence:
            sentence = self._pending_sentence.get("sentence", "")
            translation = self._pending_sentence.get("translation", "")
            if sentence:
                blank = re.sub(
                    r'\b' + re.escape(word.word) + r'\b',
                    '______',
                    sentence,
                    count=1,
                    flags=re.IGNORECASE
                )
                self.fill_sentence_label.setText(blank)
                if translation:
                    self.fill_translation_label.setText(translation)
                    self.fill_translation_label.show()
                self._adjust_height()
            self._pending_sentence = None
        else:
            # 后台生成新例句，就绪后静默替换
            self._fetch_sentence(word.word)

    def _fetch_sentence(self, word: str):
        """后台线程调用 LLM 生成例句"""
        if self._sentence_worker and self._sentence_worker.isRunning():
            self._sentence_worker.terminate()
        self._sentence_worker = SentenceWorker(word)
        self._sentence_worker.done.connect(self._on_sentence_from_worker)
        self._sentence_worker.start()

    def _on_sentence_from_worker(self, data: dict, error: str):
        """SentenceWorker 完成回调，静默替换例句"""
        if not error:
            self._on_sentence_ready(data)

    def _on_sentence_ready(self, data: dict):
        """例句生成完成，静默替换当前显示的例句"""
        if not self._fill_mode:
            return
        sentence = data.get("sentence", "")
        translation = data.get("translation", "")
        word = self._correct_word

        if not sentence:
            return

        import re
        blank_sentence = re.sub(
            r'\b' + re.escape(word) + r'\b',
            '______',
            sentence,
            count=1,
            flags=re.IGNORECASE
        )
        self.fill_sentence_label.setText(blank_sentence)

        if translation:
            self.fill_translation_label.setText(translation)
            self.fill_translation_label.show()

        self._adjust_height()

    def _check_fill_answer(self):
        """检查用户的填空答案"""
        if not self._fill_mode or not self._correct_word:
            return
        answer = self.fill_input.text().strip()
        correct = self._correct_word.strip()
        is_correct = answer.lower() == correct.lower()

        # 禁用输入
        self.fill_input.setEnabled(False)
        self.fill_check_btn.setEnabled(False)

        if is_correct:
            self.fill_result_label.setStyleSheet(f"""
                font-family: {FONT};
                font-size: 13px;
                color: #22C55E;
                font-weight: 600;
                line-height: 1.5;
            """)
            self.fill_result_label.setText("✅ 完全正确！")
        else:
            self.fill_result_label.setStyleSheet(f"""
                font-family: {FONT};
                font-size: 13px;
                color: {C_FORGET_FG};
                line-height: 1.5;
            """)
            self.fill_result_label.setText(f"❌ 正确答案：<b>{correct}</b>")
        self.fill_result_label.show()
        self._adjust_height()

    def _reveal_answer(self):
        """点击揭示释义/例句"""
        self._answer_revealed = True
        self.reveal_btn.hide()
        self._answer_widget.show()
        # 重新调整高度以适应新显示的内容
        self._adjust_height()

    def _adjust_height(self):
        """根据内容动态调整窗口高度（最大 WIN_MAX_H）"""
        # 用 QTimer 延迟到本轮事件循环结束后再调整，避免阻塞主线程
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._do_adjust_height)

    def _do_adjust_height(self):
        """实际执行高度调整（在事件循环空闲时调用）"""
        # 先让内容区完成布局
        content = self._card.layout()
        if content:
            content.activate()
        hint = self._card.sizeHint()
        new_h = min(max(hint.height(), 260), WIN_MAX_H)
        self.setFixedHeight(new_h + 28)   # +28 = 上下阴影边距
        # 重新定位（高度变了位置也要更新）
        self._position_bottom_right()

    # ──────────────────────────────────────────────────────────
    # 定位
    # ──────────────────────────────────────────────────────────
    def _position_bottom_right(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.right()  - self.width()  - 20
        y = screen.bottom() - self.height() - 20
        self.move(x, y)

    # ──────────────────────────────────────────────────────────
    # 操作逻辑
    # ──────────────────────────────────────────────────────────
    def _handle_result(self, result: str):
        if not self._current_word:
            return

        # 防止重复点击：按钮已禁用则直接忽略
        if not self.remember_btn.isEnabled():
            return

        # 填空模式下，如果用户还没检查答案，不允许直接点按钮跳过
        if self._fill_mode and self.fill_check_btn.isEnabled():
            return

        word_id = self._current_word.id

        # 立即禁用按钮（防止重复点击）
        self.forgotten_btn.setEnabled(False)
        self.fuzzy_btn.setEnabled(False)
        self.remember_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)

        try:
            # 写数据库 + 更新内存队列
            review_service.handle_review_result(word_id, result)
        except Exception as e:
            logger.error(f"handle_review_result 异常: {e}", exc_info=True)
            # 数据库写入失败也继续推进 UI，避免卡死
            # 手动从队列移除（内存层补救）
            try:
                review_service._review_queue = [
                    w for w in review_service._review_queue if w.id != word_id
                ]
                review_service._current_review_word = None
            except Exception:
                pass

        self.review_done.emit(word_id, result)

        try:
            next_word = review_service.get_next_review_word()
        except Exception as e:
            logger.error(f"get_next_review_word 异常: {e}", exc_info=True)
            next_word = None

        if next_word:
            self.load_word(next_word)
            # 恢复按钮（延迟一帧，避免视觉闪烁）
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(80, self._enable_buttons)

            # 预加载下一个词的例句（如果有待复习的后续词）
            self._preload_next_sentence()
        else:
            # 复习全部完成：先恢复按钮状态，再隐藏窗口
            # 必须在 hide() 之前恢复，否则下次 show() 时按钮仍是 disabled
            self._enable_buttons()
            self.all_done.emit()
            self.hide()
            logger.info("今日复习全部完成")

    def _enable_buttons(self):
        self.forgotten_btn.setEnabled(True)
        self.fuzzy_btn.setEnabled(True)
        self.remember_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _on_delete_word(self):
        """删除当前单词并跳到下一个"""
        if not self._current_word:
            return
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要从词库中删除「{self._current_word.word}」吗？\n\n删除后无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        word_id = self._current_word.id

        # 从数据库删除
        try:
            from app.db.repository import word_repo
            word_repo.delete_word(word_id)
        except Exception as e:
            logger.error(f"删除单词失败: {e}", exc_info=True)
            return

        # 从内存队列中移除
        review_service._review_queue = [
            w for w in review_service._review_queue if w.id != word_id
        ]
        review_service._current_review_word = None

        # 通知外部
        self.word_deleted.emit(word_id)

        # 如果有后台例句生成任务，取消
        if self._sentence_worker and self._sentence_worker.isRunning():
            self._sentence_worker.terminate()
            self._sentence_worker = None

        # 加载下一个单词或结束
        next_word = review_service.get_next_review_word()
        if next_word:
            self.load_word(next_word)
        else:
            self._enable_buttons()
            self.all_done.emit()
            self.hide()

    def _on_snooze(self):
        """点击"稍后"按钮：隐藏弹窗，通知 AppController 30 分钟后重新提醒"""
        self.hide()
        self.snooze.emit()

    def _preload_next_sentence(self):
        """预加载下一个可能复习的单词的例句，减少等待时间"""
        try:
            due_words = review_service.get_due_words()
            if not due_words:
                return
            next_word = due_words[0]  # 队列第一个就是下一个
            # 只在填空模式启用时预加载
            from app.config import config
            if config.fill_ratio <= 0:
                return
            # 如果下一个词和当前词相同（不应该发生，但防御），跳过
            if next_word.id == self._current_word.id:
                return
            # 后台生成，结果缓存在 _pending_sentence
            if self._sentence_worker and self._sentence_worker.isRunning():
                self._sentence_worker.terminate()
            self._sentence_worker = SentenceWorker(next_word.word)
            # 用一个临时回调保存结果（不直接更新 UI）
            self._sentence_worker.done.connect(self._on_preload_done)
            self._sentence_worker.start()
        except Exception as e:
            logger.debug(f"预加载例句跳过: {e}")

    def _on_preload_done(self, data: dict, error: str):
        """预加载完成，缓存例句数据"""
        self._pending_sentence = data if not error else None
        if error:
            logger.debug(f"例句预加载失败: {error}")

    def closeEvent(self, event):
        """点 X 只隐藏，不退出程序，并通知 AppController 重置复习状态"""
        self.hide()
        self.closed.emit()
        event.ignore()
