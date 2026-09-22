# Spike 0 harness

> **Easiest way to run this: GitHub Codespaces.** Open the repository on
> GitHub, press `.` or use the green **Code** button → **Codespaces** → **Create
> codespace**. You get a working environment in a browser tab with Python,
> ffmpeg and every dependency already installed — nothing to install locally, on
> Windows or anywhere else. First creation takes a few minutes; after that it is
> instant. See `.devcontainer/` for what it sets up.
>
> **Running it locally on Windows instead?** `make` is a Unix tool and will not
> exist on your machine. Every `make X` below is a shortcut for a plain Python
> command, and the Python form works everywhere. The table in
> [Commands](#commands-make-vs-plain-python) gives both.

Answers the two questions in `docs/BUILD_ORDER.md` Section 3 — does the face
survive animation, and which golf formats render usably — with scripts and a
folder of files. No Postgres, no Redis, no FastAPI, no adapter protocols.

**Throwaway by design.** Nothing here is promoted to `app/` without being
rewritten against the adapter contract in `BUILD_PLAN.md` Section 5. The
deliverable is evidence, not software.

## Blocked before a real run

| Blocker | Resolve in |
|---|---|
| Face-embedding model + licence | `docs/decisions/0002-face-embedding-model-licence.md` |
| Provider access, current pricing | `config/spike.yaml`, findings recorded in `docs/decisions/` |
| LoRA base model licence | `config/spike.yaml` → `lora.*` |
| Spike budget ceiling | passed per command as `--budget` |

Every one of those is a `null` in `config/spike.yaml`, and the harness refuses
to run against any of them rather than defaulting to something plausible.

## Commands: make vs plain Python

`make` is a convenience on macOS and Linux. On Windows — or anywhere without
it — use the right-hand column. Run these from the root of the project folder
(the one containing `pyproject.toml`), not from your home directory.

| Shortcut | Works everywhere |
|---|---|
| `make fetch-models` | `python -m scripts.spike.cli fetch-models` |
| `make check-embedder` | `python -m scripts.spike.cli check-embedder` |
| `make demo` | `python -m scripts.spike.cli demo` |
| `make test` | `python -m pytest -q` |
| `make lint` | `python -m ruff check scripts tests` |
| `make types` | `python -m mypy` |
| `make check` | all three of the above, in order |

Minimum to run anything: `pip install numpy pillow pyyaml`. No install of this
project itself is needed — `python -m` picks it up from the current folder.

## Try it without a provider or a model

```bash
python -m scripts.spike.cli demo    # fixtures -> calibrate -> generate -> score -> report
```

Everything runs on stub backends. The stub embedder is **pixel statistics, not
face recognition**, and the fake providers emit coloured shapes, so the output
is stamped `THIS REPORT IS NOT EVIDENCE` and `report` refuses to write without
`--allow-fake`.

## Choosing the scorer (ADR 0002)

Two candidates are wired up, both free and self-hosted, because they are the
only routes commercially usable today without buying a licence.

```bash
pip install -e ".[dlib]"     # or ".[dinov2]", or both
python -m scripts.spike.cli fetch-models
```

`fetch-models` downloads each file, refuses anything that is really an error
page or a Git LFS pointer, checks the digest where one is pinned, and then
prints the licence for each one and the YAML to paste into `config/spike.yaml`.

It deliberately leaves `licence` and `licence_verified_on` blank. The gate in
`EmbedderConfig.require_usable` exists so that somebody read the text; a fetcher
that ticked it off would defeat the point of having it. Nothing runs until you
fill those two fields in.

```bash
python -m scripts.spike.cli bake-off --backends dlib dinov2
# or just one:
python -m scripts.spike.cli bake-off --backends dinov2
```

### Before any of that: does the scorer even work here?

```bash
make check-embedder
```

Downloads the model, embeds a handful of probe images and reports whether the
dimension matches config, the vectors are normalised, the same image twice
gives the same vector, variations of one identity score closer than two
identities, and how many milliseconds an embedding takes — translated into what
a real run will cost in wall-clock.

`--detector whole-image` skips face detection, to test the model on its own.
`--images <dir>` points it at real photographs, which is the only way to
exercise detection properly; the built-in probe images are coloured shapes.

It says plainly in its own output that it is a plumbing check and not evidence.
Passing it means the scorer runs. It says nothing about whether the scorer
separates real faces well enough to gate takes on — only calibration against a
real master set answers that.

`dlib` is a real face recognition model (128-d, public-domain weights).
`dinov2` is an Apache 2.0 general visual embedder applied to a cropped face —
**not** a face recogniser, deliberately: face models are trained to be invariant
to pose, lighting, expression, age and hairstyle, which is exactly the drift a
persona scorer needs to catch.

The bake-off calibrates both on the same data and ranks on distribution overlap,
then on true-positive rate. It will not let a stub backend win. Whichever
separates *your* data wins — published benchmarks measure real-identity
recognition, which is not the task.

## A real run

```bash
python -m scripts.spike.cli init-run --note "throwaway look A"
# put the master stills in <run>/master/ and a different-faces control set in <run>/control/
python -m scripts.spike.cli calibrate --target-fpr 0.01 --write-config
python -m scripts.spike.cli run-matrix    --budget 150 --video-slot flagship
python -m scripts.spike.cli battery       --budget 120
python -m scripts.spike.cli lipsync-probe --budget 20
python -m scripts.spike.cli contact-sheet
python -m scripts.spike.cli time --task S0.7 --minutes 90 --note "rating the battery"
python -m scripts.spike.cli report --out docs/reports/gate-a.md
```

`--budget` is mandatory on every command that can spend: there is no default
and no way to omit it. The guard refuses *before* the call, and records failed
calls too — a provider call that times out has still been paid for.

## Design decisions worth knowing

**A clip passes only if its worst frame clears the threshold *and* a face was
found in at least 90% of sampled frames.** Scoring over only the frames where a
face was detected would report a clean pass on a clip with a two-second hole in
it.

**Distribution overlap is reported before the threshold.** A threshold drawn
across two distributions that sit on top of each other is a number with no
meaning. `calibrate` stamps a verdict and says so plainly when the instrument
is not good enough — that outcome is a Gate A finding, not a failure to report.

**The contact sheet is the check on the instrument.** Look at the worst frame
of every clip marked PASS. If the scorer passes clips your eye rejects, the
scorer is the finding, and `BUILD_PLAN.md` task 3.4's auto-reject design needs
rework before it is built on top of it.

**Everything is stamped with the embedder that measured it.** Scoring with a
calibration from a different model or version raises rather than silently
comparing incomparable numbers (`BUILD_ORDER` amendment A3).

## Known limitations

- No real provider backend is implemented. Doing so requires verifying the
  provider's current API against official documentation first.
- The stub embedder is insensitive to whole-frame affine changes, because it
  mean-subtracts before normalising. Noted because it is the kind of blindness
  a real embedder can also have.
- **The DINOv2 model call is verified only up to the download.** torch,
  torchvision and transformers install, the embedder constructs, and `_load()`
  gets as far as an OSError reaching huggingface.co — which is the expected
  failure in an environment where that host is blocked, and confirms the
  transformers API usage is right. What has NOT run is the model itself, so the
  embeddings have never been computed. A Codespace has no egress restriction, so
  it will get further.
- **The dlib backend is entirely unverified** — dlib.net is blocked here too,
  and dlib builds from source. It is the fallback, not the chosen scorer.
- The YuNet detector IS verified: it downloads, its digest matches, and it loads
  and runs through `cv2.FaceDetectorYN`. Neither package was
  installable in the container this was written in (dlib builds from source and
  timed out; torch was not present). Everything around the call is tested — the
  licence and path gates, the detection contract, the crop geometry, the
  bake-off's refusal to let a stub win — but the embeddings themselves have not
  been computed. Run the bake-off before trusting either.
