"""A read-only view of the system — the earliest thing an owner can actually look at.

**This is not task 3.5.** The review UI that task specifies has a queue by content piece,
side-by-side takes, a scrub bar with per-frame identity scores, accept/reject/rate/tag
and keyboard shortcuts, behind auth for named operators. None of that is here, because
none of the things it reviews exist yet — no content pieces, no takes, no renders.

What this does is show what the system currently holds: who Mollie is, which decisions
are made and which are not, the reference set her identity is calibrated against, and
what has been spent. It is read-only by design. Nothing here can change state, so it
cannot get publishing or disclosure wrong — the rules that matter are enforced in the
schema and the config loader, and this view is downstream of both.

It reads config and the filesystem rather than the database, so it runs anywhere the
repository is checked out. Spend appears when a database is reachable and is reported as
unavailable when it is not, rather than shown as zero.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Config, is_pending, load_all

HERE = Path(__file__).resolve().parent
UI = HERE.parent / "ui"
REPO = HERE.parent.parent
REFERENCE_ROOT = REPO / "spike" / "data"

app = FastAPI(title="Persona Studio", docs_url="/api/docs", redoc_url=None)
templates = Jinja2Templates(directory=str(UI / "templates"))
if (UI / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(UI / "static")), name="static")


def _config() -> Config:
    return load_all(REPO / "config")


def _reference_sets() -> list[dict[str, Any]]:
    """The four directories the centroid is built from, and what is in them."""
    cfg = _config()
    look = cfg.persona.persona.look
    names = getattr(look, "reference_sets", None) or ["master_v2"]
    suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    out: list[dict[str, Any]] = []
    for name in names:
        directory = REFERENCE_ROOT / name
        files = (
            sorted(p.name for p in directory.iterdir() if p.suffix.lower() in suffixes)
            if directory.is_dir()
            else []
        )
        out.append({"name": name, "count": len(files), "files": files})
    return out


def _decisions(cfg: Config) -> list[dict[str, Any]]:
    """Which of BUILD_PLAN Section 1's human decisions are made, and which are not."""
    persona = cfg.persona.persona
    budget = cfg.budget.budget
    criteria = cfg.kill_criteria.kill_criteria
    name_decided = not is_pending(persona.name)
    return [
        {
            "id": "D1",
            "what": "Persona name, look, backstory, voice",
            "state": "decided" if name_decided else "outstanding",
            "detail": f"{persona.name} · look {look_status(cfg)} · voice {persona.voice.provider}"
            if name_decided
            else "name still pending",
        },
        {
            "id": "D4",
            "what": "Financial products",
            "state": "decided",
            "detail": "permanently out of scope, enforced by the policy guard",
        },
        {
            "id": "D5",
            "what": "Kill criteria",
            "state": "outstanding",
            "detail": "thresholds pending, including operator minutes per piece",
        }
        if is_pending(criteria.economics.max_operator_minutes_per_piece)
        else {"id": "D5", "what": "Kill criteria", "state": "decided", "detail": "set"},
        {
            "id": "D8",
            "what": "Budget ceilings",
            "state": "decided",
            "detail": f"mode {budget.mode} — observe first, no ceiling set yet",
        },
        {
            "id": "D3 / D6 / D7",
            "what": "Owning entity, named operator, counsel sign-off",
            "state": "outstanding",
            "detail": "all three block publishing rather than building",
        },
    ]


def look_status(cfg: Config) -> str:
    return cfg.persona.persona.look.status


def _spend() -> dict[str, Any]:
    """Spend to date, or an honest note that the ledger is unreachable."""
    if not os.environ.get("DATABASE_URL", "").strip():
        return {"available": False, "reason": "no database configured"}
    try:
        from app.costs import spend_this_month, spend_total
        from app.models import make_engine, session_scope

        engine = make_engine()
        with session_scope(engine) as session:
            return {
                "available": True,
                "total": str(spend_total(session)),
                "month": str(spend_this_month(session)),
            }
    except Exception as exc:  # the view reports, it does not crash
        return {"available": False, "reason": f"{type(exc).__name__}"}


@app.get("/", response_class=HTMLResponse)
def overview(request: Request) -> Any:
    cfg = _config()
    persona = cfg.persona.persona
    sets = _reference_sets()
    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            "persona": persona,
            "look": persona.look,
            "reference_sets": sets,
            "reference_total": sum(s["count"] for s in sets),
            "decisions": [d for d in _decisions(cfg) if d],
            "formats": cfg.content_policy.allowed_formats,
            "blocked": cfg.content_policy.blocked_formats,
            "lora": cfg.providers.lora,
            "budget": cfg.budget.budget,
            "spend": _spend(),
            "providers": cfg.providers.providers,
        },
    )


@app.get("/reference/{set_name}/{filename}")
def reference_image(set_name: str, filename: str) -> Any:
    """Serve one reference still.

    Both parts are checked against what is actually on disk rather than sanitised,
    because a path that is rewritten rather than refused is how a traversal becomes a
    silent read of something else.
    """
    known = {s["name"] for s in _reference_sets()}
    if set_name not in known:
        return JSONResponse({"error": "unknown reference set"}, status_code=404)
    path = (REFERENCE_ROOT / set_name / filename).resolve()
    if path.parent != (REFERENCE_ROOT / set_name).resolve() or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Enough to tell a deployment apart from a working one."""
    cfg = _config()
    return {
        "status": "ok",
        "persona": str(cfg.persona.persona.name),
        # Files on disk. Three in master_v2 carry no detectable face and are not
        # part of the 121 the centroid is built from, so this is deliberately not
        # called the reference count.
        "reference_files": sum(s["count"] for s in _reference_sets()),
        "identity_threshold": cfg.persona.persona.look.identity_threshold,
        "budget_mode": cfg.budget.budget.mode,
        "database": _spend()["available"],
    }
