# Vendored: browser-use

- **Upstream**: https://github.com/browser-use/browser-use
- **Based on**: upstream snapshot from ~November 2024 (vendored in commit 68201df6)
- **License**: MIT (see LICENSE in this directory)

## Local Modifications

1. **DOM watchdog toast capture** (`browser_use/browser/watchdogs/dom_watchdog.py`) — JavaScript observer that captures toast/snackbar notifications and surfaces them in browser state for test assertions.

2. **Toast messages in browser state** (`browser_use/browser/views.py`) — Added `toast_messages` field to `BrowserStateSummary`.

3. **Disabled-element safety checks** (`browser_use/browser/watchdogs/default_action_watchdog.py`) — Live CDP query (`_is_element_disabled_live()`) to prevent clicking disabled elements during multi-action sequences.

4. **Agent loop force-done** (`browser_use/agent/service.py`) — `_force_done_on_severe_loop()` method that terminates the agent when repetition >= 15 or stagnation >= 8.

5. **Escalated repetition warnings** (`browser_use/agent/views.py`) — More aggressive warning messages for detected loops.

6. **Scaled page-emptiness warnings** (`browser_use/agent/prompts.py`) — Warnings scale back after step 3 to reduce noise.

7. **CDP connection health check** (`browser_use/browser/session.py`) — Added `is_cdp_connected` property to expose CDP WebSocket state.

8. **Default headless mode** (`browser_use/browser/profile.py`) — Changed default `headless` from `None` to `True`.

9. **Custom Murphy tests** (`tests/browser_use/test_ai_step.py`, `tests/browser_use/test_rerun_ai_summary.py`) — Tests for `_execute_ai_step()` and `_generate_rerun_summary()` agent methods added for Murphy. These use mocked LLMs and mocked browser state (no real browser launch).

## Syncing with Upstream

```bash
bin/vendor-diff.sh              # diff local browser_use against upstream HEAD
bin/vendor-diff.sh v0.X.Y       # diff against a specific upstream tag
```
