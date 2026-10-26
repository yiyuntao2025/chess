from __future__ import annotations

import os
from typing import Iterator


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

SYSTEM_PROMPT = (
    "你是一名严谨、务实的国际象棋教练。"
    "只依据用户提供的棋谱、局面、Stockfish 评估和标注作答，"
    "不要编造不存在的着法或引擎数据。"
    "使用中文，结构清晰，重点解释失误与精彩着法，并给出可执行的练习建议。"
)


def _client(
    api_key: str,
    base_url: str,
    timeout: float,
):
    if not api_key:
        raise RuntimeError(
            "未配置 DeepSeek API Key。请在教练窗口中点击“配置 DeepSeek”，"
            "或设置环境变量 DEEPSEEK_API_KEY。"
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "缺少 openai 依赖，请先运行 pip install openai"
        ) from exc
    return OpenAI(
        api_key=api_key,
        base_url=base_url or DEFAULT_BASE_URL,
        timeout=timeout,
        max_retries=1,
    )


def ask_deepseek_coach(
    prompt: str,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = 60.0,
) -> str:
    client = _client(api_key, base_url, timeout)
    response = client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("DeepSeek 未返回内容")
    return content


def stream_deepseek_coach(
    prompt: str,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = 60.0,
) -> Iterator[str]:
    client = _client(api_key, base_url, timeout)
    response = client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        stream=True,
    )
    produced = False
    for chunk in response:
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        delta = choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            produced = True
            yield content
    if not produced:
        raise RuntimeError("DeepSeek 未返回内容")


def env_api_key() -> str:
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()
