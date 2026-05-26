"""
WordBuddy LLM 服务
支持流式输出（Streaming），边生成边显示，查词速度大幅提升
"""

import json
import logging
import re
import requests
from typing import Dict, Any, Optional, Callable

from app.config import config
from app.constants import LLM_QUERY_PROMPT, LLM_FILL_PROMPT

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用异常"""
    def __init__(self, message: str, error_type: str = "unknown"):
        super().__init__(message)
        self.error_type = error_type


class LLMService:
    """OpenAI 兼容 API 查词服务（支持流式输出）"""

    def query_word(
        self,
        word: str,
        on_progress: Optional[Callable[[str], None]] = None,
        on_stream: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        查询单词释义（优先使用流式模式）
        :param word: 要查询的单词或词组
        :param on_progress: 进度状态回调（用于状态栏文字）
        :param on_stream: 流式内容回调（每收到一段文字就调用一次）
        :return: 解析后的单词信息字典
        :raises LLMError: 调用失败时抛出
        """
        if not config.llm_api_key:
            raise LLMError("请先在设置中配置 LLM API Key", "config_missing")

        if on_progress:
            on_progress(f"正在查询「{word}」...")

        prompt = LLM_QUERY_PROMPT.format(word=word)

        headers = {
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        }

        use_stream = on_stream is not None

        payload = {
            "model": config.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 400,  # 精简 prompt 后 400 已够用
            "stream": use_stream,
        }

        base_url = config.llm_base_url.rstrip("/")
        url = f"{base_url}/chat/completions"

        try:
            if use_stream:
                return self._query_stream(url, headers, payload, word, on_progress, on_stream)
            else:
                return self._query_normal(url, headers, payload, word, on_progress)

        except LLMError:
            raise
        except requests.exceptions.ConnectionError:
            raise LLMError("网络连接失败，请检查网络或 API 地址", "network_error")
        except requests.exceptions.Timeout:
            raise LLMError("请求超时，请检查网络连接", "timeout")
        except KeyError as e:
            raise LLMError(f"API 响应格式异常: {e}", "parse_error")
        except Exception as e:
            raise LLMError(f"未知错误: {e}", "unknown")

    def _query_stream(
        self,
        url: str,
        headers: dict,
        payload: dict,
        word: str,
        on_progress: Optional[Callable],
        on_stream: Callable[[str], None],
    ) -> Dict[str, Any]:
        """流式模式：边接收边回调，首字符出现极快"""
        with requests.post(url, headers=headers, json=payload, stream=True, timeout=30) as resp:
            self._check_status(resp)

            full_content = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if not line_str.startswith("data: "):
                    continue
                data_str = line_str[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        full_content += text
                        on_stream(text)  # 实时推送给 UI
                except (json.JSONDecodeError, KeyError):
                    continue

        if on_progress:
            on_progress("解析结果中...")
        return self._parse_response(full_content, word)

    def _query_normal(
        self,
        url: str,
        headers: dict,
        payload: dict,
        word: str,
        on_progress: Optional[Callable],
    ) -> Dict[str, Any]:
        """普通模式（不传 on_stream 时使用）"""
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        self._check_status(response)
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        if on_progress:
            on_progress("解析结果中...")
        return self._parse_response(content, word)

    def _check_status(self, response: requests.Response):
        """统一处理 HTTP 错误状态码"""
        code = response.status_code
        if code == 401:
            raise LLMError("API Key 无效，请检查设置", "auth_error")
        elif code == 429:
            raise LLMError("请求太频繁或余额不足，请稍后重试", "rate_limit")
        elif code == 404:
            raise LLMError("API 地址不正确（404），请检查 Base URL 设置", "not_found")
        elif code != 200:
            raise LLMError(f"API 请求失败（HTTP {code}）", "api_error")

    def _parse_response(self, content: str, original_word: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 内容"""
        # 提取 JSON（兼容 markdown 代码块）
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            brace_match = re.search(r"\{.*\}", content, re.DOTALL)
            json_str = brace_match.group(0) if brace_match else content

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}\n原始内容: {content[:200]}")
            return {
                "word": original_word,
                "phonetic": "",
                "part_of_speech": "",
                "definition": content[:500],
                "english_definition": "",
                "examples": [],
                "synonyms": [],
                "notes": "",
            }

        result = {
            "word": parsed.get("word", original_word),
            "phonetic": parsed.get("phonetic", ""),
            "part_of_speech": parsed.get("part_of_speech", ""),
            "definition": parsed.get("definition", ""),
            "english_definition": parsed.get("english_definition", ""),
            "examples": parsed.get("examples", []),
            "synonyms": parsed.get("synonyms", []),
            "notes": parsed.get("notes", ""),
        }

        if not isinstance(result["examples"], list):
            result["examples"] = [str(result["examples"])]
        if not isinstance(result["synonyms"], list):
            result["synonyms"] = [str(result["synonyms"])]

        return result

    def test_connection(self) -> tuple[bool, str]:
        """测试 API 连接"""
        try:
            result = self.query_word("hello")
            return True, f"连接成功！模型: {config.llm_model}"
        except LLMError as e:
            return False, str(e)
        except Exception as e:
            return False, f"未知错误: {e}"

    def generate_sentence(self, word: str) -> Dict[str, str]:
        """
        为指定单词生成一个含中文翻译的例句（用于填空模式）
        每次调用返回不同的例句（temperature=0.9 鼓励多样性）
        :param word: 目标单词
        :return: {"sentence": "...", "translation": "..."}
        """
        if not config.llm_api_key:
            raise LLMError("请先在设置中配置 LLM API Key", "config_missing")

        prompt = LLM_FILL_PROMPT.format(word=word)

        headers = {
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": config.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            "max_tokens": 200,
        }

        base_url = config.llm_base_url.rstrip("/")
        url = f"{base_url}/chat/completions"

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            self._check_status(response)
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            # 解析 JSON
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            json_str = json_match.group(1) if json_match else content
            brace_match = re.search(r"\{.*\}", content, re.DOTALL)
            if not json_match and brace_match:
                json_str = brace_match.group(0)

            parsed = json.loads(json_str)
            return {
                "sentence": parsed.get("sentence", f"[{word}]"),
                "translation": parsed.get("translation", ""),
            }

        except requests.exceptions.ConnectionError:
            raise LLMError("网络连接失败", "network_error")
        except requests.exceptions.Timeout:
            raise LLMError("请求超时", "timeout")
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"例句解析失败: {e}")
            return {"sentence": f"[{word}]", "translation": ""}
        except Exception as e:
            raise LLMError(f"生成例句失败: {e}", "unknown")


# 全局单例
llm_service = LLMService()
