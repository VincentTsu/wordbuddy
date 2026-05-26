# WordBuddy — 英语单词学习助手

跨电脑同步的英语单词学习工具，支持 LLM 查词、艾宾浩斯复习提醒、腾讯云 COS 数据同步。

---

## 功能特性

- 🔍 **LLM 智能查词**：调用 DeepSeek / OpenAI / 通义千问等 AI，获取音标、词性、释义、例句
- 🧠 **艾宾浩斯复习**：根据遗忘曲线（1→2→4→7→15→30 天）自动弹窗提醒复习
- ☁️ **腾讯云 COS 同步**：词库自动在公司/家里电脑间同步
- 📚 **词库管理**：查看所有单词、搜索过滤、复习统计
- 🖥️ **系统托盘常驻**：不占任务栏，右键菜单快速操作

---

## 安装和运行

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 2. 直接运行

```bash
python main.py
```

### 3. 打包为 .exe（可选）

```bash
pip install pyinstaller
pyinstaller build/word_buddy.spec
```
打包完成后，可执行文件在 `dist/WordBuddy.exe`。

---

## 首次使用配置

1. 启动程序后，右键托盘图标 → **设置**
2. **LLM 配置**：填入 API Key 和模型（推荐 DeepSeek，便宜好用）
   - Base URL: `https://api.deepseek.com/v1`
   - Model: `deepseek-chat`
3. **云同步配置**（可选）：填入腾讯云 COS 的 SecretId / SecretKey / Bucket / Region
4. 保存配置后，右键托盘 → **查词** 即可开始使用

---

## 推荐 LLM 服务

| 服务 | Base URL | 特点 |
|------|----------|------|
| DeepSeek | `https://api.deepseek.com/v1` | 价格极低，中文支持好 |
| OpenAI | `https://api.openai.com/v1` | GPT-4o-mini 效果好 |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 国内访问稳定 |

---

## 数据存储位置

- 配置文件：`%APPDATA%\WordBuddy\config.json`
- 词库数据库：`%APPDATA%\WordBuddy\word_buddy.db`

⚠️ **安全提示**：`config.json` 包含 API Key，请勿提交到 Git 仓库。

---

## 艾宾浩斯复习间隔

| 阶段 | 距上次 | 说明 |
|------|--------|------|
| 第1次 | 1天 | 刚学新词 |
| 第2次 | 2天 | |
| 第3次 | 4天 | |
| 第4次 | 7天 | |
| 第5次 | 15天 | |
| 第6次 | 30天 | 最终巩固 |
| 已掌握 | — | 不再提醒 |
