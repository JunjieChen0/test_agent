"""
Cloud Agent HTTP 服务：GET /health、POST /v1/run

启动：
  python -m app.main
  或 uvicorn app.main:app --host 127.0.0.1 --port 8847
（项目根目录需为 test_agent，且已 pip install -r requirements.txt）
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import Response

from app.llm import is_configured, run_llm_agent

DEFAULT_PORT = 8847
PORT = int(os.environ.get("PORT", str(DEFAULT_PORT)))
HOST = os.environ.get("HOST", "127.0.0.1").strip()
EXPECTED_API_KEY = (os.environ.get("CLOUD_AGENT_MOCK_API_KEY") or "").strip()

_log = logging.getLogger("test_agent.auth")

app = FastAPI(title="Cloud Agent", version="1.0.0")


def verify_agent_headers(
    x_device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    if not x_device_token or not str(x_device_token).strip():
        _log.warning("401 missing X-Device-Token (client sent no or empty header)")
        raise HTTPException(status_code=401, detail={"error": "missing X-Device-Token"})
    if EXPECTED_API_KEY and x_api_key != EXPECTED_API_KEY:
        if x_api_key is None or str(x_api_key).strip() == "":
            _log.warning(
                "401 missing X-API-Key while CLOUD_AGENT_MOCK_API_KEY is set on server "
                "(extension must set njust-ai-cj.cloudAgent.apiKey or env CLOUD_AGENT_MOCK_API_KEY)"
            )
        else:
            _log.warning("401 X-API-Key present but does not match server CLOUD_AGENT_MOCK_API_KEY (values not logged)")
        raise HTTPException(status_code=401, detail={"error": "invalid or missing X-API-Key"})


class RunRequest(BaseModel):
    goal: str = ""
    session_id: str = ""
    workspace_path: str = ""
    images: list[str] | None = Field(default=None)


def _demo_response(body: RunRequest) -> dict[str, Any]:
    image_count = len(body.images) if body.images else 0
    logs = [
        f"[test_agent] session_id={body.session_id or '(empty)'}",
        f"[test_agent] workspace_path={body.workspace_path or '(empty)'}",
        f"[test_agent] images={image_count}",
        "[test_agent] 演示模式：未配置 LLM API Key，未调用大模型。",
    ]
    now = datetime.now(timezone.utc).isoformat()
    return {
        "ok": True,
        "user_goal": body.goal,
        "memory_summary": (
            "演示模式：设置环境变量 OPENAI_API_KEY（或 LLM_API_KEY）并可选 "
            "LLM_BASE_URL / LLM_MODEL 后，将调用真实模型生成摘要与 workspace_ops。"
        ),
        "logs": logs,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": 0,
        "workspace_ops": {
            "version": 1,
            "operations": [
                {
                    "op": "write_file",
                    "path": "cloud-agent-demo.txt",
                    "content": f"demo mode {now}\ngoal: {body.goal}\nsession_id: {body.session_id}\n",
                }
            ],
        },
    }


@app.get("/health", dependencies=[Depends(verify_agent_headers)])
async def health() -> Response:
    return Response(status_code=200)


@app.post("/v1/run", dependencies=[Depends(verify_agent_headers)])
async def run_task(body: RunRequest) -> dict[str, Any]:
    if not is_configured():
        return _demo_response(body)

    try:
        agent = await run_llm_agent(
            goal=body.goal,
            session_id=body.session_id,
            workspace_path=body.workspace_path,
            images=body.images,
        )
        out: dict[str, Any] = {
            "ok": agent["ok"],
            "user_goal": body.goal,
            "memory_summary": (
                agent["memory_summary"]
                if agent["ok"]
                else agent.get("error") or agent.get("memory_summary") or "执行失败"
            ),
            "logs": [
                f"[test_agent] LLM tokens in/out: {agent['tokens_in']}/{agent['tokens_out']}",
                *agent.get("logs", []),
            ],
            "tokens_in": agent["tokens_in"],
            "tokens_out": agent["tokens_out"],
            "cost": 0,
        }
        if agent.get("workspace_ops"):
            out["workspace_ops"] = agent["workspace_ops"]
        return out
    except Exception as e:
        msg = str(e)
        return {
            "ok": False,
            "user_goal": body.goal,
            "memory_summary": f"执行异常: {msg}",
            "logs": [msg],
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0,
        }


def main() -> None:
    import errno
    import socket

    import uvicorn

    print(
        f"test_agent (Python) http://{HOST}:{PORT}\n"
        "  GET  /health\n"
        "  POST /v1/run\n"
        + (
            "  需要 X-API-Key（与 CLOUD_AGENT_MOCK_API_KEY 一致）\n"
            if EXPECTED_API_KEY
            else "  未强制 X-API-Key（可设置 CLOUD_AGENT_MOCK_API_KEY）\n"
        )
        + ("  LLM 已配置（真实模式）\n" if is_configured() else "  LLM 未配置 → 演示模式\n")
        + "  云端请设置 HOST=0.0.0.0\n"
    )

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, PORT))
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, 10048):  # 10048: WinError 端口占用
            print(
                f"端口 {PORT} 已被占用（{HOST}）。\n"
                f"  换端口：PowerShell 中  $env:PORT=8848; python -m app.main\n"
                f"  查占用：netstat -ano | findstr \":{PORT}\"  （LISTENING 行最后一列为 PID）\n"
                f"  结束进程：taskkill /PID <pid> /F"
            )
            raise SystemExit(1) from e
        raise
    finally:
        probe.close()

    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
