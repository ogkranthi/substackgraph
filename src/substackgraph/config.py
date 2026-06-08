"""Central configuration. Constants only — no logic, no side effects on import."""

import os
from pathlib import Path

# Project root (this file is src/substackgraph/config.py → parents[2] is the repo root).
ROOT = Path(__file__).resolve().parents[2]

# Writable artifacts root. Defaults to the repo for dev checkouts, but is overridable
# because an installed package resolves ROOT to a read-only site-packages dir — a
# deployment must point this (and SUBSTACKGRAPH_DB) at a writable volume.
ARTIFACTS = Path(os.getenv("SUBSTACKGRAPH_ARTIFACTS", ROOT / "artifacts"))
# Cache path is overridable so a deployment can point at a mounted volume.
DB_PATH = Path(os.getenv("SUBSTACKGRAPH_DB", ARTIFACTS / "cache.sqlite"))
LOG_DIR = ARTIFACTS / "logs"
LOG_PATH = LOG_DIR / "decisions.jsonl"
GRAPHS_DIR = ARTIFACTS / "graphs"
SCREENSHOTS_DIR = GRAPHS_DIR / "screenshots"

# Non-negotiable politeness / ToS guard: at most one request per second to Substack.
RATE_LIMIT_S = 1.0

# Confidence at or above which two candidate nodes may be merged. Below this the
# harness refuses and flags for review rather than guessing.
#
# Tuning rationale (Episode 1, 2026-06-08):
#   - same_id merges score 1.0 (only valid same-pub merge)
#   - shared_author_only scores ~0.3 (must never be enough)
#   - max shared_author + identical_name = 0.3 + 0.2 = 0.5
#   - 0.85 leaves a 0.35 gap above the worst false-positive scenario
#   - Example refusal: "The VC Corner" vs "The Founders Corner" (shared author 95342670,
#     name similarity 0.67, total score 0.43 < 0.85 → refused)
MERGE_THRESHOLD = 0.85


def ensure_dirs() -> None:
    """Create the runtime artifact directories. Called by the CLI, not on import."""
    for d in (ARTIFACTS, LOG_DIR, GRAPHS_DIR, SCREENSHOTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
