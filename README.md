# Murphy — AI-Driven Website Evaluation

Murphy is a 3-phase agent that automatically evaluates websites: **analyze** the site to discover features, **generate** test scenarios, then **execute** them with an AI browser agent. It produces structured evaluation reports with pass/fail results, failure categorization, and actionable summaries.

Built on top of [browser-use](https://github.com/browser-use/browser-use) (AI browser automation library).

## Prerequisites

- Python >= 3.11
- An LLM API key — default model is `gpt-4o`, so you'll need `OPENAI_API_KEY` (or pass `--model` for another provider)

## Setup (without Docker)

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

## Setup (with Docker)

**1. Build the image:**
```bash
docker build -f docker/Dockerfile . -t murphy --no-cache
```

**2. Create `.env` with your API key** (same as above).

**3. Run via the helper script:**
```bash
./murphy/run.sh https://example.com [options]
```

The script mounts `murphy/` and `.env` into the container and runs `python -m murphy` with your arguments.

## Usage

```bash
# Full run: auto-detect auth -> analyze site -> generate tests -> execute
murphy --url https://example.com

# With a specific goal (biases test generation toward that area)
murphy --url https://example.com --goal "check if agent creation works"

# Site requires login — opens browser for manual auth first
murphy --url https://example.com --auth

# Public site, skip auth detection entirely
murphy --url https://example.com --no-auth

# Resume from previously generated/edited files
murphy --url https://example.com --features murphy/output/example_com_features.md
murphy --url https://example.com --plan murphy/output/test_plan.yaml
```

You can also run as a Python module:
```bash
python -m murphy --url https://example.com
```

## How It Works

Murphy runs three phases with human-in-the-loop pauses between each:

**Phase 1 — Analyze:** An AI agent navigates the site, discovers pages, and catalogs every user-facing feature. Saves `<site>_features.md`. Murphy pauses so you can review/edit the features file before continuing.

**Phase 2 — Generate Tests:** An LLM reads the features and produces test scenarios with steps and success criteria. Saves `test_plan.yaml`. Murphy pauses again for review/editing.

**Phase 3 — Execute:** An AI agent runs each test scenario in a real browser, and a judge LLM evaluates pass/fail. Saves `evaluation_report.json` and `evaluation_report.md`.

You can resume from any phase by passing `--features` or `--plan` with a previously generated (and optionally edited) file.

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
| `--goal` | | Free-text goal to bias test generation (e.g. `"check if agent creation works"`) |
| `--auth` | `false` | Skip auto-detection, go straight to manual login wait |
| `--no-auth` | `false` | Skip auth detection entirely, treat site as public |
| `--features` | | Path to existing features markdown (skips Phase 1) |
| `--plan` | | Path to existing YAML test plan (skips Phases 1 & 2) |
| `--max-tests` | `8` | Maximum number of test scenarios to generate |
| `--model` | `gpt-4o` | LLM model to use |
| `--output-dir` | `./murphy/output` | Output directory for all generated files |
| `--category` | | Site category hint (`ecommerce`, `saas`, `content`, `social`) |
| `--ui` | `false` | Launch interactive web UI instead of terminal output |
| `--no-highlights` | `false` | Disable bounding boxes on interactive elements in the browser |

## Interactive UI

Launch the web UI with:
```bash
murphy --url https://example.com --ui
```

The UI lets you watch test execution in real time, review results interactively, and re-run individual tests.

---

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details on the codebase structure, including the Murphy evaluation pipeline and the vendored browser-use engine.

---

## Development

### Setup

```bash
uv venv --python 3.11
source .venv/bin/activate
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
