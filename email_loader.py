"""
Multi-format email loader.

Accepts a path to one of:
  - .txt / .eml          -> read as UTF-8 text
  - .pdf                 -> extract text with pypdf; OCR fallback for scanned PDFs
  - .png/.jpg/.jpeg/.bmp -> OCR via pytesseract (requires Tesseract binary)

Returns plain text the email_parser can ingest. OCR support degrades gracefully
when Tesseract isn't installed — the loader raises OcrUnavailable with
actionable setup instructions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LoaderError(RuntimeError):
    pass


class OcrUnavailable(LoaderError):
    """Raised when an image (or scanned PDF) needs OCR but Tesseract is missing."""


class UnsupportedFormat(LoaderError):
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

TEXT_SUFFIXES   = {".txt", ".eml", ".text", ".msg"}
PDF_SUFFIXES    = {".pdf"}
IMAGE_SUFFIXES  = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}


def load(path: Path) -> str:
    """Read any supported file type and return its plain-text content."""
    path = Path(path)
    if not path.exists():
        raise LoaderError(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix in TEXT_SUFFIXES:
        return _read_text(path)

    if suffix in PDF_SUFFIXES:
        return _read_pdf(path)

    if suffix in IMAGE_SUFFIXES:
        return _ocr_image(path)

    raise UnsupportedFormat(
        f"Unsupported file type {suffix!r}. "
        f"Supported: {sorted(TEXT_SUFFIXES | PDF_SUFFIXES | IMAGE_SUFFIXES)}"
    )


def detect_kind(path: Path) -> str:
    """Return 'text', 'pdf', 'image', or 'unsupported' for the given path."""
    suffix = Path(path).suffix.lower()
    if suffix in TEXT_SUFFIXES:  return "text"
    if suffix in PDF_SUFFIXES:   return "pdf"
    if suffix in IMAGE_SUFFIXES: return "image"
    return "unsupported"


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise LoaderError(f"Could not decode {path} as text.")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

# Below this many extracted characters we assume the PDF is image-based and fall back to OCR
_PDF_MIN_TEXT_CHARS = 40


def _read_pdf(path: Path) -> str:
    try:
        import pypdf
    except ImportError as e:
        raise LoaderError(
            "PDF reading requires `pypdf`. Install with: pip install pypdf"
        ) from e

    reader = pypdf.PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    text = "\n".join(parts).strip()

    if len(text) >= _PDF_MIN_TEXT_CHARS:
        return text

    # Probably a scanned / image-based PDF. Try OCR each page if available.
    return _ocr_pdf(path)


def _ocr_pdf(path: Path) -> str:
    """OCR each page of a scanned PDF by rasterising via pypdf + PIL."""
    backend = _get_ocr_backend()
    if backend is None:
        raise OcrUnavailable(_ocr_setup_message())

    try:
        import pypdf
        from PIL import Image
        import io
    except ImportError as e:
        raise LoaderError(
            "Image-based PDF OCR requires pypdf and Pillow. "
            "Install with: pip install pypdf Pillow"
        ) from e

    reader = pypdf.PdfReader(str(path))
    pieces: list[str] = []
    for page in reader.pages:
        for image in page.images:
            try:
                pil_img = Image.open(io.BytesIO(image.data))
                pieces.append(backend(pil_img))
            except Exception:
                continue

    text = "\n".join(p for p in pieces if p).strip()
    if not text:
        raise LoaderError(
            f"Could not extract text from {path}. The PDF may be encrypted "
            "or contain non-OCR-able imagery."
        )
    return text


# ---------------------------------------------------------------------------
# Image OCR
# ---------------------------------------------------------------------------

def _ocr_image(path: Path) -> str:
    backend = _get_ocr_backend()
    if backend is None:
        raise OcrUnavailable(_ocr_setup_message())

    from PIL import Image
    img = Image.open(str(path))
    text = backend(img)
    if not text.strip():
        raise LoaderError(f"OCR returned no text for {path}.")
    return text


# ---------------------------------------------------------------------------
# OCR backend detection
# ---------------------------------------------------------------------------

# Common Windows install locations for the Tesseract binary
_TESSERACT_WIN_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%USERPROFILE%\AppData\Local\Tesseract-OCR\tesseract.exe"),
]


def _get_ocr_backend():
    """Return a callable Image -> str, or None if no OCR backend is available."""
    try:
        import pytesseract
    except ImportError:
        return None

    # Allow user override via TESSERACT_CMD env var
    override = os.environ.get("TESSERACT_CMD")
    if override and Path(override).exists():
        pytesseract.pytesseract.tesseract_cmd = override
        return lambda img: pytesseract.image_to_string(img)

    # Auto-detect common Windows install paths
    for candidate in _TESSERACT_WIN_PATHS:
        if Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return lambda img: pytesseract.image_to_string(img)

    # Trust PATH
    try:
        import subprocess
        subprocess.run(["tesseract", "--version"],
                       capture_output=True, check=True, timeout=5)
        return lambda img: pytesseract.image_to_string(img)
    except Exception:
        return None


def _ocr_setup_message() -> str:
    return (
        "OCR is required to read this file but Tesseract is not installed.\n"
        "\n"
        "Install on Windows:\n"
        "  Option A (recommended): download installer from\n"
        "    https://github.com/UB-Mannheim/tesseract/wiki\n"
        "    and run it. Default install path is auto-detected.\n"
        "  Option B (admin):  winget install UB-Mannheim.TesseractOCR\n"
        "  Option C: set TESSERACT_CMD env var to your tesseract.exe path.\n"
        "\n"
        "After installing, re-run the same command. Plain-text and digital "
        "PDFs work without Tesseract."
    )


def ocr_available() -> bool:
    """Quick check for callers that want to gate behaviour."""
    return _get_ocr_backend() is not None
