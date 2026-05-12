"""
Renders the existing sample_emails/*.txt files into PDF and PNG attachments
so the multi-format loader can be tested end-to-end.

Run once:
    python generate_sample_attachments.py
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from pathlib import Path

SAMPLE_DIR = Path(__file__).parent / "sample_emails"


def render_pdf(text: str, out_path: Path) -> None:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    c = canvas.Canvas(str(out_path), pagesize=letter)
    width, height = letter
    margin = 50
    y = height - margin
    c.setFont("Courier", 11)
    for line in text.splitlines() or [""]:
        if y < margin:
            c.showPage()
            c.setFont("Courier", 11)
            y = height - margin
        c.drawString(margin, y, line[:120])
        y -= 14
    c.save()


def render_png(text: str, out_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    # Estimate width/height
    lines = text.splitlines() or [""]
    char_w, char_h = 8, 16
    width = max(600, char_w * max((len(l) for l in lines), default=40) + 60)
    height = char_h * len(lines) + 60

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # Try a real TTF; fall back to PIL's bitmap default
    font = None
    for candidate in (
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\cour.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        try:
            font = ImageFont.truetype(candidate, 14)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    y = 30
    for line in lines:
        draw.text((30, y), line, fill="black", font=font)
        y += char_h
    img.save(str(out_path))


def main() -> int:
    if not SAMPLE_DIR.exists():
        print(f"{SAMPLE_DIR} does not exist.")
        return 1

    txt_files = sorted(SAMPLE_DIR.glob("*.txt"))
    if not txt_files:
        print(f"No .txt samples found in {SAMPLE_DIR}.")
        return 1

    for txt in txt_files:
        text = txt.read_text(encoding="utf-8")
        pdf_out = txt.with_suffix(".pdf")
        png_out = txt.with_suffix(".png")
        render_pdf(text, pdf_out)
        render_png(text, png_out)
        print(f"  rendered {txt.name} -> {pdf_out.name}, {png_out.name}")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
