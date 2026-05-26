"""
WordBuddy 设置窗口
LLM API 配置 + COS 同步配置 + 通用设置
"""

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QLineEdit, QTabWidget, QFormLayout,
    QSpinBox, QCheckBox, QMessageBox, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from app.config import config

logger = logging.getLogger(__name__)


class TestWorker(QThread):
    """后台测试连接"""
    done = pyqtSignal(bool, str)

    def __init__(self, test_type: str):
        super().__init__()
        self.test_type = test_type

    def run(self):
        if self.test_type == "llm":
            from app.services.llm_service import llm_service
            ok, msg = llm_service.test_connection()
        else:
            from app.services.sync_service import sync_service
            ok, msg = sync_service.test_connection()
        self.done.emit(ok, msg)


def _make_input(placeholder: str = "", is_password: bool = False, width: int = 300) -> QLineEdit:
    inp = QLineEdit()
    inp.setPlaceholderText(placeholder)
    inp.setFixedWidth(width)
    inp.setFixedHeight(36)
    if is_password:
        inp.setEchoMode(QLineEdit.EchoMode.Password)
    inp.setStyleSheet("""
        QLineEdit {
            border: 1.5px solid #E8E8E8;
            border-radius: 8px;
            padding: 0 12px;
            font-size: 13px;
            color: #333;
            background: white;
        }
        QLineEdit:focus {
            border-color: #4A90D9;
        }
    """)
    return inp


