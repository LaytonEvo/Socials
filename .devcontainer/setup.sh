#!/usr/bin/env bash
# Runs once when the Codespace is created.
#
# Ordered so the useful stuff arrives first: the harness and its test suite are
# installed and verified before the slow optional download starts. If the DINOv2
# install fails or times out, everything else still works and the message says
# exactly how to retry -- a half-built environment that looks broken is worse
# than one that tells you which half is missing.

set -uo pipefail

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
warn() { printf '\n\033[1;33m!! %s\033[0m\n' "$1"; }

say "Installing ffmpeg and make"
# apt-get update first: without it the package lists are empty and the install
# fails with a misleading "unable to locate package".
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg make

say "Installing the harness and its dev tools"
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"

say "Checking it works"
if python -m ruff check scripts tests && python -m mypy && python -m pytest -q; then
  CHECK_OK=1
else
  CHECK_OK=0
  warn "make check did not pass. The environment is built, but something is wrong."
fi

say "Installing DINOv2 (the chosen identity scorer) — this one is large"
# CPU-only torch on purpose. A Codespace has no GPU, and the default wheels
# pull in roughly 4GB of CUDA libraries that can never run -- measured, not
# guessed: a default install came to 5.8GB of site-packages, 4.1GB of it
# nvidia/ and triton/, with torch.cuda.is_available() False. That is a large
# bite out of a 32GB machine and a slow first boot for nothing.
# Falls back to the default index if the CPU one is unreachable.
if ! pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu; then
  warn "CPU-only torch index unreachable; falling back to default wheels (much larger)."
fi

if pip install --quiet -e ".[dinov2]"; then
  DINO_OK=1
else
  DINO_OK=0
  warn "DINOv2 did not install. Everything else works. Retry with:
      pip install -e \".[dinov2]\""
fi

cat <<'BANNER'

────────────────────────────────────────────────────────────────────────
  Persona Studio — Spike 0

  Ready. Two things you can do right now, both free and offline:

    make demo
        Runs the whole harness end to end on fake data. Nothing is
        downloaded, nothing is spent. Good for seeing the shape of it.

    make check
        Lint, type-check and the full test suite.

  When you want the real scorer (needs internet, downloads the model):

    python -m scripts.spike.cli fetch-models --backend dinov2
        Fetches the face detector, then tells you what to put in
        config/spike.yaml.

  Read docs/BUILD_ORDER.md section 3 for what Spike 0 is actually for,
  and scripts/spike/README.md for how the pieces fit together.
────────────────────────────────────────────────────────────────────────

BANNER

[ "$CHECK_OK" = 1 ] || warn "Reminder: make check failed above."
[ "$DINO_OK" = 1 ] || warn "Reminder: DINOv2 is not installed."
exit 0
