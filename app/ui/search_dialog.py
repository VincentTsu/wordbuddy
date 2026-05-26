"""
WordBuddy 查词窗口
极简设计：统一字体，无多余装饰
"""

import logging
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence, QColor, QAction

from app.services.llm_service import llm_service, LLMError
from app.services.sync_service import sync_service
from app.db.repository import word_repo

logger = logging.getLogger(__name__)

# ── 统一配色 & 字体 ──
C_BG = "#FAFAFA"
C_TEXT = "#2C2C2C"
C_TEXT2 = "#777777"
C_BORDER = "#E8E8E8"
C_PRIMARY = "#4A90D9"

# 字体：英文用 Inter（清晰现代），中文用微软雅黑
FONT_FAMILY = "'Inter', 'Segoe UI', 'Microsoft YaHei', sans-serif"
FONT_TITLE = 24      # 单词标题
FONT_SECTION = 13    # 小标题（例句/近义词/备注标签）
FONT_BODY = 15       # 正文（所有解释内容）


class LLMWorker(QThread):
    result_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str, str)
    progress_update = pyqtSignal(str)

    def __init__(self, word: str):
        super().__init__()
        self.word = word

    def run(self):
        try:
            result = llm_service.query_word(
                self.word,
                on_progress=lambda msg: self.progress_update.emit(msg),
                on_stream=None,
            )
            self.result_ready.emit(result)
        except LLMError as e:
            self.error_occurred.emit(str(e), e.error_type)
        except Exception as e:
            self.error_occurred.emit(f"未知错误: {e}", "unknown")


