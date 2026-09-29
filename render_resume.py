#!/usr/bin/env python3
"""
render_resume.py  (this is "Script 2" from the original plan)

Deterministic, no AI. Takes a content.yaml (edited, application-specific, or the
master itself) + style.yaml (from master) + template.html and renders a PDF.

Uses Playwright (headless Chromium) to print the rendered HTML to PDF — chosen
specifically because it installs cleanly on native Windows with no system
library dependencies (unlike WeasyPrint, which needs a separate GTK3/Pango/
Cairo runtime that's genuinely painful to set up on Windows). Chromium also
respects the @page CSS rule in master_template.html directly, so style.yaml's
page size/margins still drive everything exactly as before.

One-time setup:
    pip install playwright jinja2 pyyaml
    playwright install chromium

Usage:
    python render_resume.py \
        --content "content.yaml" \
        --style "../../master/master_style.yaml" \
        --template "../../master/master_template.html" \
        --out "Resume_Entrupy.pdf"
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Missing dependency. Run: pip install playwright jinja2 pyyaml\n"
              "Then (one-time only): playwright install chromium")


def load_yaml(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"File not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def render_pdf(content: dict, style: dict, template_path: Path, out_path: Path) -> Path:
    """Renders content+style through template_path into out_path (PDF).
    Also writes a <out_path>.debug.html sidecar. Returns the debug HTML path.
    Importable directly (e.g. from the Streamlit app) — no subprocess needed."""
    env = Environment(loader=FileSystemLoader(str(template_path.parent)))
    template = env.get_template(template_path.name)
    html_str = template.render(content=content, style=style)

    debug_html_path = out_path.with_suffix(".debug.html")
    with open(debug_html_path, "w", encoding="utf-8") as f:
        f.write(html_str)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            # Streamlit Community Cloud installs the Python package but may not
            # have the Chromium browser binary yet. Install it on first use.
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(debug_html_path.resolve().as_uri())
        page.wait_for_timeout(500)  # let @import web fonts finish rendering
        page.pdf(
            path=str(out_path),
            print_background=True,
            prefer_css_page_size=True,   # honors the @page rule -> style.yaml's margins/size
        )
        browser.close()

    return debug_html_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True, help="Path to content.yaml (edited or master)")
    ap.add_argument("--style", required=True, help="Path to master_style.yaml")
    ap.add_argument("--template", required=True, help="Path to master_template.html")
    ap.add_argument("--out", required=True, help="Output PDF path")
    args = ap.parse_args()

    content_path = Path(args.content)
    style_path = Path(args.style)
    template_path = Path(args.template)
    out_path = Path(args.out)

    content = load_yaml(content_path)
    style = load_yaml(style_path)

    debug_html_path = render_pdf(content, style, template_path, out_path)

    print(f"Rendered PDF: {out_path}")
    print(f"Debug HTML:   {debug_html_path}  (inspect this in a browser if layout looks off)")


if __name__ == "__main__":
    main()

