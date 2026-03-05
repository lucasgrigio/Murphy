# Architecture

## Murphy File Organization (`murphy/`)

| File | Purpose |
|------|---------|
| `cli.py` | CLI entry point and orchestration |
| `evaluate.py` | Core evaluation logic (exploration, plan generation, test execution) |
| `judge.py` | LLM judge for pass/fail verdicts |
| `models.py` | Pydantic models (TestPlan, TestResult, ScenarioExecutionVerdict, etc.) |
| `report.py` | Markdown report generation |
| `server.py` | Web UI server |
| `actions.py` | Custom agent actions (domain access, DOM refresh) |
| `session_utils.py` | Session management helpers |
| `patches.py` | Monkey-patches for schema resolution |
| `fixtures.py` + `fixtures/` | Dummy upload files for test scenarios |

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
