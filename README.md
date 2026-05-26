# WordBuddy — 英语单词学习助手

跨平台英语单词学习工具，支持桌面端（Windows）+ Android 手机端，LLM 智能查词、艾宾浩斯复习、腾讯云 COS 双向同步。

---

## 功能特性

- **LLM 智能查词** — 调用 DeepSeek 等 AI 获取音标、词性、释义、例句、同义词
- **艾宾浩斯复习** — 遗忘曲线间隔（1→2→4→7→15→30 天），自动提醒复习
- **云同步** — 腾讯云 COS 双向逐词合并，桌面端 / 手机端词库和复习进度自动同步
- **词库管理** — 搜索过滤、复习统计、单词详情
- **桌面端** — 系统托盘常驻，不占任务栏，右键菜单快速操作
- **Android 端** — Material Design 3 界面，查词 / 复习 / 词库 / 同步全部功能

---

## 桌面端（Windows）

### 安装运行

```bash
pip install -r requirements.txt
python main.py
```

或双击 `启动WordBuddy.bat`。

### 打包为 .exe

```bash
pip install pyinstaller
pyinstaller build/word_buddy.spec
```

### 首次配置

1. 右键托盘图标 → **设置**
2. LLM 配置：填入 API Key
   - Base URL: `https://api.deepseek.com/v1`
   - Model: `deepseek-chat`
3. 云同步：填入腾讯云 COS 的 SecretId / SecretKey / Bucket / Region
4. 保存后即可使用

---

## Android 端

### 编译

用 Android Studio 打开 `mobile-android/` 或在命令行：

```bash
cd mobile-android
./gradlew assembleDebug
```

APK 输出：`app/build/outputs/apk/debug/app-debug.apk`

### 初始配置

App 首次启动时从 `assets/credentials.properties` 读取默认 API Key 和 COS 配置。将此文件放入 `app/src/main/assets/`（参考同目录下的 `.example.properties` 模板）。未提供文件时需在 App 设置页手动填入。

---

## 云同步机制

| 特性 | 说明 |
|------|------|
| 策略 | 逐词合并，不覆盖整库 |
| 冲突处理 | 优先保留复习进度更新的一方 |
| 删除 | 上传优先 + 删除追踪，防止同步撤销删除 |
| 触发时机 | 启动时、查词后、复习后（桌面端 + 手机端均自动触发） |

---

## 同步密钥获取

- 腾讯云 COS：[控制台](https://console.cloud.tencent.com/cam/capi) → 密钥管理 → 新建密钥
- DeepSeek API Key：[platform.deepseek.com](https://platform.deepseek.com/api_keys)

---

## 推荐 LLM 服务

| 服务 | Base URL | 特点 |
|------|----------|------|
| DeepSeek | `https://api.deepseek.com/v1` | 价格极低，中文支持好 |
| OpenAI | `https://api.openai.com/v1` | 效果好 |

---

## 艾宾浩斯复习间隔

| 阶段 | 间隔 | 说明 |
|------|------|------|
| 第1次 | 1天 | 刚学新词 |
| 第2次 | 2天 | |
| 第3次 | 4天 | |
| 第4次 | 7天 | |
| 第5次 | 15天 | |
| 第6次 | 30天 | 最终巩固 |
| 已掌握 | — | 不再提醒 |

---

## 文件结构

```
wordbuddy/
├── main.py              # 桌面端入口
├── app/
│   ├── services/         # 同步服务（COS）
│   ├── db/               # SQLite 仓库
│   ├── ui/               # PyQt6 界面
│   └── constants.py
├── mobile-android/       # Android 项目
│   └── app/src/main/java/com/wordbuddy/android/
│       ├── MainActivity.java    # UI 主界面
│       ├── WordDbHelper.java    # 本地数据库
│       ├── CosSyncClient.java   # COS 同步客户端
│       └── LlmClient.java       # LLM 查词
└── requirements.txt
```

---

## 数据存储位置

**桌面端：**
- 配置：`%APPDATA%\WordBuddy\config.json`
- 词库：`%APPDATA%\WordBuddy\word_buddy.db`

**Android 端：**
- 应用私有数据库目录，通过 SharedPreferences 保存配置
