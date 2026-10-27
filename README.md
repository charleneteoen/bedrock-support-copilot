# Bedrock Support Copilot

A customer-support assistant that streams answers in real time from **Claude on Amazon Bedrock**. It grounds answers in company docs with **Bedrock Knowledge Bases** (RAG), takes actions with **tool calling**, filters input and output with **Bedrock Guardrails**, and stores conversations in **DynamoDB**. Tokens reach the browser over a WebSocket as they are generated, and each turn reports latency and token metrics.

## Architecture

```
Browser (WebSocket) ──► FastAPI /ws/chat
                           │
                           ├─ 1. Guardrail (INPUT)  ── bedrock-runtime ApplyGuardrail
                           ├─ 2. Retrieve context   ── bedrock-agent-runtime Retrieve (Knowledge Base)
                           ├─ 3. Load history       ── DynamoDB (sessions, TTL 24h)
                           ├─ 4. Stream Claude      ── Bedrock (Anthropic SDK, AsyncAnthropicBedrockMantle)
                           │      └─ tool_use? ──► lookup_order / create_support_ticket ──► loop
                           ├─ 5. Guardrail (OUTPUT) ── replaces streamed answer if it intervenes
                           └─ 6. Save history + emit metrics (TTFT, latency, tokens, cache hits)
```

| File | Responsibility |
|---|---|
| [app/copilot.py](app/copilot.py) | Orchestrates one turn as an async event stream, including the streaming tool-use loop |
| [app/retrieval.py](app/retrieval.py) | Bedrock Knowledge Base retrieval, with a local keyword fallback |
| [app/guardrails.py](app/guardrails.py) | ApplyGuardrail on input and output |
| [app/tools.py](app/tools.py) | Tool schemas (`strict`) and validation of tool input before execution |
| [app/store.py](app/store.py) | DynamoDB or in-memory session history and orders |
| [app/mock_bedrock.py](app/mock_bedrock.py) | Offline stand-in for the Bedrock client, for demos and tests |
| [infra/main.tf](infra/main.tf) | DynamoDB tables, the Guardrail and a least-privilege IAM policy |

## Run it locally (no AWS needed)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
COPILOT_MODE=mock .venv/bin/uvicorn app.main:app --reload
# open http://localhost:8000
.venv/bin/pytest            # 9 tests: RAG, tools, guardrails, history, WebSocket
```

## Run against AWS

1. Enable the Claude model in the Bedrock console (Model access).
2. `cd infra && terraform init && terraform apply`. This creates the tables, the guardrail and the IAM policy.
3. Optional: create a Knowledge Base from an S3 bucket holding `knowledge/*.md`, then set `KNOWLEDGE_BASE_ID`.
4. Copy the `env` output from Terraform into your environment (see [.env.example](.env.example)), then:

```bash
COPILOT_MODE=bedrock .venv/bin/uvicorn app.main:app
# or
docker build -t support-copilot . && docker run -p 8000:8000 --env-file .env -v ~/.aws:/root/.aws:ro support-copilot
```

## Engineering decisions

- **Streaming with tools.** Text tokens go to the client as soon as they arrive. When Claude requests tools, every call in that round runs concurrently with `asyncio.gather`, and all results return in a single `tool_result` message, so Claude keeps making parallel calls. A round that stops on `max_tokens` never executes its tool call.
- **Validating model output.** Tools use `strict` schemas plus server-side validation in `tools.validate`, because eager input streaming skips the API's own validation. Bad input goes back to the model as an `is_error` tool result rather than crashing the turn.
- **Guardrails versus latency.** The input guardrail runs before any model call. The output guardrail checks the full answer after streaming. If it intervenes, a `replace` event swaps the text in the browser. This keeps time-to-first-token low while still enforcing policy.
- **Prompt caching.** The system prompt is frozen and the tool order is fixed, so the cached prefix stays identical across turns. Retrieved context goes into the user turn, after the cache breakpoint. `cache_read_tokens` in the metrics shows the savings.
- **Swappable backends.** Each AWS integration switches on through its own env var and has an in-memory fallback. You can develop and test offline, then deploy the same code against AWS.
- **Non-blocking I/O.** boto3 calls run in `asyncio.to_thread`, so one slow Retrieve or DynamoDB call doesn't stall other WebSocket clients.

## Resume bullets

- Built a real-time GenAI support assistant on **Amazon Bedrock (Claude)** with token streaming over WebSockets (FastAPI, asyncio), RAG through **Bedrock Knowledge Bases**, and multi-step **tool calling** for order lookup and ticket escalation.
- Added **Bedrock Guardrails** on both user input and model output (prompt-attack filtering, PII anonymization, denied topics) while keeping time-to-first-token low.
- Stored session memory in **DynamoDB** with TTL and provisioned the infrastructure with **Terraform** under least-privilege IAM. Packaged the service with Docker.
- Instrumented each turn with time-to-first-token, end-to-end latency, token usage and prompt-cache hits. Used prompt caching to cut repeated input-token cost.
- Wrote an offline mock of the Bedrock streaming client so the test suite covers RAG, tool use, guardrail paths and the WebSocket protocol in CI without AWS credentials.

## Next steps

- Deploy on ECS Fargate or App Runner behind an ALB with WebSocket support, and use API Gateway WebSockets plus Lambda for a serverless option.
- Publish the metrics to CloudWatch with EMF and add a dashboard and alarms on p95 TTFT.
- Add an evaluation set of real support questions with expected answers, to catch regressions when changing prompts or models.
- Add a client-side refusal fallback to a second model (`BetaRefusalFallbackMiddleware`).
