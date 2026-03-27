# 云端部署说明

服务协议与 NJUST AI CJ **Cloud Agent** 一致：`GET /health`、`POST /v1/run`。

## 环境变量

| 变量 | 说明 |
|------|------|
| `HOST` | 监听地址，云端务必 `0.0.0.0`（镜像默认已设） |
| `PORT` | 端口，Railway/Fly/Render 等通常会注入，需与平台一致 |
| `OPENAI_API_KEY` 或 `LLM_API_KEY` | 大模型密钥；不设置则走**演示模式**（不写真实模型） |
| `LLM_BASE_URL` | OpenAI 兼容接口根地址，默认 `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名，默认 `gpt-4o-mini` |
| `CLOUD_AGENT_MOCK_API_KEY` | 若设置，请求必须带 `X-API-Key`，与扩展 `cloudAgent.apiKey` 一致 |
| `LLM_USE_JSON_OBJECT` | 设为 `0` 可关闭 `response_format: json_object`（兼容部分旧接口） |

扩展侧：`njust-ai-cj.cloudAgent.serverUrl` 填 **https 公网地址**（无尾部 `/`）。

### 使用 DeepSeek

DeepSeek 提供 OpenAI 兼容接口，在平台创建的 **API Key** 可直接使用：

| 变量 | 建议值 |
|------|--------|
| `LLM_API_KEY` | DeepSeek 控制台里的 API Key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | `deepseek-chat`（对话）或 `deepseek-reasoner`（需按官方说明选用） |

PowerShell 示例：

```powershell
$env:LLM_API_KEY = "sk-..."           # DeepSeek 的 key
$env:LLM_BASE_URL = "https://api.deepseek.com/v1"
$env:LLM_MODEL = "deepseek-chat"
python -m app.main
```

若请求因 `response_format` 报错，可尝试：`$env:LLM_USE_JSON_OBJECT = "0"`（以官方当前文档为准）。

## 本地运行（Python）

```bash
cd test_agent
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
set OPENAI_API_KEY=sk-...   # 可选；不设则为演示模式
python -m app.main
```

或：`uvicorn app.main:app --host 127.0.0.1 --port 8847`（需在项目根目录执行；默认端口为 8847，可用环境变量 `PORT` 覆盖）。

## Docker

```bash
docker build -t test-agent .
docker run -p 8080:8080 \
  -e OPENAI_API_KEY=sk-... \
  -e CLOUD_AGENT_MOCK_API_KEY=your-extension-key \
  test-agent
```

平台若分配动态 `PORT`，只需在控制台把 `PORT` 配成平台给定值（多数平台会自动注入，无需改镜像内 `EXPOSE` 数字）。

## 常见托管

- **Railway / Render**：连接 Git 仓库或上传 Dockerfile，在 Variables 里填上述密钥与 `HOST=0.0.0.0`。
- **Fly.io**：`fly launch` 后 `fly secrets set OPENAI_API_KEY=...`，确保 `fly.toml` 中 `internal_port` 与 `PORT` 一致。

## 健康检查

负载均衡若无法自定义头，需使用支持自定义 Header 的检查方式，或向网关层注册带 `X-Device-Token` 的检查（与扩展行为一致）。
