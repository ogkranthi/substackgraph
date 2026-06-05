"""Central configuration. Constants only — no logic, no side effects on import."""

from pathlib import Path

# Project root (this file is src/substackgraph/config.py → parents[2] is the repo root).
ROOT = Path(__file__).resolve().parents[2]

ARTIFACTS = ROOT / "artifacts"
DB_PATH = ARTIFACTS / "cache.sqlite"
LOG_DIR = ARTIFACTS / "logs"
LOG_PATH = LOG_DIR / "decisions.jsonl"
GRAPHS_DIR = ARTIFACTS / "graphs"
SCREENSHOTS_DIR = GRAPHS_DIR / "screenshots"

# Non-negotiable politeness / ToS guard: at most one request per second to Substack.
RATE_LIMIT_S = 1.0

# Confidence at or above which two candidate nodes may be merged. Below this the
# harness refuses and flags for review rather than guessing.
MERGE_THRESHOLD = 0.85


def ensure_dirs() -> None:
    """Create the runtime artifact directories. Called by the CLI, not on import."""
    for d in (ARTIFACTS, LOG_DIR, GRAPHS_DIR, SCREENSHOTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
