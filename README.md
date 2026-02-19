# Murphy — AI-Driven Website Evaluation

Murphy is a 3-phase agent that automatically evaluates websites: **analyze** the site to discover features, **generate** test scenarios, then **execute** them with an AI browser agent. It produces structured evaluation reports with pass/fail results, failure categorization, and actionable summaries.

Built on top of [browser-use](README_browseruse.md) (AI browser automation library).

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
cd browser-use
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
docker build . -t browseruse --no-cache
```

**2. Create `.env` with your API key** (same as above).

**3. Run via the helper script:**
```bash
./murphy/run.sh https://example.com [options]
```

The script mounts `murphy/` and `.env` into the container and runs `python -m murphy` with your arguments.

## Usage

```bash
# Full run: auto-detect auth → analyze site → generate tests → execute
murphy --url https://example.com

# With a specific goal (biases test generation toward that area)
murphy --url https://work.toqan.ai --goal "check if agent creation works"

# Site requires login — opens browser for manual auth first
murphy --url https://work.toqan.ai --auth

# Public site, skip auth detection entirely
murphy --url https://example.com --no-auth

# Resume from previously generated/edited files
murphy --url https://work.toqan.ai --features murphy/output/work_toqan_ai_features.md
murphy --url https://work.toqan.ai --plan murphy/output/test_plan.yaml
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

Requires the `cli` extra:
```bash
uv sync --extra cli
```

The UI lets you watch test execution in real time, review results interactively, and re-run individual tests.
