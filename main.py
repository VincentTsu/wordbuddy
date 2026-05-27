"""
WordBuddy 主程序入口
初始化所有模块，启动系统托盘和复习定时器
"""

import sys
import logging
import threading
from typing import Optional

from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from PyQt6.QtCore import QTimer, Qt, QObject, pyqtSignal

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class AppController(QObject):
    """
    应用控制器：协调所有窗口和服务（继承 QObject 防止被 GC）
    托盘图标的操作都通过这里分发
    """

    # 信号（后台线程 → 主线程，Qt 自动投递到主线程事件循环）
    _request_db_close = pyqtSignal()   # 请求主线程关闭 DB
    _request_db_reopen = pyqtSignal()  # 请求主线程重开 DB

    def __init__(self, app: QApplication):
        super().__init__(app)  # 以 app 为 parent，生命周期与 app 一致
        self.app = app
        self._search_dialog = None
        self._review_dialog = None
        self._word_list_dialog = None
        self._settings_dialog = None
        self._review_timer: Optional[QTimer] = None
        self._review_active = False  # 防止重复弹窗
        self._snooze_until: float = 0.0  # 稍后提醒截止时间（time.time()）

        # 后台线程通过这两个信号通知主线程操作 DB
        self._request_db_close.connect(self._on_main_thread_close_db)
        self._request_db_reopen.connect(self._on_main_thread_reopen_db)

        # 同步标志：后台线程用来等待主线程完成关闭
        self._db_close_done = threading.Event()

    def initialize(self):
        """初始化所有模块"""
        # 1. 加载配置
        from app.config import config, get_db_path
        config.load()
        logger.info("配置已加载")

        # 2. 初始化数据库（先用本地已有数据，启动不阻塞 UI）
        from app.db.repository import word_repo
        word_repo.initialize(get_db_path())
        logger.info("数据库已初始化")

        # 3. 注入 post_query_sync 的回调
        import app.services.sync_service as _ss
        _ss._on_download_success = self._request_db_reopen.emit

        # 4. 启动时同步（后台线程，不阻塞 UI）
        threading.Thread(target=self._startup_sync, daemon=True).start()

        # 5. 创建系统托盘
        from app.ui.tray_icon import TrayIcon
        self.tray = TrayIcon(self, parent=None)
        self.tray.show()
        logger.info("系统托盘已启动")

        # 6. 启动复习检查定时器
        self._start_review_timer()

        # 7. 首次启动检查（未配置时引导设置）
        QTimer.singleShot(1500, self._check_first_run)

        logger.info("WordBuddy 已启动，运行在系统托盘")

    # ────────── 同步相关：信号处理（始终在主线程执行）──────────

    def _on_main_thread_close_db(self):
        """主线程：关闭 DB 连接（释放文件锁）"""
        try:
            from app.db.repository import word_repo
            # WAL checkpoint ?????????? DB ??
            if word_repo._conn is not None:
                try:
                    word_repo._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
            word_repo.close()
            logger.info("[主线程] ✅ DB 已关闭，文件锁释放")
        except Exception as e:
            logger.error(f"[主线程] 关闭 DB 失败: {e}", exc_info=True)
        finally:
            # 通知后台线程可以继续了
            self._db_close_done.set()

    def _on_main_thread_reopen_db(self):
        """主线程：重新打开 DB 连接（下载替换完成后调用）"""
        self._reload_db()

    def _reload_db(self):
        """主线程：强制重载数据库连接"""
        try:
            from app.db.repository import word_repo
            from app.config import get_db_path
            word_repo.initialize(get_db_path(), force=True)
            count = word_repo.get_stats()["total"]
            logger.info(f"[主线程] ✅ 数据库重新加载完毕，共 {count} 个单词")
            if hasattr(self, 'tray') and hasattr(self.tray, '_refresh_due_count'):
                self.tray._refresh_due_count()
        except Exception as e:
            logger.error(f"[主线程] ❌ 重新加载数据库失败: {e}", exc_info=True)

    # ────────── 启动同步（后台线程）──────────

    def _startup_sync(self):
        """
        后台线程：启动同步流程（逐词合并策略，无需关闭 DB）。
        流程：先上传本地改动，再合并远端新数据。
        """
        from app.services.sync_service import sync_service
        from app.config import get_db_path
        db_path = get_db_path()

        try:
            # Step 1: 先上传本地改动
            if sync_service.check_need_upload(db_path):
                logger.info("启动同步：本地有未上传的改动，上传中...")
                _, msg_up = sync_service.upload(db_path)
                logger.info(f"启动同步上传结果: {msg_up}")
            else:
                logger.info("启动同步：本地无新改动，跳过上传")

            # Step 2: 合并远端新数据
            if sync_service.check_need_download(db_path):
                logger.info("启动同步：远端有更新，开始合并...")
                merged = sync_service.merge_from_remote(db_path)
                logger.info(f"启动同步合并结果: {merged} 条变更")
            else:
                logger.info("启动同步：远端无变化，跳过合并")

        except Exception as e:
            logger.error(f"启动同步异常: {e}", exc_info=True)

    # ────────── 复习相关 ──────────

    def _check_first_run(self):
        """首次运行引导"""
        from app.config import config
        if not config.is_llm_configured():
            reply = QMessageBox.question(
                None, "欢迎使用 WordBuddy",
                "检测到还未配置 LLM API Key。\n\n请前往设置页面配置 API Key 才能使用查词功能。\n\n是否现在去设置？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.show_settings()

    def _start_review_timer(self):
        """启动艾宾浩斯复习检查定时器"""
        from app.config import config
        interval_ms = config.review_interval_minutes * 60 * 1000

        self._review_timer = QTimer()
        self._review_timer.timeout.connect(self._check_review)
        self._review_timer.start(interval_ms)
        logger.info(f"复习检查定时器已启动，间隔 {config.review_interval_minutes} 分钟")

        # 启动后 3 秒检查一次
        QTimer.singleShot(3000, self._check_review)

    def _check_review(self):
        """检查是否有待复习单词"""
        if self._review_active:
            return
        # 稍后提醒期间跳过
        import time
        if time.time() < self._snooze_until:
            return
        from app.services.review_service import review_service
        next_word = review_service.get_next_review_word()
        if next_word:
            logger.info(f"发现待复习单词: {next_word.word}")
            self._show_review_popup(next_word)

    def _show_review_popup(self, word):
        """弹出复习窗口"""
        self._review_active = True
        from app.ui.review_dialog import ReviewDialog
        if self._review_dialog is None:
            self._review_dialog = ReviewDialog()
            self._review_dialog.review_done.connect(self._on_review_done)
            self._review_dialog.all_done.connect(self._on_all_reviews_done)
            self._review_dialog.closed.connect(self._on_review_closed)
            self._review_dialog.snooze.connect(self._on_review_snoozed)
            self._review_dialog.word_deleted.connect(self._on_word_deleted)

        self._review_dialog.load_word(word)
        self._review_dialog.show()
        self._review_dialog.raise_()

        self.tray.showMessage(
            "WordBuddy — 复习时间",
            f"有新的单词需要复习: {word.word}",
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )

    def _on_review_done(self, word_id: int, result: str):
        """处理单次复习结果：更新托盘计数 + 后台上传同步"""
        from app.services.review_service import review_service
        count = review_service.get_due_count()
        self.tray.update_due_count(count)
        # 每次复习后立即把结果上传到云端，保证跨设备进度一致
        self._post_review_sync()

    def _on_all_reviews_done(self):
        """今日全部复习完成"""
        self._review_active = False
        self.tray.update_due_count(0)
        self.tray.showMessage(
            "WordBuddy",
            "🎉 今日复习全部完成！",
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )
        logger.info("今日复习全部完成")

    def _on_review_closed(self):
        """用户手动关闭复习窗口（点 X）→ 重置状态，定时器下轮正常检查"""
        self._review_active = False
        from app.services.review_service import review_service
        review_service._current_review_word = None
        logger.info("复习窗口被用户关闭，已重置复习状态")

    def _on_review_snoozed(self):
        """用户点击"稍后提醒" → 30 分钟内不再弹窗"""
        import time
        SNOOZE_MINUTES = 30
        self._review_active = False
        self._snooze_until = time.time() + SNOOZE_MINUTES * 60
        from app.services.review_service import review_service
        review_service._current_review_word = None
        self.tray.showMessage(
            "WordBuddy",
            f"⏰ 已暂停，{SNOOZE_MINUTES} 分钟后再提醒",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )
        logger.info(f"复习已推迟 {SNOOZE_MINUTES} 分钟")

    def _on_word_deleted(self, word_id: int):
        """复习中删除单词后更新托盘计数"""
        from app.services.review_service import review_service
        count = review_service.get_due_count()
        self.tray.update_due_count(count)
        logger.info(f"复习中删除单词: word_id={word_id}")

    # ────────── 窗口打开方法 ──────────

    def show_search(self):
        """打开查词窗口"""
        from app.ui.search_dialog import SearchDialog
        if self._search_dialog is None:
            self._search_dialog = SearchDialog()
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()

    def _post_query_sync(self):
        from app.services.sync_service import sync_service
        sync_service.post_query_sync()

    def _post_review_sync(self):
        """复习结果写入后，后台上传到云端（仅上传，不下载，不阻塞 UI）"""
        from app.config import config
        if not config.is_cos_configured():
            return
        import threading
        from app.services.sync_service import sync_service
        from app.config import get_db_path

        def _upload():
            try:
                ok, msg = sync_service.upload(get_db_path())
                logger.info(f"复习后同步上传: {msg}")
            except Exception as e:
                logger.warning(f"复习后同步上传失败: {e}")

        threading.Thread(target=_upload, daemon=True).start()

    def start_review(self):
        """手动触发复习（今日到期的单词）"""
        from app.services.review_service import review_service
        review_service.reset_daily_queue()
        next_word = review_service.get_next_review_word()
        if next_word:
            self._show_review_popup(next_word)
        else:
            self.tray.showMessage(
                "WordBuddy",
                "✅ 今日没有待复习的单词",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

    def start_manual_review(self):
        """手动复习：随机推送 10 个未掌握单词"""
        from app.services.review_service import review_service
        words = review_service.load_random_words(10)
        if words:
            self._show_review_popup(words[0])
        else:
            self.tray.showMessage(
                "WordBuddy",
                "词库中没有可复习的单词",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

    def show_word_list(self):
        """打开词库列表"""
        from app.ui.word_list_dialog import WordListDialog
        if self._word_list_dialog is None:
            self._word_list_dialog = WordListDialog()
        self._word_list_dialog.show()
        self._word_list_dialog.raise_()
        self._word_list_dialog.activateWindow()

    def show_settings(self):
        """打开设置窗口"""
        from app.ui.settings_dialog import SettingsDialog
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog()
            self._settings_dialog.settings_saved.connect(self._on_settings_saved)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _on_settings_saved(self):
        """设置保存后重启定时器"""
        if self._review_timer:
            self._review_timer.stop()
        self._start_review_timer()

    def force_download(self):
        """强制从云端恢复词库（逐词合并，保留本地进度更高的词）"""
        from app.services.sync_service import sync_service
        from app.db.repository import word_repo

        reply = QMessageBox.question(
            None, "WordBuddy — 从云端恢复",
            "确定要从云端恢复词库吗？\n\n云端词库将与本地逐词合并，"
            "复习进度更高的版本会被保留。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        logger.info("[强制恢复] 开始从云端合并...")

        try:
            before_count = word_repo.get_stats()["total"]
        except Exception:
            before_count = -1

        ok, msg = sync_service.sync_now(force=True)

        try:
            after_count = word_repo.get_stats()["total"]
        except Exception:
            after_count = -1

        logger.info(f"[强制恢复] 完成: ok={ok}, msg={msg}, 之前={before_count}词, 现在={after_count}词")

        icon = QSystemTrayIcon.MessageIcon.Information if ok else QSystemTrayIcon.MessageIcon.Warning
        detail = msg
        if before_count >= 0 and after_count >= 0:
            detail += f"（{before_count} → {after_count} 词）"
        self.tray.showMessage("WordBuddy — 云端恢复", detail, icon, 3000)

    def sync_now(self):
        """?????????????????"""
        from app.services.sync_service import sync_service
        from app.db.repository import word_repo

        logger.info("[????] ??...")

        try:
            before_count = word_repo.get_stats()["total"]
        except Exception:
            before_count = -1

        ok, msg = sync_service.sync_now(force=True)  # Always pull cloud to catch phone changes

        try:
            after_count = word_repo.get_stats()["total"]
        except Exception:
            after_count = -1

        logger.info(f"[????] ??: ok={ok}, msg={msg}, ??={before_count}?, ??={after_count}?")

        icon = QSystemTrayIcon.MessageIcon.Information if ok else QSystemTrayIcon.MessageIcon.Warning
        detail = str(msg)
        if before_count >= 0 and after_count >= 0 and before_count != after_count:
            detail += f"?{before_count} ? {after_count} ??"
        self.tray.showMessage("WordBuddy ? ??", detail, icon, 3000)
def main():
    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("WordBuddy")
    app.setApplicationVersion("1.0.0")
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，保持托盘

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "WordBuddy", "系统不支持托盘图标，无法运行！")
        sys.exit(1)

    controller = AppController(app)
    controller.initialize()
    app._controller = controller  # 防止 GC 提前回收 controller

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
