#!/usr/bin/env python3
"""Playwright walkthrough of the FastMSR cockpit → animated GIF.

Logs in, clicks through the key module screens, captures a screenshot of each,
and stitches them into an animated GIF at `static/fastmsr-walkthrough.gif`
(embedded at the top of the README). Uses the seeded synthetic demo data.

Usage:
    # start the app first:  python web_app.py
    python scripts/demo_walkthrough.py
    # or against another base URL:
    DEMO_BASE_URL=http://localhost:5008 python scripts/demo_walkthrough.py

Install deps first:
    pip install playwright pillow && python -m playwright install chromium
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_URL = os.getenv("DEMO_BASE_URL", "http://localhost:5008").rstrip("/")
EMAIL = os.getenv("FASTMSR_ADMIN_EMAIL", "admin@fastmsr.example")
PASSWORD = os.getenv("FASTMSR_ADMIN_PASSWORD", "FastMSR2026$")

ROOT = Path(__file__).resolve().parent.parent
FRAME_DIR = ROOT / "screenshots" / "frames"
GIF_PATH = ROOT / "static" / "fastmsr-walkthrough.gif"

VIEWPORT = {"width": 1440, "height": 900}
FRAME_WIDTH = 1040          # downscale for a lighter GIF
FRAME_MS = 2000             # ms per frame

# (caption, path) — the module tour, in order.
SCREENS = [
    ("MSR Command Center", "/"),
    ("Portfolios", "/portfolios"),
    ("Portfolio — stratification & QC", "/portfolios/1"),
    ("Loan-level MSR & cash-flow DCF", "/loans/1"),
    ("Valuation & rate-shock scenarios", "/valuation?pid=1"),
    ("CRX Exchange — competitive SRP auction", "/crx/1"),
    ("Servicing transfer — docs & exceptions", "/transfers/1"),
    ("Compliance & risk", "/compliance"),
    ("Audit trail (RBAC)", "/audit"),
]


def login(page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="networkidle", timeout=45000)
    page.fill('input[name="email"]', EMAIL)
    page.fill('input[name="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle", timeout=45000)


def capture(page) -> list[tuple[str, Path]]:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    shots: list[tuple[str, Path]] = []
    for i, (label, path) in enumerate(SCREENS):
        try:
            page.goto(f"{BASE_URL}{path}", wait_until="networkidle", timeout=30000)
        except Exception as e:  # noqa: BLE001 — keep the tour going
            print(f"  ! {path}: {e}")
        page.wait_for_timeout(900)
        out = FRAME_DIR / f"{i:02d}.png"
        page.screenshot(path=str(out))     # viewport-only → uniform frame size
        shots.append((label, out))
        print(f"  captured {path} -> {out.name}")
    return shots


def build_gif(shots) -> None:
    from PIL import Image, ImageDraw, ImageFont

    def _font(size: int):
        for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:  # noqa: BLE001
                continue
        return ImageFont.load_default()

    font = _font(18)
    frames = []
    for label, png in shots:
        img = Image.open(png).convert("RGB")
        w, h = img.size
        img = img.resize((FRAME_WIDTH, round(h * FRAME_WIDTH / w)), Image.LANCZOS)
        draw = ImageDraw.Draw(img)
        bar_h = 38
        y0 = img.height - bar_h
        draw.rectangle([0, y0, img.width, img.height], fill=(15, 23, 42))     # slate #0F172A
        draw.rectangle([0, y0, 6, img.height], fill=(245, 158, 11))            # amber accent
        draw.text((18, y0 + 9), f"FastMSR · {label}", fill=(248, 250, 252), font=font)
        frames.append(img)

    if not frames:
        sys.exit("No frames captured — is the app running at " + BASE_URL + " ?")
    GIF_PATH.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(GIF_PATH, save_all=True, append_images=frames[1:],
                   duration=FRAME_MS, loop=0, optimize=True)
    kb = GIF_PATH.stat().st_size // 1024
    print(f"\nGIF written: {GIF_PATH.relative_to(ROOT)}  ({len(frames)} frames, {kb} KB)")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright not installed:\n"
                 "  pip install playwright pillow && python -m playwright install chromium")
    print(f"Walkthrough of {BASE_URL} as {EMAIL}")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = ctx.new_page()
        login(page)
        shots = capture(page)
        browser.close()
    build_gif(shots)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
