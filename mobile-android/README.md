# WordBuddy Android

这是 WordBuddy 的 Android 原生端，和桌面版共用同一个腾讯云 COS 对象：

- 本地数据库：`word_buddy.db`
- COS 对象：`word_buddy.db`
- 数据表：兼容桌面版 `words` 表
- 复习间隔：`1, 2, 4, 7, 15, 30` 天

## 功能

- 手机本地词库浏览和搜索
- 今日复习、随机复习
- 记住 / 模糊 / 忘记 三种复习结果
- OpenAI-compatible LLM 查词，默认兼容 DeepSeek
- 腾讯云 COS 合并同步：下载云端词库，按单词合并，再上传合并结果
- 设置页保存 LLM 与 COS 配置

## 构建

1. 用 Android Studio 打开 `mobile-android`
2. 等待 Gradle 同步完成
3. 连接 Android 手机，点击 Run

当前仓库所在电脑没有检测到 Java、Gradle 或 Android SDK，所以这里没有直接生成 APK。Android Studio 首次打开会自动下载 Gradle 和 Android Gradle Plugin。

## 使用

1. 打开 App，进入“设置”
2. 填入和桌面端相同的 COS SecretId、SecretKey、Bucket、Region
3. 如需手机查词，填入 LLM Base URL、API Key、Model
4. 点“保存设置”
5. 点首页“立即同步”，拉取并合并电脑端词库

安全提醒：这个版本是个人自用端，COS SecretKey 会保存在手机本地 SharedPreferences 中。不要把填好密钥的安装包或手机备份发给别人。
