# Deploying the read-only view

**Date:** 2026-09-29
**Why:** the owner asked to see the app before authorising a training run.
**Status:** build fixed and verified locally; deploy in progress. Two duplicate services
need removing by hand.

## What is deployed

`app/api/main.py` — the read-only overview built in the previous task. It reads
`config/` and the filesystem, not the database, so it runs anywhere the repository is
checked out and needs neither Postgres nor Redis nor dlib.

- Project: **Persona Studio** (`a494b08b-806b-4e2a-ad01-c9be24c61136`)
- Environment: **production** (`1aa8d851-d7d7-4a45-a6b0-0e389958adeb`)
- Service: **web** (`70f36765-f2e6-43be-bde9-6a3ecf8e1f8f`)
- Domain: `web-production-6192.up.railway.app`
- Bucket: **persona-media**, sjc (`60ab9a39-14cd-4617-a80e-f764c4bef818`)

## Three deploys reported SUCCESS and did not serve

Worth recording, because a green build that crash-loops is the failure mode most likely
to be mistaken for a working deploy.

| # | Commit | Reported | Actually |
|---|--------|----------|----------|
| 1 | `2e306e4` | SUCCESS | `uvicorn: command not found` |
| 2 | `a91b17a` | SUCCESS | `No module named uvicorn`, from `/mise/installs/python/3.13.15/bin/python` |
| 3 | `6b56097` | — | verified locally before pushing |

**Root cause.** The service builds with **Railpack**, and a setuptools
`pyproject.toml` with no lockfile is not a Python detection trigger for it. Railpack
installed an interpreter, installed no packages, produced an image, and reported
success. Nothing in the build output said the dependency step had been skipped.

Deploy 2 was my own wrong fix: I wrote a `nixpacks.toml` without checking which builder
the service used. `get-service-config` says `"builder": "RAILPACK"`, so that file was
never read — the second failure names mise's interpreter rather than the `/opt/venv` the
file was meant to create, which is what gave it away. The file is now removed rather
than left in the tree implying a build step that does not run.

**Fix.** A `requirements.txt` containing a single dot. Railway's documentation states
Railpack detects Python from `requirements.txt`, so this is a documented trigger rather
than an inference. The dot installs this project, which resolves its own dependencies
from `pyproject.toml`, so the dependency set still lives in exactly one place. A literal
package list there would drift from the real one silently, which is a worse bug than the
one it fixes.

Also `--port ${PORT:-8080}` in the `Procfile`. An unset `PORT` makes uvicorn exit 2 with
`Option '--port' requires an argument` — in a deploy log that reads like a crash rather
than a missing variable. Railway sets `PORT`, so the fallback should never be used.

## How deploy 3 was verified before pushing

No Docker is available in the build container, so the image itself could not be built
locally. The install and start path were reproduced instead:

1. Fresh venv, `pip install -r requirements.txt` and nothing else → uvicorn present.
2. The `Procfile` command run verbatim against that venv, with `PORT` set as Railway
   sets it → `Application startup complete`.
3. `GET /` → **200**, page contains Mollie and the 0.9619 threshold.
4. `GET /reference/...` → **200 image/png**.
5. `GET /reference/../../etc/passwd` → **404**, refused.
6. `make check` → green, 482 passed, 79 skipped.

Steps 1 and 2 are the two that the previous deploys failed, and neither had been run
before pushing them. That was the actual mistake; the builder confusion followed from it.

## Open, needs the owner

- **Apply the staged service deletions.** `Socials` (`2bf4692e-…`) and `virtuous-art`
  (`66ca4ecb-…`), both created by me in error, are **staged for deletion** and need one
  Apply in the dashboard. Deleting a service requires two-factor verification, which an
  API token cannot perform — that is why `delete-service` timed out four times rather
  than reporting a permission error. Keep **web**; it holds the domain.

  This is now blocking, not cosmetic. All three services point at the same repository and
  branch, so the two pushes here queued six deployments. The workspace will not run six
  builds at once, so every one of them sits in INITIALIZING and nothing proceeds — with
  zero failures reported, which makes it look like a slow build rather than a jam.
  Applying the patch cancels the four deployments belonging to the deleted services and
  should let web's build through.
- **Bucket credentials.** `persona-media` exists, but Railway does not expose its
  credentials through the API. They need copying from the dashboard into the environment
  before anything can write to it, the same route the fal key took. Nothing uses the
  bucket yet, so this is not blocking the view.

## What this view is not

It shows state, and it changes none. It has no write path, so it cannot get publishing
or disclosure wrong; those rules live in the schema and the config loader, both upstream
of it. The content review UI is task 3.5 and reviews content that does not exist yet.
