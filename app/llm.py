"""模型层（Model）：封装火山方舟 DeepSeek 调用

对应 harness 五层（Harness/Runtime/Framework/Agent/Model）的最内层——
模型"只会生成文本"，Agent 循环是叠在它外面的能力。

- call_chat：非流式（工具调用阶段用，要完整 JSON 决定调不调工具）
- call_chat_stream：流式（建议生成阶段用，打字机）
- 每次调用返回 (响应, meta)，meta 含 token/耗时（可观测埋点）

错误处理（对应 30 题第 20 题"LLM 调用失败怎么办"）：
- 网络/HTTP 错误 → 抛 LLMError，由循环层决定重试还是降级
- 不在这里静默吞错（静默 = 循环以为成功了，最危险）
"""

import json
import os
import time
import urllib.request
import urllib.error

from app.config import load_env_file, get

load_env_file()

API_KEY = get("ARK_API_KEY", "")
MODEL = get("ARK_MODEL", "deepseek-v4-flash-260425")
BASE = "https://ark.cn-beijing.volces.com/api/v3"

# 代理支持（如果 .env 配了 HTTPS_PROXY；国内 API 一般直连）
_proxy = get("HTTPS_PROXY", "")
if _proxy:
    _handler = urllib.request.ProxyHandler({"http": _proxy, "https": _proxy})
    urllib.request.install_opener(urllib.request.build_opener(_handler))


class LLMError(Exception):
    """LLM 调用失败（网络/HTTP/超时）——循环层捕获后决定重试"""


def _post(payload: dict, timeout: int = 30) -> dict:
    """POST 到 OpenAI 兼容接口，返回 JSON"""
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        raise LLMError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"网络错误: {e.reason}") from e
    except TimeoutError as e:
        raise LLMError("请求超时") from e


def call_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int = 800,
) -> tuple[dict, dict]:
    """非流式调用：返回 (完整响应, 埋点 meta)"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools

    t0 = time.time()
    resp = _post(payload)
    dur = int((time.time() - t0) * 1000)

    usage = resp.get("usage", {})
    meta = {
        "model": MODEL,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "duration_ms": dur,
    }
    return resp, meta


def call_chat_stream(messages: list[dict], max_tokens: int = 800):
    """流式调用：yield 文本片段（建议阶段打字机用）"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
    }
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            for raw in resp:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"流式调用失败: {e}") from e
