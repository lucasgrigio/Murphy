"""Murphy — shared constants and defaults."""

DEFAULT_MAX_STEPS = 30
DEFAULT_MAX_TESTS = 8
DEFAULT_MAX_ACTIONS_PER_STEP = 3
QUALITY_MAX_RETRIES = 2

# Per-endpoint job timeouts (seconds)
JOB_TIMEOUT_ANALYZE = 300       # 5 min — single browser exploration
JOB_TIMEOUT_GENERATE_PLAN = 180 # 3 min — pure LLM, no browser
JOB_TIMEOUT_EXECUTE = 1800      # 30 min — runs multiple tests (160-621s each)
JOB_TIMEOUT_EVALUATE = 600      # 10 min — exploration + plan synthesis