class SearchDialog(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[LLMWorker] = None
        self._drag_pos = None
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("WordBuddy")
        self.setObjectName("searchRoot")
        self.setMinimumSize(480, 480)
        self.resize(520, 580)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # 外层布局
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 自定义标题栏 ──
        self._title_bar = QWidget()
        self._title_bar.setFixedHeight(36)
        self._title_bar.setStyleSheet(f"""
            QWidget#titleBar {{
                background: #F2F2F2;
                border-bottom: 1px solid {C_BORDER};
            }}
        """)
        self._title_bar.setObjectName("titleBar")

        tb_layout = QHBoxLayout(self._title_bar)
        tb_layout.setContentsMargins(12, 0, 4, 0)
        tb_layout.setSpacing(0)

        # 拖拽区域
        tb_layout.addStretch()

        # 置顶按钮
        self.pin_btn = QPushButton("📌")
        self.pin_btn.setFixedSize(36, 28)
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("置顶窗口")
        self.pin_btn.setObjectName("titleBtn")
        self.pin_btn.clicked.connect(self._toggle_pin)
        tb_layout.addWidget(self.pin_btn)

        # 最小化按钮
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(36, 28)
        self.min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.min_btn.setToolTip("最小化")
        self.min_btn.setObjectName("titleBtn")
        self.min_btn.clicked.connect(self.showMinimized)
        tb_layout.addWidget(self.min_btn)

        # 关闭按钮
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(36, 28)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setToolTip("关闭")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.clicked.connect(self.hide)
        tb_layout.addWidget(self.close_btn)

        outer.addWidget(self._title_bar)

        # ── 内容区 ──
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 16, 28, 20)
        layout.setSpacing(14)

        # 搜索栏
        row = QHBoxLayout()
        row.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索单词或词组...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(40)
        self.search_input.returnPressed.connect(self._on_search)
        row.addWidget(self.search_input, 1)

        self.search_btn = QPushButton("查询")
        self.search_btn.setFixedSize(68, 40)
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_btn.clicked.connect(self._on_search)
        row.addWidget(self.search_btn)

        layout.addLayout(row)

        # 状态行
        status_row = QHBoxLayout()
        self.stats_label = QLabel()
        status_row.addWidget(self.stats_label)
        status_row.addStretch()
        self.status_label = QLabel("回车查询")
        status_row.addWidget(self.status_label)
        layout.addLayout(status_row)

        # 结果区
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.result_widget = QWidget()
        self.result_layout = QVBoxLayout(self.result_widget)
        self.result_layout.setSpacing(8)
        self.result_layout.setContentsMargins(0, 8, 0, 0)
        self.result_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.result_layout.addStretch()

        self.scroll_area.setWidget(self.result_widget)
        layout.addWidget(self.scroll_area)

        # 全局样式
        self.setStyleSheet(f"""
            QWidget#searchRoot {{
                background: {C_BG};
                font-family: {FONT_FAMILY};
                font-size: {FONT_BODY}px;
                color: {C_TEXT};
            }}
            QLineEdit {{
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 0 14px;
                font-size: {FONT_BODY}px;
                font-family: {FONT_FAMILY};
                color: {C_TEXT};
                background: white;
            }}
            QLineEdit:focus {{
                border-color: {C_PRIMARY};
            }}
            QLineEdit::placeholder {{
                color: #BBB;
            }}
            QPushButton {{
                background: {C_PRIMARY};
                color: white;
                border: none;
                border-radius: 8px;
                font-size: {FONT_BODY}px;
                font-family: {FONT_FAMILY};
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background: #3A7BC8;
            }}
            QPushButton:pressed {{
                background: #2D6AB8;
            }}
            QPushButton:disabled {{
                background: #C0C0C0;
            }}
            QLabel {{
                color: {C_TEXT};
                border: none;
                background: transparent;
                font-family: {FONT_FAMILY};
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
                background: transparent;
            }}
            QPushButton#pinBtn {{
                background: #F0F0F0;
                color: {C_TEXT2};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                font-size: 12px;
                font-family: {FONT_FAMILY};
            }}
            QPushButton#pinBtn:hover {{
                background: #E4E4E4;
            }}
            QPushButton#pinBtn:checked {{
                background: {C_PRIMARY};
                color: white;
                border-color: {C_PRIMARY};
            }}
            QPushButton#titleBtn {{
                background: transparent;
                color: {C_TEXT2};
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton#titleBtn:hover {{
                background: #E0E0E0;
            }}
            QPushButton#titleBtn:checked {{
                background: {C_PRIMARY};
                color: white;
            }}
            QPushButton#closeBtn {{
                background: transparent;
                color: {C_TEXT2};
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton#closeBtn:hover {{
                background: #E74C3C;
                color: white;
            }}
        """)

        self._update_stats()

        # Esc 关闭
        esc = QAction(self)
        esc.setShortcut(QKeySequence("Escape"))
        esc.triggered.connect(self.hide)
        self.addAction(esc)

        outer.addWidget(content)

        # 标题栏拖拽
        self._title_bar.mousePressEvent = self._title_bar_mouse_press
        self._title_bar.mouseMoveEvent = self._title_bar_mouse_move
        self._title_bar.mouseReleaseEvent = self._title_bar_mouse_release

    def _update_stats(self):
        try:
            stats = word_repo.get_stats()
            self.stats_label.setText(f"{stats['total']} 词 | 待复习 {stats['due_today']}")
        except Exception:
            pass

    def _on_search(self):
        word = self.search_input.text().strip()
        if not word:
            return
        if self._worker and self._worker.isRunning():
            return

        self._clear_results()
        self.search_btn.setEnabled(False)
        self.search_input.setEnabled(False)
        self.status_label.setStyleSheet(f"color: {C_PRIMARY}; font-size: {FONT_SECTION}px;")
        self.status_label.setText("查询中...")

        self._worker = LLMWorker(word)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.progress_update.connect(lambda m: self.status_label.setText(m))
        self._worker.start()

    def _on_result(self, data: Dict[str, Any]):
        self.search_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.status_label.setStyleSheet(f"color: #27AE60; font-size: {FONT_SECTION}px;")
        self.status_label.setText("已保存")

        self._render_result(data)

        try:
            word_repo.add_or_update_word(data)
            self._update_stats()
            # 保存成功后，后台异步上传到 COS（不阻塞 UI）
            sync_service.post_query_sync()
        except Exception as e:
            logger.error(f"保存单词失败: {e}")

    def _on_error(self, msg: str, error_type: str):
        self.search_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.status_label.setStyleSheet(f"color: #E74C3C; font-size: {FONT_SECTION}px;")
        self.status_label.setText(msg)

    def _clear_results(self):
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.result_layout.addStretch()

    def _section_title(self, text: str) -> QLabel:
        """小标题：13px 加粗灰色"""
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: {FONT_SECTION}px; font-weight: bold; color: {C_TEXT2}; "
            f"font-family: {FONT_FAMILY}; border: none; background: transparent; "
            f"margin-top: 2px;"
        )
        return lbl

    def _body(self, text: str) -> QLabel:
        """正文：15px 正文色，统一大小"""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"font-size: {FONT_BODY}px; color: {C_TEXT}; "
            f"font-family: {FONT_FAMILY}; border: none; background: transparent;"
        )
        return lbl

    def _render_result(self, data: Dict[str, Any]):
        pos = self.result_layout.count() - 1  # stretch 之前的位置

        # ── 单词标题 ──
        word_text = data.get("word", "")
        phonetic = data.get("phonetic", "")
        part_of_speech = data.get("part_of_speech", "")

        title_row = QWidget()
        title_lay = QVBoxLayout(title_row)
        title_lay.setContentsMargins(0, 0, 0, 0)
        title_lay.setSpacing(2)

        word_lbl = QLabel(word_text)
        word_lbl.setStyleSheet(
            f"font-size: {FONT_TITLE}px; font-weight: bold; color: {C_TEXT}; "
            f"font-family: {FONT_FAMILY}; border: none; background: transparent;"
        )
        title_lay.addWidget(word_lbl)

        sub_parts = [p for p in [phonetic, part_of_speech] if p]
        if sub_parts:
            sub_lbl = QLabel("  ".join(sub_parts))
            sub_lbl.setStyleSheet(
                f"font-size: {FONT_BODY}px; color: {C_TEXT2}; "
                f"font-family: {FONT_FAMILY}; border: none; background: transparent;"
            )
            title_lay.addWidget(sub_lbl)

        self.result_layout.insertWidget(pos, title_row)
        pos += 1

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {C_BORDER}; max-height: 1px; border: none; margin: 8px 0;")
        self.result_layout.insertWidget(pos, sep)
        pos += 1

        # ── 以下全部统一为：小标题 + 正文，两种字体 ──

        # 释义
        if data.get("definition"):
            self.result_layout.insertWidget(pos, self._section_title("释义"))
            pos += 1
            self.result_layout.insertWidget(pos, self._body(data["definition"]))
            pos += 1

        # 英文释义
        if data.get("english_definition"):
            self.result_layout.insertWidget(pos, self._section_title("English"))
            pos += 1
            self.result_layout.insertWidget(pos, self._body(data["english_definition"]))
            pos += 1

        # 例句
        examples = data.get("examples", [])
        if examples:
            self.result_layout.insertWidget(pos, self._section_title("例句"))
            pos += 1
            for ex in examples[:3]:
                self.result_layout.insertWidget(pos, self._body(f"  {ex}"))
                pos += 1

        # 近义词
        synonyms = data.get("synonyms", [])
        if synonyms:
            self.result_layout.insertWidget(pos, self._section_title("近义词"))
            pos += 1
            self.result_layout.insertWidget(pos, self._body("  ".join(synonyms[:6])))
            pos += 1

        # 备注
        if data.get("notes"):
            self.result_layout.insertWidget(pos, self._section_title("备注"))
            pos += 1
            self.result_layout.insertWidget(pos, self._body(data["notes"]))

    def _toggle_pin(self):
        if self.pin_btn.isChecked():
            self.setWindowFlags(
                self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
            )
            self.pin_btn.setText("📌")
            self.pin_btn.setToolTip("取消置顶")
        else:
            self.setWindowFlags(
                self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint
            )
            self.pin_btn.setText("📌")
            self.pin_btn.setToolTip("置顶窗口")
        self.show()

    def _title_bar_mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_bar_mouse_move(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def _title_bar_mouse_release(self, event):
        self._drag_pos = None

    def showEvent(self, event):
        super().showEvent(event)
        self.search_input.setFocus()
        self._update_stats()

    def hideEvent(self, event):
        super().hideEvent(event)
        # 关闭时自动取消置顶，下次打开干净状态
        if self.pin_btn.isChecked():
            self.pin_btn.setChecked(False)
            self.setWindowFlags(
                self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint
            )

    def closeEvent(self, event):
        """点 X 只隐藏，不退出程序"""
        self.hide()
        event.ignore()
