"""
WordBuddy 常量定义
艾宾浩斯记忆间隔、LLM Prompt 模板、默认配置等
"""

APP_NAME = "WordBuddy"
APP_VERSION = "1.0.0"

# 艾宾浩斯记忆复习间隔（天数）
# 阶段 0->1->2->3->4->5->6（6阶段即「已掌握」）
EBBINGHAUS_INTERVALS = [1, 2, 4, 7, 15, 30]

# 复习检查间隔（分钟）
DEFAULT_REVIEW_CHECK_INTERVAL = 30

# LLM 查词 Prompt 模板
LLM_QUERY_PROMPT = """You are a concise English dictionary. For the word/phrase "{word}", return ONLY this JSON (no markdown):
{{"word":"{word}","phonetic":"IPA","part_of_speech":"pos","definition":"中文释义（简洁）","english_definition":"brief English def","examples":["example 1","example 2"],"synonyms":["syn1","syn2"],"notes":""}}"""

# 例句填空题 Prompt 模板
LLM_FILL_PROMPT = """Give one short example sentence using "{word}". Requirements:
1. The sentence MUST contain the EXACT word "{word}" as used, not a different form.
2. Keep it under 20 words.
3. Provide Chinese translation.
Return ONLY this JSON (no markdown, no explanation):
{{"sentence":"Your sentence here with {word} in it","translation":"中文翻译"}}"""

# 默认配置
DEFAULT_CONFIG = {
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat"
    },
    "cos": {
        "secret_id": "",
        "secret_key": "",
        "bucket": "",
        "region": "ap-guangzhou"
    },
    "settings": {
        "review_interval_minutes": DEFAULT_REVIEW_CHECK_INTERVAL,
        "auto_start": False,
        "theme": "light",
        "fill_ratio": 25
    }
}

# 数据库文件名
DB_FILENAME = "word_buddy.db"
CONFIG_FILENAME = "config.json"
COS_OBJECT_KEY = "word_buddy.db"

# 复习阶段文字描述
REVIEW_STAGE_LABELS = [
    "新词 (第1天)",
    "第2天",
    "第4天",
    "第7天",
    "第15天",
    "第30天",
    "已掌握 ✓"
]
