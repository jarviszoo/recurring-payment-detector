"""
CLI for uploading an email and getting an analysis back.

Accepts .txt, .eml, .pdf, .png, .jpg, .jpeg, .bmp, .tiff, .webp
(plus arbitrary text piped via stdin).

Usage:
    python email_demo.py path/to/email.txt
    python email_demo.py invoice.pdf receipt.png
    cat email.txt | python email_demo.py
    python email_demo.py            # runs the bundled samples in sample_emails/
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from pathlib import Path

import email_evaluator
import email_loader

SAMPLE_DIR = Path(__file__).parent / "sample_emails"


def evaluate_path(path: Path) -> None:
    kind = email_loader.detect_kind(path)
    print(f"\n>>> File: {path}  ({kind})")
    try:
        text = email_loader.load(path)
    except email_loader.OcrUnavailable as e:
        print(f"  [SKIP] {path.name}: OCR unavailable.")
        print()
        for line in str(e).splitlines():
            print(f"      {line}")
        return
    except email_loader.LoaderError as e:
        print(f"  [ERR] {path.name}: {e}")
        return

    if kind != "text":
        # Show the OCR / extracted text so the user can sanity-check it
        preview = "\n".join(line for line in text.splitlines() if line.strip())[:400]
        print(f"  --- extracted text preview ({len(text)} chars) ---")
        for line in preview.splitlines():
            print(f"      {line}")
        print("  --- end preview ---")

    ev = email_evaluator.evaluate_email(text)
    print(email_evaluator.format_report(ev))


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args:
        for a in args:
            p = Path(a)
            if not p.exists():
                print(f"  [ERR] {a} not found", file=sys.stderr)
                continue
            evaluate_path(p)
        return 0

    # Stdin
    if not sys.stdin.isatty():
        text = sys.stdin.read()
        ev = email_evaluator.evaluate_email(text)
        print(email_evaluator.format_report(ev))
        return 0

    # Auto-demo bundled samples
    if SAMPLE_DIR.exists():
        patterns = ["*.txt", "*.eml", "*.pdf", "*.png", "*.jpg", "*.jpeg"]
        files: list[Path] = []
        for pat in patterns:
            files.extend(SAMPLE_DIR.glob(pat))
        files = sorted(set(files))
        if not files:
            print(f"No sample files found in {SAMPLE_DIR}.")
            return 1
        print(f"Running on bundled samples in {SAMPLE_DIR} ({len(files)} files):")
        for f in files:
            evaluate_path(f)
        print()
        if not email_loader.ocr_available():
            print("Note: OCR backend is not configured, so any image samples were skipped.")
            print("See the [SKIP] messages above for setup instructions.")
        return 0

    print("Usage: python email_demo.py <file> [more files ...] | <piped stdin>")
    print(f"Supported: {sorted(email_loader.TEXT_SUFFIXES | email_loader.PDF_SUFFIXES | email_loader.IMAGE_SUFFIXES)}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