def _make_primary_btn(text: str, width: int = 120) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(36)
    btn.setFixedWidth(width)
    btn.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #4A90D9, stop:1 #357ABD);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
        }
        QPushButton:hover { background: #357ABD; }
        QPushButton:pressed { background: #2C6AA0; }
        QPushButton:disabled { background: #C8D8EA; }
    """)
    return btn


def _make_secondary_btn(text: str, width: int = 120) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(36)
    btn.setFixedWidth(width)
    btn.setStyleSheet("""
        QPushButton {
            background: white;
            border: 1.5px solid #4A90D9;
            color: #4A90D9;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
        }
        QPushButton:hover { background: #F0F7FF; }
        QPushButton:pressed { background: #E0EFFF; }
        QPushButton:disabled { color: #AAA; border-color: #CCC; }
    """)
    return btn


class SettingsDialog(QWidget):
    """设置窗口"""

    settings_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._test_worker = None
        self._init_ui()
        self._load_values()

    def _init_ui(self):
        self.setWindowTitle("WordBuddy — 设置")
        self.setFixedSize(540, 520)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet("""
            QDialog {
                background: #F5F5F5;
                font-family: 'Microsoft YaHei UI';
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 20)
        main_layout.setSpacing(16)

        # 标题
        title = QLabel("⚙️ 设置")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #2C6AA0;")
        main_layout.addWidget(title)

        # 标签页
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                background: white;
                border: 1px solid #E8E8E8;
                border-radius: 12px;
                padding: 16px;
            }
            QTabBar::tab {
                background: transparent;
                color: #888;
                padding: 8px 20px;
                font-size: 13px;
                border: none;
            }
            QTabBar::tab:selected {
                color: #4A90D9;
                font-weight: 600;
                border-bottom: 2px solid #4A90D9;
            }
            QTabBar::tab:hover { color: #357ABD; }
        """)

        # ── Tab 1: LLM 配置 ──
        llm_tab = QWidget()
        llm_layout = QVBoxLayout(llm_tab)
        llm_layout.setSpacing(16)
        llm_layout.setContentsMargins(8, 16, 8, 8)

        form1 = QFormLayout()
        form1.setSpacing(12)
        form1.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.llm_base_url = _make_input("https://api.deepseek.com/v1", width=320)
        self.llm_api_key = _make_input("sk-...", is_password=True, width=320)
        self.llm_model = _make_input("deepseek-chat", width=320)

        form1.addRow(self._label("Base URL"), self.llm_base_url)
        form1.addRow(self._label("API Key"), self.llm_api_key)
        form1.addRow(self._label("Model"), self.llm_model)
        llm_layout.addLayout(form1)

        hint = QLabel("💡 支持 OpenAI / DeepSeek / 通义千问等任意兼容接口")
        hint.setStyleSheet("color: #999; font-size: 12px;")
        llm_layout.addWidget(hint)
        llm_layout.addSpacing(4)

        self.llm_test_btn = _make_secondary_btn("🔗 测试连接", 120)
        self.llm_test_btn.clicked.connect(lambda: self._test_connection("llm"))
        self.llm_test_result = QLabel()
        self.llm_test_result.setStyleSheet("font-size: 12px;")

        test_row = QHBoxLayout()
        test_row.addWidget(self.llm_test_btn)
        test_row.addWidget(self.llm_test_result)
        test_row.addStretch()
        llm_layout.addLayout(test_row)
        llm_layout.addStretch()

        # ── Tab 2: COS 配置 ──
        cos_tab = QWidget()
        cos_layout = QVBoxLayout(cos_tab)
        cos_layout.setSpacing(16)
        cos_layout.setContentsMargins(8, 16, 8, 8)

        form2 = QFormLayout()
        form2.setSpacing(12)
        form2.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cos_secret_id = _make_input("SecretId", width=320)
        self.cos_secret_key = _make_input("SecretKey", is_password=True, width=320)
        self.cos_bucket = _make_input("your-bucket-1234567890", width=320)

        self.cos_region = QComboBox()
        self.cos_region.addItems([
            "ap-guangzhou", "ap-beijing", "ap-shanghai",
            "ap-chengdu", "ap-hong-kong", "ap-singapore"
        ])
        self.cos_region.setFixedHeight(36)
        self.cos_region.setFixedWidth(320)
        self.cos_region.setStyleSheet("""
            QComboBox {
                border: 1.5px solid #E8E8E8;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 13px;
                color: #333;
                background: white;
            }
            QComboBox:focus { border-color: #4A90D9; }
            QComboBox::drop-down { border: none; width: 24px; }
        """)

        form2.addRow(self._label("SecretId"), self.cos_secret_id)
        form2.addRow(self._label("SecretKey"), self.cos_secret_key)
        form2.addRow(self._label("Bucket"), self.cos_bucket)
        form2.addRow(self._label("Region"), self.cos_region)
        cos_layout.addLayout(form2)

        cos_hint = QLabel("💡 词库会同步至 COS，实现公司/家里电脑数据共享")
        cos_hint.setStyleSheet("color: #999; font-size: 12px;")
        cos_layout.addWidget(cos_hint)
        cos_layout.addSpacing(4)

        self.cos_test_btn = _make_secondary_btn("🔗 测试连接", 120)
        self.cos_test_btn.clicked.connect(lambda: self._test_connection("cos"))
        self.cos_test_result = QLabel()
        self.cos_test_result.setStyleSheet("font-size: 12px;")

        cos_test_row = QHBoxLayout()
        cos_test_row.addWidget(self.cos_test_btn)
        cos_test_row.addWidget(self.cos_test_result)
        cos_test_row.addStretch()
        cos_layout.addLayout(cos_test_row)

        manual_sync_btn = _make_primary_btn("☁️ 立即同步", 120)
        manual_sync_btn.clicked.connect(self._manual_sync)
        cos_layout.addWidget(manual_sync_btn)
        cos_layout.addStretch()

        # ── Tab 3: 通用设置 ──
        general_tab = QWidget()
        gen_layout = QVBoxLayout(general_tab)
        gen_layout.setSpacing(16)
        gen_layout.setContentsMargins(8, 16, 8, 8)

        form3 = QFormLayout()
        form3.setSpacing(12)
        form3.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.review_interval = QSpinBox()
        self.review_interval.setRange(5, 240)
        self.review_interval.setSuffix(" 分钟")
        self.review_interval.setFixedHeight(36)
        self.review_interval.setFixedWidth(140)
        self.review_interval.setStyleSheet("""
            QSpinBox {
                border: 1.5px solid #E8E8E8;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 13px;
                color: #333;
                background: white;
            }
            QSpinBox:focus { border-color: #4A90D9; }
        """)

        self.auto_start = QCheckBox("开机自动启动")
        self.auto_start.setStyleSheet("font-size: 13px; color: #333;")

        self.fill_ratio = QSpinBox()
        self.fill_ratio.setRange(0, 100)
        self.fill_ratio.setSuffix(" %")
        self.fill_ratio.setFixedHeight(36)
        self.fill_ratio.setFixedWidth(140)
        self.fill_ratio.setStyleSheet("""
            QSpinBox {
                border: 1.5px solid #E8E8E8;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 13px;
                color: #333;
                background: white;
            }
            QSpinBox:focus { border-color: #4A90D9; }
        """)

        form3.addRow(self._label("复习检查间隔"), self.review_interval)
        form3.addRow(self._label("开机启动"), self.auto_start)
        form3.addRow(self._label("填空题比例"), self.fill_ratio)
        gen_layout.addLayout(form3)

        fill_hint = QLabel("💡 填空题会随机出现，要求拼写单词，训练输出能力\n0% = 纯认词模式，100% = 全部填空")
        fill_hint.setStyleSheet("color: #999; font-size: 12px;")
        gen_layout.addWidget(fill_hint)
        gen_layout.addStretch()

        self.tabs.addTab(llm_tab, "🤖 LLM 配置")
        self.tabs.addTab(cos_tab, "☁️ 云同步")
        self.tabs.addTab(general_tab, "⚙️ 通用设置")
        main_layout.addWidget(self.tabs)

        # ── 底部按钮 ──
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()

        cancel_btn = _make_secondary_btn("取消", 90)
        cancel_btn.clicked.connect(self.close)

        save_btn = _make_primary_btn("保存", 90)
        save_btn.clicked.connect(self._save)

        bottom_row.addWidget(cancel_btn)
        bottom_row.addSpacing(8)
        bottom_row.addWidget(save_btn)
        main_layout.addLayout(bottom_row)

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 13px; color: #555; min-width: 100px;")
        return label

    def _load_values(self):
        self.llm_base_url.setText(config.llm_base_url)
        self.llm_api_key.setText(config.llm_api_key)
        self.llm_model.setText(config.llm_model)
        self.cos_secret_id.setText(config.cos_secret_id)
        self.cos_secret_key.setText(config.cos_secret_key)
        self.cos_bucket.setText(config.cos_bucket)
        idx = self.cos_region.findText(config.cos_region)
        if idx >= 0:
            self.cos_region.setCurrentIndex(idx)
        self.review_interval.setValue(config.review_interval_minutes)
        self.auto_start.setChecked(config.get("settings", "auto_start", default=False))
        self.fill_ratio.setValue(config.fill_ratio)

    def _save(self):
        config.set("llm", "base_url", self.llm_base_url.text().strip())
        config.set("llm", "api_key", self.llm_api_key.text().strip())
        config.set("llm", "model", self.llm_model.text().strip())
        config.set("cos", "secret_id", self.cos_secret_id.text().strip())
        config.set("cos", "secret_key", self.cos_secret_key.text().strip())
        config.set("cos", "bucket", self.cos_bucket.text().strip())
        config.set("cos", "region", self.cos_region.currentText())
        config.set("settings", "review_interval_minutes", self.review_interval.value())
        config.set("settings", "auto_start", self.auto_start.isChecked())
        config.set("settings", "fill_ratio", self.fill_ratio.value())
        config.save()

        # 处理开机自启动
        self._set_auto_start(self.auto_start.isChecked())

        self.settings_saved.emit()
        QMessageBox.information(self, "保存成功", "设置已保存！")
        self.close()

    def _set_auto_start(self, enable: bool):
        """设置开机自启动（Windows 注册表）"""
        try:
            import sys, winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "WordBuddy"
            exe_path = sys.executable

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
            if enable:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            logger.warning(f"设置开机自启动失败: {e}")

    def _test_connection(self, test_type: str):
        if self._test_worker and self._test_worker.isRunning():
            return

        # 临时应用配置（测试前不保存）
        if test_type == "llm":
            config.set("llm", "base_url", self.llm_base_url.text().strip())
            config.set("llm", "api_key", self.llm_api_key.text().strip())
            config.set("llm", "model", self.llm_model.text().strip())
            btn, result_label = self.llm_test_btn, self.llm_test_result
        else:
            config.set("cos", "secret_id", self.cos_secret_id.text().strip())
            config.set("cos", "secret_key", self.cos_secret_key.text().strip())
            config.set("cos", "bucket", self.cos_bucket.text().strip())
            config.set("cos", "region", self.cos_region.currentText())
            btn, result_label = self.cos_test_btn, self.cos_test_result

        btn.setEnabled(False)
        result_label.setText("⏳ 测试中...")
        result_label.setStyleSheet("color: #4A90D9; font-size: 12px;")

        self._test_worker = TestWorker(test_type)
        self._test_worker.done.connect(
            lambda ok, msg: self._on_test_done(ok, msg, btn, result_label)
        )
        self._test_worker.start()

    def _on_test_done(self, ok: bool, msg: str, btn, result_label):
        btn.setEnabled(True)
        if ok:
            result_label.setText(f"✅ {msg}")
            result_label.setStyleSheet("color: #52C41A; font-size: 12px;")
        else:
            result_label.setText(f"❌ {msg}")
            result_label.setStyleSheet("color: #FF4D4F; font-size: 12px;")

    def _manual_sync(self):
        from app.services.sync_service import sync_service
        # 先保存配置
        config.set("cos", "secret_id", self.cos_secret_id.text().strip())
        config.set("cos", "secret_key", self.cos_secret_key.text().strip())
        config.set("cos", "bucket", self.cos_bucket.text().strip())
        config.set("cos", "region", self.cos_region.currentText())

        ok, msg = sync_service.sync_now()
        if ok:
            QMessageBox.information(self, "同步完成", msg)
        else:
            QMessageBox.warning(self, "同步失败", msg)

    def closeEvent(self, event):
        """点 X 只隐藏，不退出程序"""
        self.hide()
        event.ignore()
