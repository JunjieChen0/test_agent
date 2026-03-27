"""OpenAI 兼容 Chat Completions（DeepSeek / 智谱 / Groq 等可通过环境变量指向）。"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

LLM_API_KEY = (os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY") or "").strip()
LLM_BASE_URL = (os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = (os.environ.get("LLM_MODEL") or "gpt-4o-mini").strip()

SYSTEM_PROMPT = """你是 Cloud Agent 服务端助手。用户会给出当前任务目标、会话 id、工作区路径说明；可能附带截图（图片 URL 或 base64）。
你必须只输出一个 JSON 对象，不要 markdown 代码块，不要其它文字。JSON 结构如下：
{
  "memory_summary": "string，用简洁中文总结你为用户做了什么或建议",
  "logs": ["string", "多行执行/思考日志，方便 IDE 展示"],
  "workspace_ops": null 或 {
    "version": 1,
    "operations": [
      { "op": "write_file", "path": "相对工作区的路径", "content": "完整 UTF-8 文件内容" },
      { "op": "apply_diff", "path": "相对工作区的路径", "diff": "<<<<<<< SEARCH\\n...\\n=======\\n...\\n>>>>>>> REPLACE\\n" }
    ]
  }
}
规则：
- operations 最多 20 条（足够演示）；path 使用正斜杠，不要用绝对路径。
- 若无需改本地文件，workspace_ops 设为 null。
- 优先给出可执行的 write_file（例如 README、小脚本），避免无意义的空操作。"""


def is_configured() -> bool:
    return bool(LLM_API_KEY)


def _build_user_content(
    goal: str,
    session_id: str,
    workspace_path: str,
    images: list[str] | None,
) -> str | list[dict[str, Any]]:
    text = (
        f"【用户目标】\n{goal or '(空)'}\n\n"
        f"【session_id】\n{session_id or '(空)'}\n\n"
        f"【workspace_path】\n{workspace_path or '(空，扩展仅在本地落盘)'}\n"
    )
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if images:
        for img in images:
            if not isinstance(img, str) or not img.strip():
                continue
            parts.append({"type": "image_url", "image_url": {"url": img.strip()}})
    return text if len(parts) == 1 else parts


def _safe_parse_json_object(text: str) -> dict[str, Any] | None:
    t = text.strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        out = json.loads(t[start : end + 1])
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def _clamp_workspace_ops(ops: Any) -> dict[str, Any] | None:
    if not isinstance(ops, dict):
        return None
    if ops.get("version") is not None and ops.get("version") != 1:
        return None
    raw = ops.get("operations")
    if not isinstance(raw, list):
        return None
    operations: list[dict[str, Any]] = []
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        op = item.get("op")
        path = item.get("path") if isinstance(item.get("path"), str) else ""
        if len(path) > 4096:
            continue
        if op == "write_file" and isinstance(item.get("content"), str):
            c = item["content"]
            if len(c) > 1_000_000:
                continue
            operations.append({"op": "write_file", "path": path, "content": c})
        elif op == "apply_diff" and isinstance(item.get("diff"), str):
            d = item["diff"]
            if len(d) > 1_000_000:
                continue
            operations.append({"op": "apply_diff", "path": path, "diff": d})
    if not operations:
        return None
    return {"version": 1, "operations": operations}


async def run_llm_agent(
    *,
    goal: str,
    session_id: str,
    workspace_path: str,
    images: list[str] | None = None,
) -> dict[str, Any]:
    if not is_configured():
        return {
            "ok": False,
            "error": "未配置 OPENAI_API_KEY 或 LLM_API_KEY，无法调用模型",
            "memory_summary": "",
            "logs": [],
            "tokens_in": 0,
            "tokens_out": 0,
        }

    user_content = _build_user_content(goal, session_id, workspace_path, images)
    use_json = os.environ.get("LLM_USE_JSON_OBJECT", "1").strip() != "0"
    url = f"{LLM_BASE_URL}/chat/completions"

    def build_payload(with_json_format: bool) -> dict[str, Any]:
        p: dict[str, Any] = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
        }
        if with_json_format:
            p["response_format"] = {"type": "json_object"}
        return p

    async def post_chat(client: httpx.AsyncClient, payload: dict[str, Any]) -> httpx.Response:
        return await client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LLM_API_KEY}",
            },
            json=payload,
            timeout=120.0,
        )

    async with httpx.AsyncClient() as client:
        resp = await post_chat(client, build_payload(use_json))
        raw_text = resp.text

        if not resp.is_success and use_json and resp.status_code == 400:
            resp = await post_chat(client, build_payload(False))
            raw_text = resp.text

        try:
            data = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": f"模型接口返回非 JSON（HTTP {resp.status_code}）",
                "memory_summary": raw_text[:500],
                "logs": [f"HTTP {resp.status_code}", raw_text[:200]],
                "tokens_in": 0,
                "tokens_out": 0,
            }

        if not resp.is_success:
            err = data.get("error") if isinstance(data.get("error"), dict) else {}
            msg = (
                err.get("message")
                or data.get("message")
                or raw_text[:300]
            )
            return {
                "ok": False,
                "error": f"模型接口错误 HTTP {resp.status_code}: {msg}",
                "memory_summary": "",
                "logs": [f"HTTP {resp.status_code}", str(msg)],
                "tokens_in": 0,
                "tokens_out": 0,
            }

        choices = data.get("choices") or []
        choice0 = choices[0] if choices else {}
        msg = choice0.get("message") or {}
        assistant_text = msg.get("content") if isinstance(msg.get("content"), str) else ""
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)

        parsed = _safe_parse_json_object(assistant_text)
        if not parsed:
            return {
                "ok": True,
                "memory_summary": (assistant_text[:8000] if assistant_text else "（模型无文本）"),
                "logs": ["模型未返回可解析 JSON，已将原文写入 memory_summary"],
                "workspace_ops": None,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }

        memory_summary = (
            parsed["memory_summary"]
            if isinstance(parsed.get("memory_summary"), str)
            else assistant_text[:4000]
        )
        logs_raw = parsed.get("logs")
        logs = (
            [str(x) for x in logs_raw if x is not None and str(x)]
            if isinstance(logs_raw, list)
            else []
        )
        workspace_ops = _clamp_workspace_ops(parsed.get("workspace_ops"))

        return {
            "ok": True,
            "memory_summary": memory_summary,
            "logs": logs,
            "workspace_ops": workspace_ops,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }
