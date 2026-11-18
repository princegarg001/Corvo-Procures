"""Batch processing and runs: POST /api/process-batch, /api/runs, exports and comparison."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..services import run_service
from .deps import actor, db, decode_text, read_upload

router = APIRouter(prefix="/api", tags=["batch"])


def _csv(text: str, filename: str) -> PlainTextResponse:
    return PlainTextResponse(text, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/process-batch", summary="Process a PR batch CSV and return the decisions")
async def process_batch(
    request: Request,
    policy_version: str | None = Query(None, description="Pin a policy version, e.g. 5.0 (reproduces Run 1)"),
    format: Literal["json", "csv"] = Query("json"),
    name: str | None = Query(None, description="Run name shown in the app"),
    session: Session = Depends(db),
    user: str = Depends(actor),
) -> object:
    """Multipart `file` **or** a raw `text/csv` body. Stateless w.r.t. contract ceilings:
    every batch starts from the contract register baseline (decision D14)."""
    data, filename, fields = await read_upload(request)
    text = decode_text(data)
    try:
        run, result = run_service.process_batch(
            session, text, name=name or fields.get("name") or filename or "API batch", filename=filename,
            pin=policy_version or fields.get("policy_version") or None, actor=user)
    except run_service.BatchError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:  # e.g. unknown pinned version
        raise HTTPException(422, str(exc)) from exc
    if format == "csv":
        return _csv(run.output_csv, f"decisions_run{run.id}.csv")
    return {
        "run_id": run.id, "policy_versions_used": result.versions_used, "summary": result.summary,
        "decisions": run_service.rows_of(run),
    }


@router.get("/runs")
def list_runs(session: Session = Depends(db)) -> list[dict[str, object]]:
    return run_service.list_runs(session)


@router.get("/runs/compare")
def compare(a: int, b: int, session: Session = Depends(db)) -> dict[str, object]:
    return run_service.compare_runs(session, a, b)


@router.get("/runs/compare/export.csv")
def compare_csv(a: int, b: int, session: Session = Depends(db)) -> PlainTextResponse:
    return _csv(run_service.compare_csv(run_service.compare_runs(session, a, b)), f"compare_run{a}_vs_run{b}.csv")


@router.get("/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(db)) -> dict[str, object]:
    return run_service.result_json(run_service.get_run(session, run_id))


@router.get("/runs/{run_id}/export.csv")
def export_run(run_id: int, session: Session = Depends(db)) -> PlainTextResponse:
    run = run_service.get_run(session, run_id)
    return _csv(run.output_csv, f"decisions_run{run.id}.csv")


@router.get("/runs/{run_id}/input.csv")
def export_input(run_id: int, session: Session = Depends(db)) -> PlainTextResponse:
    run = run_service.get_run(session, run_id)
    return _csv(run.input_text, run.input_file or f"input_run{run.id}.csv")
