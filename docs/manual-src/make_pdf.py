# -*- coding: utf-8 -*-
"""Render docs/digital-multitool-manual.html to a navigable PDF.

Stages:
1. A print variant of the HTML is written to build/ with every <details>
   forced open, so the PDF carries the full control tables.
2. Headless Edge prints it to PDF (A4, print stylesheet in the HTML keeps
   sections on their own pages and the clickable contents page working).
3. pypdf + reportlab post-process: chapter bookmarks for the PDF viewer's
   sidebar (the "sticky nav" of a PDF), a running footer with the current
   section and page number, and document metadata.

Needs: pip install pypdf reportlab   (plus Microsoft Edge on the machine).
"""
import io
import json
import os
import subprocess
import sys
import tempfile

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

_HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(_HERE, "build")
HTML = os.path.join(os.path.dirname(_HERE), "digital-multitool-manual.html")
OUT = os.path.join(os.path.dirname(_HERE), "digital-multitool-manual.pdf")

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

TITLE = "Digital Multitool — User Manual"


def render_raw_pdf():
    html = open(HTML, encoding="utf-8").read()
    html = html.replace("<details>", "<details open>")
    print_html = os.path.join(BUILD, "print.html")
    with open(print_html, "w", encoding="utf-8") as f:
        f.write(html)

    edge = next((p for p in EDGE_PATHS if os.path.exists(p)), None)
    if not edge:
        sys.exit("Microsoft Edge not found — install it or add its path "
                 "to EDGE_PATHS.")
    raw = os.path.join(BUILD, "manual_raw.pdf")
    if os.path.exists(raw):
        os.remove(raw)
    # Separate user-data-dir so this works while normal Edge is running.
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [edge, "--headless=new", "--disable-gpu",
             f"--user-data-dir={profile}", "--no-pdf-header-footer",
             f"--print-to-pdf={raw}",
             "file:///" + print_html.replace("\\", "/")],
            check=True, timeout=300)
    if not os.path.exists(raw):
        sys.exit("Edge did not produce a PDF.")
    return raw


def find_section_pages(reader, sections):
    """Map each section title to the page it starts on.

    Sections start on a fresh page (break-before:page), so the title sits in
    the first characters of its page's text. The cover/contents page lists
    every title, so any page containing 4+ titles is skipped.
    """
    page_texts = [(p.extract_text() or "") for p in reader.pages]
    starts = {}
    cursor = 0
    for sec in sections:
        title = sec["title"]
        for i in range(cursor, len(page_texts)):
            text = page_texts[i]
            if sum(1 for s in sections if s["title"] in text) >= 4:
                continue                      # contents page
            if title in text[:400]:
                starts[title] = i
                cursor = i
                break
        else:
            print(f"  !! section not located: {title!r} — no bookmark")
    return starts


def footer_overlay(n_pages, page_sizes, section_for_page):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i in range(n_pages):
        w, h = page_sizes[i]
        c.setPageSize((w, h))
        if i > 0:                             # no footer on the cover
            c.setFont("Helvetica", 7.5)
            c.setFillColorRGB(0.36, 0.42, 0.49)
            c.drawString(32, 18, TITLE)
            right = f"{section_for_page[i]}   ·   {i + 1} / {n_pages}"
            c.drawRightString(w - 32, 18, right)
        c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf)


def main():
    sections = json.load(open(os.path.join(BUILD, "sections.json"),
                              encoding="utf-8"))
    raw = render_raw_pdf()
    reader = PdfReader(raw)
    n = len(reader.pages)
    print(f"rendered {n} pages")

    starts = find_section_pages(reader, sections)

    # Current section per page, for the running footer.
    section_for_page = [""] * n
    current = ""
    for i in range(n):
        for sec in sections:
            if starts.get(sec["title"]) == i:
                current = sec["title"]
        section_for_page[i] = current

    sizes = [(float(p.mediabox.width), float(p.mediabox.height))
             for p in reader.pages]
    overlay = footer_overlay(n, sizes, section_for_page)

    writer = PdfWriter()
    writer.append(reader)                     # keeps internal TOC links
    for i, page in enumerate(writer.pages):
        page.merge_page(overlay.pages[i])

    writer.add_outline_item(TITLE, 0)
    for sec in sections:
        if sec["title"] in starts:
            writer.add_outline_item(sec["title"], starts[sec["title"]])
    writer.page_mode = "/UseOutlines"         # open with bookmarks visible
    writer.add_metadata({"/Title": TITLE, "/Author": "SCPI_Control",
                         "/Subject": "Lab bench-control app user manual"})

    with open(OUT, "wb") as f:
        writer.write(f)
    print("wrote", OUT, f"{os.path.getsize(OUT)/1e6:.2f} MB, {n} pages, "
          f"{len(starts)}/{len(sections)} bookmarks")


if __name__ == "__main__":
    main()
