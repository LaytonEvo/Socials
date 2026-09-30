"""Bundle the LoRA numbers the overview page shows into a file it can ship with.

The run outputs live under `spike/runs/`, excluded from git and from the deployment
build context because they hold gigabytes of imagery. The page needs about twenty
numbers out of that. Without bundling them the section works on a developer checkout and
silently disappears once deployed, which is the worst of both.

Run after any training or evaluation run: `python scripts/bundle_lora_summary.py`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.api.main import LORA_SUMMARY, _lora_run  # noqa: E402


def main() -> int:
    LORA_SUMMARY.unlink(missing_ok=True)  # so the reader falls through to the run files
    run = _lora_run()
    if run is None:
        print("no LoRA run found under spike/runs/lora — nothing to bundle")
        return 1
    LORA_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    LORA_SUMMARY.write_text(json.dumps(run, indent=2) + "\n")
    print(f"wrote {LORA_SUMMARY.relative_to(ROOT)} — {len(run['runs'])} evaluation runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
