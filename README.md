# Murphy — AI-Driven Website Evaluation

Murphy automatically evaluates websites in two phases: **plan** (discover features and generate test scenarios) and **execute** (run tests in a real browser with an AI judge). It produces structured evaluation reports with pass/fail results, failure categorization, and actionable summaries.

Built on top of [browser-use](https://github.com/browser-use/browser-use) (AI browser automation library).

## Prerequisites

- Python >= 3.11
- An LLM API key — default model is `gpt-5-mini`, so you'll need `OPENAI_API_KEY` (or pass `--model` for another provider)

## Which setup should I use?

| | **Local (uv)** | **Docker** |
|---|---|---|
| **Best for** | Sites requiring login (`--auth`), development | Public sites, reproducible environments |
| **Auth support** | Full — opens a visible browser for manual login | No — browser runs headless with no visible window, so `--auth` cannot work |
| **Review pauses** | Works — you edit files on disk and press Enter | Works — files are on a mounted volume, press Enter in the same terminal |
| **Requires** | Python >= 3.11, uv, Chromium | Docker |

**Rule of thumb:** use **local** if the site requires authentication. Both setups are interactive — Murphy pauses for you to review and edit the generated features and test plan before continuing.

## Setup (local)

**1. Install [uv](https://docs.astral.sh/uv/):**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Clone and install dependencies:**
```bash
git clone https://github.com/ProsusAI/Murphy.git
cd Murphy
uv sync
```

**3. Install Chromium:**
```bash
uv run playwright install chromium
```

**4. Create `.env` with your API key:**
```bash
cp .env.example .env
```
Then set your key:
```
OPENAI_API_KEY=sk-...
```

## Setup (Docker)

> **Note:** Docker runs the browser in headless mode. The `--auth` flag (manual login) will not work — use the local setup above if your site requires login.

**1. Build the image:**
```bash
docker build -f docker/Dockerfile . -t murphy --no-cache
```

**2. Create `.env` with your API key** (same as above).

**3. Run via the helper script:**
```bash
./murphy/run.sh --url https://example.com [options]
```

The script mounts `murphy/` and `.env` into the container and runs `python -m murphy` with your arguments.

## Usage

All examples below use `uv run murphy`. If running via Docker, replace with `./murphy/run.sh`.

```bash
# Full run: auto-detect auth -> analyze site -> generate tests -> execute
uv run murphy --url https://example.com

# With a specific goal (biases test generation toward that area)
uv run murphy --url https://example.com --goal "test the checkout flow"

# Site requires login — opens browser for manual auth first (local only, not Docker)
uv run murphy --url https://example.com --auth

# Public site, skip auth detection entirely
uv run murphy --url https://example.com --no-auth

# Resume from previously generated/edited files
uv run murphy --url https://example.com --features murphy/output/example_com_features.md
uv run murphy --url https://example.com --plan murphy/output/test_plan.yaml
```

## How It Works

Murphy runs two phases with human-in-the-loop pauses for review:

**Phase 1 — Plan:** An AI agent navigates the site, discovers pages, and catalogs features. Murphy saves an editable `<site>_features.md` and pauses for review. Then an LLM reads the features and produces test scenarios with steps and success criteria, saving an editable `test_plan.yaml` with another pause for review.

**Phase 2 — Execute:** An AI agent runs each test scenario in a real browser, and a judge LLM evaluates pass/fail. Saves `evaluation_report.json` and `evaluation_report.md`.

You can resume from any point by passing `--features` or `--plan` with a previously generated (and optionally edited) file.

## Output

Default output directory: `./murphy/output/`

| File | Description |
|------|-------------|
| `<site>_features.md` | Discovered features, pages, and user flows (editable) |
| `test_plan.yaml` | Generated test scenarios with steps and success criteria (editable) |
| `evaluation_report.json` | Full structured results (machine-readable) |
| `evaluation_report.md` | Human-readable summary with pass/fail per test |

## All CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | *(required)* | Target URL to evaluate |
| `--goal` | | Free-text goal to bias test generation (e.g. `"test the checkout flow"`) |
| `--auth` | `false` | Skip auto-detection, go straight to manual login wait |
| `--no-auth` | `false` | Skip auth detection entirely, treat site as public |
| `--features` | | Path to existing features markdown (skips feature discovery) |
| `--plan` | | Path to existing YAML test plan (skips planning, goes straight to execution) |
| `--max-tests` | `8` | Maximum number of test scenarios to generate |
| `--model` | `gpt-5-mini` | LLM model for agent tasks |
| `--judge-model` | `gpt-5-mini` | LLM model for judging verdicts |
| `--output-dir` | `./murphy/output` | Output directory for all generated files |
| `--category` | | Site category hint (`ecommerce`, `saas`, `content`, `social`) |
| `--ui` | `false` | Launch interactive web UI instead of terminal output |
| `--no-highlights` | `false` | Disable bounding boxes on interactive elements in the browser |
| `--max-steps` | `30` | Max agent steps per exploration/execution phase |
| `--parallel` | `3` | Number of tests to run concurrently |

## Interactive UI

Launch the web UI with:
```bash
murphy --url https://example.com --ui
```

The UI lets you review the generated test plan, run all tests with a live progress bar, and view detailed results with pass/fail verdicts, action traces, and failure analysis.

---

## REST API

Murphy also exposes a REST API for programmatic evaluation:

```bash
murphy-api
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/analyze` | Website analysis (feature discovery) |
| `POST` | `/generate-plan` | Test plan generation from analysis |
| `POST` | `/execute` | Test execution from plan |
| `POST` | `/evaluate` | Combined explore + plan generation |
| `GET` | `/jobs/{job_id}` | Job status polling (supports long-poll via `?poll=N`) |

Every `POST` endpoint supports three modes:

- **Synchronous** (default) — blocks until completion, returns `200` with result
- **Async + webhook** (`webhook_url` set) — returns `202` with `job_id`, POSTs result to webhook on completion
- **Async + polling** (`"async": true`) — returns `202` with `job_id`, poll `/jobs/{job_id}` for result

Authentication is via `X-API-Key` header when `MURPHY_API_KEY` is configured.

---

## Environment Variables

All variables are optional unless noted. See `.env.example` for a template.

### LLM Providers

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (required if using default `gpt-5-mini` model) |
| `ANTHROPIC_API_KEY` | Anthropic API key (if using `--model` with an Anthropic model) |
| `GOOGLE_API_KEY` | Google API key (if using `--model` with a Google model) |
| `GROQ_API_KEY` | Groq API key (if using `--model` with a Groq model) |
| `DEEPSEEK_API_KEY` | DeepSeek API key (if using `--model` with a DeepSeek model) |

### REST API

| Variable | Default | Description |
|----------|---------|-------------|
| `MURPHY_API_KEY` | *(none)* | API key for REST API authentication (open access if unset) |
| `MURPHY_API_HOST` | `0.0.0.0` | Host to bind the API server |
| `MURPHY_API_PORT` | `8000` | Port for the API server |
| `MURPHY_MAX_CONCURRENT_JOBS` | `2` | Maximum concurrent browser jobs |
| `MURPHY_REQUEST_TIMEOUT` | `1800` | HTTP keep-alive timeout (seconds) |
| `MURPHY_JOB_TIMEOUT_OVERRIDE` | *(none)* | Override all per-endpoint job timeouts (seconds) |

### Browser

| Variable | Default | Description |
|----------|---------|-------------|
| `BROWSER_USE_EXECUTABLE_PATH` | *(auto)* | Path to Chrome/Chromium executable |
| `BROWSER_USE_HEADLESS` | `true` | Run browser in headless mode |
| `BROWSER_USE_LOGGING_LEVEL` | `info` | Logging level |

---

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details on the codebase structure, including the Murphy evaluation pipeline and the vendored browser-use engine.

---

## Development

### Setup

```bash
uv sync
```

### Testing

```bash
uv run pytest -vxs tests/browser_use         # CI test suite
uv run pytest -vxs tests/                     # all tests
uv run pytest -vxs tests/browser_use/test_specific_test.py  # single file
```

### Quality Checks

```bash
uv run pyright                          # type checking
uv run ruff check --fix                 # linting
uv run ruff format                      # formatting
uv run pre-commit run --all-files       # pre-commit hooks
```

### Code Style

- Async Python throughout
- **Tabs** for indentation (not spaces)
- Modern Python 3.12+ typing: `str | None`, `list[str]`, `dict[str, Any]` (not `Optional`, `List`, `Dict`)
- Console logging in separate `_log_*` methods to keep main logic clean
- Pydantic v2 models for internal data and user-facing API parameters
- Pydantic `model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)` tuned per use-case
- `Annotated[..., AfterValidator(...)]` for validation logic instead of helper methods
- `from uuid_extensions import uuid7str` + `id: str = Field(default_factory=uuid7str)` for ID fields
- Runtime assertions at function boundaries to enforce constraints
- Always use `uv` instead of `pip`
- Use real model names — `gpt-4o` and `gpt-4` are distinct models
- Return `ActionResult` with structured content from actions
- Run pre-commit hooks before PRs

### Testing Conventions

- **No mocks** — always use real objects. The only exception is the LLM: use pytest fixtures in `conftest.py` to set up LLM responses.
- **No real remote URLs** — use `pytest-httpserver` to set up a local test server with the HTML needed for each test.
- Tests in `tests/browser_use/` are the CI suite, run automatically on every commit. Tests specific to an event go in `tests/browser_use/test_action_EventNameHere.py`.
- Modern pytest-asyncio: no `@pytest.mark.asyncio` needed, just use `async` test functions. Use `loop = asyncio.get_event_loop()` when needed. Fixtures use plain `@pytest.fixture`.

### Strategy for Making Changes

1. Find or write tests verifying existing behavior before making changes
2. Write failing tests for the new design, confirm they fail
3. Implement changes, running tests as needed to verify assumptions
4. Run the full `tests/browser_use` suite — confirm new design works and backward compatibility is preserved
5. Condense/deduplicate test logic, scan for other test files that need updates
6. Update relevant docs to match implementation

For large refactors, prefer event buses and job queues to break systems into smaller services managing isolated state.
