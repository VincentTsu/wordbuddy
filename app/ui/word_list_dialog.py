"""
WordBuddy 词库列表窗口
简约设计：白底、去emoji、自适应列宽
"""

import logging
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QTableWidget, QTableWidgetItem, QLineEdit,
    QHeaderView, QAbstractItemView, QMessageBox,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QBrush

from app.db.repository import word_repo
from app.constants import REVIEW_STAGE_LABELS

logger = logging.getLogger(__name__)

# ── 设计 token ──────────────────────────────────────────────
FONT = "'Segoe UI', 'Microsoft YaHei UI', sans-serif"
C_BG = "#FAFAFA"
C_CARD = "#FFFFFF"
C_BORDER = "#EBEBEB"
C_TEXT = "#1F2937"
C_TEXT2 = "#6B7280"
C_TEXT3 = "#9CA3AF"
C_ACCENT = "#3B82F6"
C_ACCENT_LIGHT = "#EFF6FF"
C_GREEN = "#10B981"
C_AMBER = "#F59E0B"


class StatCard(QFrame):
    """统计卡片 - 极简纯文字"""

    def __init__(self, value: str, label: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            QFrame {{
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(2)

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 20px;
            font-weight: 700;
            color: {C_TEXT};
            background: transparent;
            border: none;
        """)
        layout.addWidget(self.value_label)

        self.desc_label = QLabel(label)
        self.desc_label.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 11px;
            color: {C_TEXT3};
            background: transparent;
            border: none;
        """)
        layout.addWidget(self.desc_label)

    def update_value(self, value: str):
        self.value_label.setText(value)


class WordListDialog(QWidget):
    """词库列表窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_page = 1
        self._page_size = 50
        self._total = 0
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        self.setWindowTitle("WordBuddy")
        self.setMinimumSize(780, 580)
        self.resize(920, 620)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setStyleSheet(f"""
            QWidget {{
                background: {C_BG};
                font-family: {FONT};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 16)
        main_layout.setSpacing(14)

        # ── 顶部栏：标题 + 刷新 ──
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        title = QLabel("我的词库")
        title.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 18px;
            font-weight: 700;
            color: {C_TEXT};
        """)
        top_bar.addWidget(title)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedSize(60, 30)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT};
                font-size: 12px;
                color: {C_TEXT2};
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: {C_ACCENT_LIGHT}; color: {C_ACCENT}; }}
        """)
        refresh_btn.clicked.connect(self._load_data)
        top_bar.addWidget(refresh_btn)
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        # ── 统计卡片行 ──
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)

        self.card_total = StatCard("0", "总单词")
        self.card_due = StatCard("0", "今日待复习")
        self.card_mastered = StatCard("0", "已掌握")
        self.card_learning = StatCard("0", "学习中")

        for card in [self.card_total, self.card_due, self.card_mastered, self.card_learning]:
            stats_row.addWidget(card)

        main_layout.addLayout(stats_row)

        # ── 搜索栏 ──
        search_frame = QFrame()
        search_frame.setStyleSheet(f"""
            QFrame {{
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
            }}
        """)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(12, 0, 8, 0)
        search_layout.setSpacing(6)

        search_icon = QLabel("Q")  # 用纯字母代替 emoji
        search_icon.setStyleSheet(f"""
            font-family: {FONT};
            font-size: 13px;
            font-weight: 600;
            color: {C_TEXT3};
            border: none;
            background: transparent;
        """)
        search_layout.addWidget(search_icon)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索单词或释义")
        self.search_input.setFixedHeight(34)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                border: none;
                background: transparent;
                font-family: {FONT};
                font-size: 13px;
                color: {C_TEXT};
            }}
            QLineEdit::placeholder {{ color: {C_TEXT3}; }}
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_input)
        main_layout.addWidget(search_frame)

        # ── 表格 ──
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "单词", "释义", "词性", "阶段", "下次复习", "加入时间"
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
                gridline-color: transparent;
                font-family: {FONT};
                font-size: 13px;
                color: {C_TEXT};
                selection-background-color: {C_ACCENT_LIGHT};
                selection-color: {C_ACCENT};
            }}
            QTableWidget::item {{
                padding: 8px 10px;
                border-bottom: 1px solid #F3F4F6;
            }}
            QTableWidget::item:alternate {{
                background: #FCFCFC;
            }}
            QHeaderView::section {{
                background: {C_CARD};
                color: {C_TEXT3};
                font-family: {FONT};
                font-weight: 600;
                font-size: 11px;
                padding: 10px 10px;
                border: none;
                border-bottom: 1px solid {C_BORDER};
            }}
        """)

        # 列宽设置：单词固定, 释义拉伸, 其余自适应内容
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 150)
        self.table.setRowHeight(0, 42)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        main_layout.addWidget(self.table, 1)

        # ── 底部分页 ──
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        self.total_label = QLabel()
        self.total_label.setStyleSheet(f"font-family: {FONT}; font-size: 12px; color: {C_TEXT3};")
        bottom_row.addWidget(self.total_label)
        bottom_row.addStretch()

        self.prev_btn = QPushButton("< 上一页")
        self.next_btn = QPushButton("下一页 >")
        self.page_label = QLabel()

        for btn in [self.prev_btn, self.next_btn]:
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    font-family: {FONT};
                    font-size: 12px;
                    color: {C_TEXT2};
                    background: {C_CARD};
                    border: 1px solid {C_BORDER};
                    border-radius: 6px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background: {C_ACCENT_LIGHT};
                    color: {C_ACCENT};
                    border-color: {C_ACCENT};
                }}
                QPushButton:disabled {{
                    color: #D1D5DB;
                    background: {C_BG};
                    border-color: #E5E7EB;
                }}
            """)

        self.page_label.setStyleSheet(f"font-family: {FONT}; font-size: 12px; color: {C_TEXT3};")

        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn.clicked.connect(self._next_page)

        bottom_row.addWidget(self.prev_btn)
        bottom_row.addWidget(self.page_label)
        bottom_row.addWidget(self.next_btn)
        main_layout.addLayout(bottom_row)

        # 搜索防抖定时器
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(lambda: self._load_data(reset_page=True))

    # ──────────────────────────────────────────────────────────
    # 数据加载
    # ──────────────────────────────────────────────────────────
    def _on_search_changed(self):
        self._search_timer.start(300)

    def _load_data(self, reset_page: bool = False):
        if reset_page:
            self._current_page = 1

        search = self.search_input.text().strip()
        words, total = word_repo.get_all_words(search, self._current_page, self._page_size)
        self._total = total

        # 更新统计卡片
        stats = word_repo.get_stats()
        self.card_total.update_value(str(stats["total"]))
        self.card_due.update_value(str(stats["due_today"]))
        self.card_mastered.update_value(str(stats["mastered"]))
        self.card_learning.update_value(str(stats["learning"]))

        # 填充表格
        self.table.setRowCount(len(words))
        for row, word in enumerate(words):
            self.table.setRowHeight(row, 42)

            # 单词
            w_item = QTableWidgetItem(word.word)
            w_item.setFont(QFont("Georgia", 12, QFont.Weight.Bold))
            w_item.setForeground(QBrush(QColor(C_TEXT)))
            w_item.setData(Qt.ItemDataRole.UserRole, word.id)
            self.table.setItem(row, 0, w_item)

            # 释义
            definition = word.definition or word.english_definition or ""
            def_item = QTableWidgetItem(definition)
            self.table.setItem(row, 1, def_item)

            # 词性
            pos = word.part_of_speech or ""
            if pos:
                pos_item = QTableWidgetItem(pos)
                pos_item.setForeground(QBrush(QColor(C_TEXT3)))
                pos_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                pos_item = QTableWidgetItem("-")
                pos_item.setForeground(QBrush(QColor("#D1D5DB")))
                pos_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, pos_item)

            # 复习阶段
            stage = word.review_stage
            total_stages = len(REVIEW_STAGE_LABELS)
            if word.is_mastered:
                stage_text = "已掌握"
                stage_color = C_GREEN
            else:
                stage_text = REVIEW_STAGE_LABELS[min(stage, total_stages - 1)]
                stage_color = C_TEXT2
            stage_item = QTableWidgetItem(stage_text)
            stage_item.setForeground(QBrush(QColor(stage_color)))
            stage_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, stage_item)

            # 下次复习（格式化为 MM-DD）
            if word.is_mastered:
                review_text = "-"
                review_color = "#D1D5DB"
            elif word.next_review_date:
                try:
                    dt = word.next_review_date[:10]  # 取 YYYY-MM-DD 部分
                    # 判断是否过期
                    from datetime import date
                    review_date = date.fromisoformat(dt)
                    today = date.today()
                    if review_date <= today:
                        review_text = "今天"
                        review_color = C_ACCENT
                    else:
                        review_text = review_date.strftime("%m-%d")
                        review_color = C_TEXT2
                except (ValueError, IndexError):
                    review_text = word.next_review_date[:10]
                    review_color = C_TEXT2
            else:
                review_text = "-"
                review_color = "#D1D5DB"
            review_item = QTableWidgetItem(review_text)
            review_item.setForeground(QBrush(QColor(review_color)))
            review_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, review_item)

            # 加入时间（格式化为 MM-DD）
            created = word.created_at
            if created:
                try:
                    created_text = created[:10]
                    dt = datetime.fromisoformat(created_text)
                    created_text = dt.strftime("%m-%d")
                except (ValueError, IndexError):
                    created_text = created[:10] if len(created) >= 10 else created
            else:
                created_text = "-"
            date_item = QTableWidgetItem(created_text)
            date_item.setForeground(QBrush(QColor(C_TEXT3)))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, date_item)

        # 更新分页信息
        total_pages = max(1, (total + self._page_size - 1) // self._page_size)
        self.page_label.setText(f"{self._current_page} / {total_pages}")
        self.prev_btn.setEnabled(self._current_page > 1)
        self.next_btn.setEnabled(self._current_page < total_pages)
        self.total_label.setText(f"共 {total} 词")

    # ──────────────────────────────────────────────────────────
    # 分页
    # ──────────────────────────────────────────────────────────
    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._load_data()

    def _next_page(self):
        total_pages = (self._total + self._page_size - 1) // self._page_size
        if self._current_page < total_pages:
            self._current_page += 1
            self._load_data()

    # ──────────────────────────────────────────────────────────
    # 右键菜单
    # ──────────────────────────────────────────────────────────
    def _show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        word_id_item = self.table.item(row, 0)
        if not word_id_item:
            return
        word_id = word_id_item.data(Qt.ItemDataRole.UserRole)
        word_text = word_id_item.text()

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 4px;
                font-family: {FONT};
            }}
            QMenu::item {{
                padding: 6px 16px;
                font-size: 13px;
                color: {C_TEXT};
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: #FEF2F2;
                color: #EF4444;
            }}
        """)
        delete_action = menu.addAction(f"删除「{word_text}」")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == delete_action:
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定要删除单词「{word_text}」及其复习记录吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                word_repo.delete_word(word_id)
                self._load_data()

    # ──────────────────────────────────────────────────────────
    # 事件
    # ──────────────────────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        self._load_data()

    def closeEvent(self, event):
        """点 X 只隐藏，不退出程序"""
        self.hide()
        event.ignore()
