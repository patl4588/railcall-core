#!/usr/bin/env python3
"""
Build PDFs of the adopted policy set + SRA from their markdown source.

Pipeline: markdown -> styled HTML -> headless Chrome --print-to-pdf.
Chrome is the only heavy dep; it's already on any macOS box we use.

Output: compliance/policies/pdf/*.pdf (per-policy) and
        compliance/policies/pdf/RailCall_Compliance_Bundle_YYYY-MM-DD.pdf
        (single concatenated document — the artifact to send to a
        customer's security team).

Run: python3 compliance/build_pdfs.py
"""
import base64
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
POLICIES_DIR = os.path.join(HERE, "policies")
SRA_PATH = os.path.join(HERE, "HIPAA_SRA_v1_2026-07-21.md")
OUT_DIR = os.path.join(POLICIES_DIR, "pdf")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if not os.path.exists(CHROME):
    print("ERROR: Chrome not at expected path — edit CHROME in this script.",
          file=sys.stderr)
    sys.exit(1)

# HTML wrapper: clean typography, table styling, and (importantly) print
# CSS so page breaks land at H1/H2 rather than mid-paragraph.
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{
    size: Letter;
    margin: 0.85in 0.75in 0.85in 0.75in;
    @top-right {{
      content: "RailCall — {short_title}";
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 9pt;
      color: #666;
    }}
    @bottom-center {{
      content: counter(page) " of " counter(pages);
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 9pt;
      color: #666;
    }}
  }}
  html, body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 10.5pt;
    line-height: 1.5;
    color: #111;
    max-width: 100%;
  }}
  h1 {{
    font-size: 20pt;
    letter-spacing: -0.01em;
    color: #0b1220;
    border-bottom: 2px solid #0b1220;
    padding-bottom: 0.3em;
    margin-top: 0;
    page-break-before: always;
  }}
  h1:first-of-type {{ page-break-before: avoid; }}
  h2 {{
    font-size: 14pt;
    color: #0b1220;
    margin-top: 1.6em;
    padding-top: 0.3em;
    border-top: 1px solid #ddd;
    page-break-after: avoid;
  }}
  h3 {{
    font-size: 12pt;
    color: #333;
    margin-top: 1.2em;
    page-break-after: avoid;
  }}
  h4 {{ font-size: 11pt; color: #333; }}
  p, li {{ margin: 0.4em 0; }}
  strong {{ color: #0b1220; }}
  code {{
    font-family: "SF Mono", Menlo, Monaco, "Courier New", monospace;
    font-size: 9.5pt;
    background: #f4f4f6;
    padding: 1px 4px;
    border-radius: 3px;
    border: 1px solid #e0e0e5;
  }}
  pre {{
    background: #f4f4f6;
    padding: 12px 14px;
    border-radius: 5px;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.4;
    border-left: 3px solid #4a5568;
    page-break-inside: avoid;
  }}
  pre code {{ background: none; padding: 0; border: none; }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
  }}
  th, td {{
    border: 1px solid #ccc;
    padding: 6px 10px;
    text-align: left;
    vertical-align: top;
  }}
  th {{
    background: #f4f4f6;
    font-weight: 600;
    color: #0b1220;
  }}
  tr {{ page-break-inside: avoid; }}
  hr {{
    border: none;
    border-top: 1px solid #ddd;
    margin: 1.5em 0;
  }}
  blockquote {{
    border-left: 4px solid #4a5568;
    margin: 1em 0;
    padding: 0.6em 1em;
    background: #f8f8f9;
    color: #444;
  }}
  a {{ color: #0b6bcb; text-decoration: none; }}
  /* Cover page for the bundle */
  .cover {{
    text-align: center;
    padding: 3in 0 0 0;
    page-break-after: always;
  }}
  .cover h1 {{
    font-size: 32pt;
    border: none;
    padding: 0;
    letter-spacing: -0.02em;
  }}
  .cover .sub {{
    color: #666;
    font-size: 14pt;
    margin: 0.5em 0;
  }}
  .cover .meta {{
    color: #333;
    font-size: 11pt;
    margin-top: 3em;
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def md_to_html(md_text: str) -> str:
    """Convert markdown to HTML with table + fenced-code support."""
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
    )


def render_pdf(html_path: str, pdf_path: str) -> None:
    """Headless Chrome: HTML file -> PDF."""
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",  # we drew our own header/footer via @page CSS
        "--print-to-pdf=" + pdf_path,
        "--print-to-pdf-no-header",
        "file://" + html_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print("  chrome stderr:", result.stderr[-300:], file=sys.stderr)
        raise RuntimeError("chrome print-to-pdf failed for " + html_path)


def build_one_pdf(md_path: str, out_pdf: str, title: str) -> None:
    """Render a single markdown file to a single PDF."""
    md_text = open(md_path).read()
    body_html = md_to_html(md_text)
    short = title if len(title) <= 40 else title[:37] + "..."
    html = HTML_TEMPLATE.format(title=title, short_title=short, body=body_html)
    with tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(html)
        tmp_html = f.name
    try:
        render_pdf(tmp_html, out_pdf)
    finally:
        os.unlink(tmp_html)


def build_bundle_pdf(sections: list, out_pdf: str) -> None:
    """Render the whole set + SRA + cover as ONE PDF."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cover = f"""
<div class="cover">
  <h1>RailCall</h1>
  <div class="sub">Compliance Program &mdash; Policy Set v1.0</div>
  <div class="meta">
    Adopted 2026-07-21 by Sami Ben Chaalia (Security Officer)<br>
    Bundle generated {today}<br><br>
    <em>Confidential — for review under NDA</em>
  </div>
</div>
"""

    body_parts = [cover]
    for md_path, title in sections:
        md_text = open(md_path).read()
        body_parts.append(md_to_html(md_text))

    html = HTML_TEMPLATE.format(
        title="RailCall Compliance Bundle",
        short_title="Compliance Bundle v1.0",
        body="\n<hr>\n".join(body_parts),
    )
    with tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(html)
        tmp_html = f.name
    try:
        render_pdf(tmp_html, out_pdf)
    finally:
        os.unlink(tmp_html)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    # Per-policy PDFs
    policies = sorted(glob.glob(os.path.join(POLICIES_DIR, "[0-9]*.md")))
    sections = []  # (md_path, title) for the bundle

    print("Rendering per-policy PDFs into %s ..." % OUT_DIR)
    for md_path in policies:
        base = os.path.basename(md_path).replace(".md", "")
        # Title = first-line H1
        with open(md_path) as f:
            first = f.readline().strip()
        title = first.lstrip("# ").strip() if first.startswith("#") else base
        out_pdf = os.path.join(OUT_DIR, base + ".pdf")
        try:
            build_one_pdf(md_path, out_pdf, title)
            size_kb = os.path.getsize(out_pdf) // 1024
            print("  ok  %-50s  %d KB" % (base + ".pdf", size_kb))
            sections.append((md_path, title))
        except Exception as e:
            print("  ERR %s: %s" % (base, e), file=sys.stderr)

    # SRA PDF
    print()
    print("Rendering SRA...")
    try:
        build_one_pdf(SRA_PATH, os.path.join(OUT_DIR, "HIPAA_SRA_v1.pdf"),
                      "RailCall — HIPAA Security Risk Analysis (v1)")
        print("  ok  HIPAA_SRA_v1.pdf")
    except Exception as e:
        print("  ERR SRA: %s" % e, file=sys.stderr)

    # Bundle PDF — SRA first (compliance context), then policies in order.
    print()
    print("Rendering combined bundle...")
    bundle_sections = [(SRA_PATH, "RailCall — HIPAA Security Risk Analysis")]
    bundle_sections.extend(sections)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    bundle_pdf = os.path.join(OUT_DIR, f"RailCall_Compliance_Bundle_{today}.pdf")
    try:
        build_bundle_pdf(bundle_sections, bundle_pdf)
        size_kb = os.path.getsize(bundle_pdf) // 1024
        print("  ok  %s  %d KB" % (os.path.basename(bundle_pdf), size_kb))
    except Exception as e:
        print("  ERR bundle: %s" % e, file=sys.stderr)
        return 1

    print()
    print("Done. PDFs in %s" % OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
