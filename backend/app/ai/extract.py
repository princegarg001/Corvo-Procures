"""Plain-text extraction from amendment documents: PDF (pdfplumber), DOCX (python-docx), TXT/MD."""

from __future__ import annotations

import io
import logging


class ExtractError(ValueError):
    pass


def extract_text(data: bytes, filename: str) -> str:
    name = filename.lower()
    if data.startswith(b"%PDF") or name.endswith(".pdf"):
        import pdfplumber

        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
        except Exception as exc:
            raise ExtractError(f"could not read the PDF: {exc}") from exc
        text = "\n".join(pages)
    elif data.startswith(b"PK") or name.endswith(".docx"):
        import docx

        try:
            doc = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise ExtractError(f"could not read the Word document: {exc}") from exc
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        text = "\n".join(parts)
    else:
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ExtractError("could not decode the text file")
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise ExtractError("the document contains no readable text (is it a scanned image?)")
    return text
