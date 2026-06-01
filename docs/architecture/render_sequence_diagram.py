#!/usr/bin/env python3
"""Render the Mermaid block in a Markdown file to a trimmed PNG via headless Chromium.

Default target is the AP capture sequence diagram, so a bare run keeps
``AP-CAPTURE-SEQUENCE.png`` in sync with the Mermaid source in
``AP-CAPTURE-SEQUENCE.md`` (see the AP-sequence rule in ``CLAUDE.md``).

Usage:
    <bench>/env/bin/python docs/architecture/render_sequence_diagram.py
    <bench>/env/bin/python docs/architecture/render_sequence_diagram.py <in.md> <out.png>

Requirements: Pillow (in the bench venv), network access to the jsDelivr CDN
(loads mermaid@11 at render time), and a Chromium binary — the Playwright one at
``~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome`` (see
``test/testplans/BROWSER-TESTING-SETUP.md``) or one named via the ``CHROME`` env var.

NOT auto-run by CI — invoke it manually whenever the diagram's ``.md`` changes,
then commit the ``.md`` and ``.png`` together.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MD = os.path.join(HERE, "AP-CAPTURE-SEQUENCE.md")
DEFAULT_PNG = os.path.join(HERE, "AP-CAPTURE-SEQUENCE.png")


def _find_chrome() -> str:
	if os.environ.get("CHROME"):
		return os.environ["CHROME"]
	matches = sorted(
		glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
	)
	if not matches:
		raise SystemExit(
			"No Chromium found. Set CHROME=/path/to/chrome or install it "
			"(npx playwright install chromium) — see test/testplans/BROWSER-TESTING-SETUP.md."
		)
	return matches[-1]


def render(md_path: str, out_png: str) -> None:
	src = open(md_path).read()
	m = re.search(r"```mermaid\n(.*?)\n```", src, re.S)
	if not m:
		raise SystemExit(f"No ```mermaid block found in {md_path}")
	diagram = m.group(1)

	html = (
		"<!doctype html><html><head><meta charset='utf-8'><style>"
		"html,body{margin:0;background:#ffffff;}"
		"#wrap{display:inline-block;padding:28px;background:#ffffff;}"
		"</style></head><body><div id='wrap'><pre class='mermaid'>\n"
		+ diagram
		+ "\n</pre></div><script type='module'>"
		"import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';"
		"mermaid.initialize({startOnLoad:true,theme:'default',securityLevel:'loose',"
		"sequence:{useMaxWidth:false},fontFamily:'DejaVu Sans, Arial, sans-serif'});"
		"await mermaid.run();</script></body></html>"
	)

	with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
		fh.write(html)
		html_path = fh.name

	raw = out_png + ".raw.png"
	try:
		subprocess.run(
			[
				_find_chrome(), "--headless", "--disable-gpu", "--no-sandbox",
				"--hide-scrollbars", "--force-device-scale-factor=2",
				# Generous canvas; trimmed to content below. Widen if a diagram clips.
				"--window-size=3400,5600", "--virtual-time-budget=12000",
				f"--screenshot={raw}", f"file://{html_path}",
			],
			check=True, capture_output=True,
		)
	finally:
		os.unlink(html_path)

	# Trim the surrounding white, then re-pad with a small margin.
	img = Image.open(raw).convert("RGB")
	bbox = ImageChops.difference(img, Image.new("RGB", img.size, (255, 255, 255))).getbbox()
	if bbox:
		img = img.crop(bbox)
	pad = 28
	canvas = Image.new("RGB", (img.width + 2 * pad, img.height + 2 * pad), (255, 255, 255))
	canvas.paste(img, (pad, pad))
	canvas.save(out_png, format="PNG")
	os.remove(raw)
	print(f"wrote {out_png}  ({canvas.width}x{canvas.height})")


if __name__ == "__main__":
	md = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MD
	png = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PNG
	render(md, png)
