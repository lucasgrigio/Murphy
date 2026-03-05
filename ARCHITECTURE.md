# Architecture

## Murphy File Organization (`murphy/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Package exports and version |
| `__main__.py` | `python -m murphy` entry point |
| `cli.py` | CLI entry point and 2-phase orchestration |
| `api.py` | REST API server (FastAPI) |
| `evaluate.py` | Backward-compatible re-exports |
| `analysis.py` | Website analysis — feature discovery via browser agent |
| `generation.py` | Test plan generation — feature-based and exploration-first paths |
| `execution.py` | Test execution — sequential and parallel with session pooling |
| `judge.py` | LLM judge for pass/fail verdicts |
| `summary.py` | Results classification, summary building, and report writing |
| `report.py` | Markdown and JSON report generation |
| `quality.py` | Test plan quality validation and retry logic |
| `prompts.py` | All LLM prompt text |
| `models.py` | Pydantic models (TestPlan, TestResult, ScenarioExecutionVerdict, etc.) |
| `config.py` | Shared configuration constants |
| `auth.py` | Auth detection and manual login flow |
| `actions.py` | Custom agent actions (domain access, DOM refresh) |
| `session_utils.py` | Session management helpers |
| `patches.py` | Monkey-patches for schema resolution |
| `fixtures.py` | Dummy upload files for test scenarios |
| `features_io.py` | Read/write features markdown files |
| `test_plan_io.py` | Read/write YAML test plans |
| `server.py` | Interactive web UI server |
| `regen_report.py` | Script to regenerate markdown from existing JSON report |

## REST API (`murphy-api`)

Murphy exposes a REST API via FastAPI for programmatic evaluation. Start with `murphy-api`.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/analyze` | Website analysis (feature discovery) |
| `POST` | `/generate-plan` | Test plan generation from analysis |
| `POST` | `/execute` | Test execution from plan |
| `POST` | `/evaluate` | Combined explore + plan generation |
| `GET` | `/jobs/{job_id}` | Job status polling (supports long-poll via `?poll=N`) |

### Execution modes

Every `POST` endpoint supports three modes:

1. **Synchronous** (default) — blocks until completion, returns `200` with result
2. **Async + webhook** (`webhook_url` set) — returns `202` with `job_id`, POSTs result to the webhook URL on completion
3. **Async + polling** (`"async": true`) — returns `202` with `job_id`, poll `/jobs/{job_id}` for result

Authentication is via `X-API-Key` header when `MURPHY_API_KEY` is set. Concurrent jobs are limited by `MURPHY_MAX_CONCURRENT_JOBS` (default: 2).

## Browser-Use Engine (`browser_use/`)

Browser-Use is the async Python library that powers Murphy's browser automation. It uses LLMs + CDP (Chrome DevTools Protocol) to enable AI agents to autonomously navigate web pages, interact with elements, and complete complex tasks.

The library follows an event-driven architecture:

- **Agent (`browser_use/agent/service.py`)** — Main orchestrator: takes tasks, manages browser sessions, executes LLM-driven action loops
- **BrowserSession (`browser_use/browser/session.py`)** — Manages browser lifecycle, CDP connections, and coordinates watchdog services through a `bubus` event bus
- **Tools (`browser_use/tools/service.py`)** — Action registry mapping LLM decisions to browser operations (click, type, scroll, etc.)
- **DomService (`browser_use/dom/service.py`)** — Extracts/processes DOM content, handles element highlighting and accessibility tree generation
- **LLM Integration (`browser_use/llm/`)** — Abstraction layer supporting OpenAI, Anthropic, Google, Groq, and other providers

## Event-Driven Browser Management

BrowserSession uses a `bubus` event bus to coordinate watchdog services:

- **DownloadsWatchdog** — PDF auto-download and file management
- **PopupsWatchdog** — JavaScript dialogs and popups
- **SecurityWatchdog** — Domain restrictions and security policies
- **DOMWatchdog** — DOM snapshots, screenshots, and element highlighting
- **AboutBlankWatchdog** — Empty page redirects

## File Organization Patterns

- **Service pattern**: Each major component has a `service.py` containing main logic (Agent, BrowserSession, DomService, Tools)
- **Views pattern**: Pydantic models and data structures live in `views.py` files
- **Events**: Event definitions in `events.py` files
- **Browser profile**: `browser_use/browser/profile.py` — launch arguments, display configuration, extension management
- **System prompts**: Agent prompts in `browser_use/agent/system_prompt*.md`

## CDP Integration

Uses [cdp-use](https://github.com/browser-use/cdp-use) for typed CDP protocol access. cdp-use only provides shallow typed interfaces for websocket calls — all CDP client/session management lives in `browser_use/browser/session.py`.

CDP API usage examples:
```python
cdp_client.send.DOMSnapshot.enable(session_id=session_id)
cdp_client.send.Target.attachToTarget(params=ActivateTargetParameters(targetId=target_id, flatten=True))
cdp_client.register.Browser.downloadWillBegin(callback_func_here)  # event registration
```

Note: `cdp_client.on(...)` does not exist — use `cdp_client.register.*` for events.

## Browser Configuration

BrowserProfile automatically detects display size via `detect_display_configuration()`:
- macOS: `AppKit.NSScreen`
- Linux/Windows: `screeninfo`
- Extension management (uBlock Origin, cookie handlers) with configurable whitelisting
- Chrome launch argument generation/deduplication
- Proxy support, security settings, headless/headful modes

## MCP (Model Context Protocol) Integration

The library supports both directions:
1. **As MCP Server**: Exposes browser automation tools to MCP clients like Claude Desktop (`uvx browser-use[cli] --mcp`)
2. **With MCP Clients**: Agents can connect to external MCP servers (filesystem, GitHub, etc.) to extend capabilities

Connection management lives in `browser_use/mcp/client.py`.
