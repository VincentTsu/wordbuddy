"""
WordBuddy 系统托盘图标
常驻系统托盘，右键菜单管理所有功能入口
"""

import logging
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QBrush
from PyQt6.QtCore import Qt, QTimer, QSize

from app.services.review_service import review_service

logger = logging.getLogger(__name__)


def _create_tray_icon(badge_count: int = 0) -> QIcon:
    """动态生成托盘图标（带数字徽章）"""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 主图标背景圆
    painter.setBrush(QBrush(QColor("#4A90D9")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)

    # 书本 emoji 简化图标：白色 "W" 字母
    painter.setPen(QColor("white"))
    font = QFont("Microsoft YaHei UI", 28, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "W")

    # 徽章（待复习数量）
    if badge_count > 0:
        badge_text = str(min(badge_count, 99))
        painter.setBrush(QBrush(QColor("#FF4D4F")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(36, 0, 28, 28)

        painter.setPen(QColor("white"))
        badge_font = QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold)
        painter.setFont(badge_font)
        painter.drawText(36, 0, 28, 28, Qt.AlignmentFlag.AlignCenter, badge_text)

    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    """系统托盘图标和菜单"""

    def __init__(self, app_controller, parent=None):
        super().__init__(parent)
        self.app_controller = app_controller
        self._due_count = 0

        self.setIcon(_create_tray_icon(0))
        self.setToolTip("WordBuddy — 英语单词学习助手")

        self._build_menu()

        self.activated.connect(self._on_activated)

        # 定时刷新待复习数量（每分钟）
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_due_count)
        self._refresh_timer.start(60_000)

        # 启动时刷新一次
        QTimer.singleShot(2000, self._refresh_due_count)

    def _build_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: white;
                border: 1px solid #E0E0E0;
                border-radius: 10px;
                padding: 6px 4px;
                font-family: 'Microsoft YaHei UI';
            }
            QMenu::item {
                padding: 9px 22px;
                font-size: 13px;
                color: #333;
                border-radius: 6px;
                min-width: 180px;
            }
            QMenu::item:selected {
                background: #F0F7FF;
                color: #2C6AA0;
            }
            QMenu::separator {
                height: 1px;
                background: #F0F0F0;
                margin: 4px 10px;
            }
        """)

        # 标题（不可点击）
        header_action = menu.addAction("📖  WordBuddy")
        header_action.setEnabled(False)
        header_font = header_action.font()
        header_font.setBold(True)
        header_action.setFont(header_font)

        menu.addSeparator()

        self.search_action = menu.addAction("🔍  查词")
        self.search_action.triggered.connect(self.app_controller.show_search)

        self.review_action = menu.addAction("🧠  开始复习（0 个待复习）")
        self.review_action.triggered.connect(self.app_controller.start_review)

        self.manual_review_action = menu.addAction("📝  随机复习 10 词")
        self.manual_review_action.triggered.connect(self.app_controller.start_manual_review)

        self.wordlist_action = menu.addAction("📚  我的词库")
        self.wordlist_action.triggered.connect(self.app_controller.show_word_list)

        menu.addSeparator()

        self.sync_action = menu.addAction("☁️  立即同步")
        self.sync_action.triggered.connect(self.app_controller.sync_now)

        self.force_download_action = menu.addAction("⬇️  从云端恢复词库")
        self.force_download_action.triggered.connect(self.app_controller.force_download)

        settings_action = menu.addAction("⚙️  设置")
        settings_action.triggered.connect(self.app_controller.show_settings)

        menu.addSeparator()

        quit_action = menu.addAction("✕  退出")
        quit_action.triggered.connect(QApplication.quit)

        self.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.app_controller.show_search()

    def _refresh_due_count(self):
        try:
            self._due_count = review_service.get_due_count()
            self.setIcon(_create_tray_icon(self._due_count))
            self.review_action.setText(f"🧠  开始复习（{self._due_count} 个待复习）")
            self.setToolTip(
                f"WordBuddy\n今日待复习: {self._due_count} 个"
                if self._due_count > 0 else "WordBuddy — 英语单词学习助手"
            )
        except Exception as e:
            logger.debug(f"刷新待复习数量失败: {e}")

    def update_due_count(self, count: int):
        self._due_count = count
        self.setIcon(_create_tray_icon(count))
        self.review_action.setText(f"🧠  开始复习（{count} 个待复习）")
