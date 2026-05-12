"""
CLI for uploading an email (file path or stdin) and getting an analysis back.

Usage:
    python email_demo.py path/to/email.txt
    python email_demo.py path/to/email.txt path/to/another.txt
    cat email.txt | python email_demo.py
    python email_demo.py            # runs the bundled samples in sample_emails/
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from pathlib import Path
import email_evaluator


SAMPLE_DIR = Path(__file__).parent / "sample_emails"


def evaluate_path(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    print(f"\n>>> File: {path}")
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

    # Stdin if piped
    if not sys.stdin.isatty():
        text = sys.stdin.read()
        ev = email_evaluator.evaluate_email(text)
        print(email_evaluator.format_report(ev))
        return 0

    # Otherwise demo every file in sample_emails/
    if SAMPLE_DIR.exists():
        files = sorted(SAMPLE_DIR.glob("*.txt"))
        if not files:
            print(f"No sample emails found in {SAMPLE_DIR}.")
            return 1
        print(f"Running on bundled samples in {SAMPLE_DIR} ({len(files)} files):")
        for f in files:
            evaluate_path(f)
        return 0

    print("Usage: python email_demo.py <email.txt> [more.txt ...] | <piped stdin>")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
