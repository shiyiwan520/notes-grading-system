"""
pdf_reader.py — PDF 文字擷取模組
優先 pdfplumber，備援 PyMuPDF
"""

import io
from typing import Tuple, Optional


def extract_text_from_bytes(pdf_bytes: bytes) -> Tuple[str, Optional[str]]:
    """
    從 PDF bytes 擷取文字。
    回傳 (text, error_message)，成功時 error_message 為 None。
    """
    text = _try_pdfplumber(pdf_bytes)
    if text:
        return text, None
    text = _try_pymupdf(pdf_bytes)
    if text:
        return text, None
    return "", "Cannot extract text from this PDF. It may be a scanned image."


def _try_pdfplumber(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages_text).strip()
    except Exception:
        return ""


def _try_pymupdf(pdf_bytes: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages_text = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages_text).strip()
    except Exception:
        return ""
