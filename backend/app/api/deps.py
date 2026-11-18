"""Shared API dependencies: DB session, acting user (X-User header from the role switcher)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session


def db() -> Iterator[Session]:
    yield from get_session()


def actor(x_user: str | None = Header(default=None, alias="X-User")) -> str:
    """Real authentication is out of scope (PLAN §10); the UI sends the selected demo user."""
    name = (x_user or "").strip()
    return name[:80] if name else "api"


async def read_upload(request: Request, field: str = "file") -> tuple[bytes, str | None, dict[str, str]]:
    """Read a multipart file field or a raw request body; enforce the upload size limit."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    ctype = request.headers.get("content-type", "")
    form_fields: dict[str, str] = {}
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get(field)
        for k, v in form.items():
            if isinstance(v, str):
                form_fields[k] = v
        if upload is None or isinstance(upload, str):
            raise HTTPException(422, f"multipart field '{field}' (a file) is required")
        data = await upload.read()
        name = upload.filename
    else:
        data = await request.body()
        name = None
    if len(data) > limit:
        raise HTTPException(413, f"upload larger than {get_settings().max_upload_mb} MB")
    if not data:
        raise HTTPException(422, "empty upload")
    return data, name, form_fields


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(422, "could not decode the file as text")
