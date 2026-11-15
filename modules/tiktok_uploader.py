"""Publicador TikTok Studio con Playwright (sube a BORRADORES, nunca publica).

Se ejecuta como proceso aparte:
    python -m modules.tiktok_uploader output/tiktok_job.json
"""
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
DRAFT_BUTTON_RE = re.compile(r"(save draft|guardar borrador|save as draft|borrador|draft)", re.I)
EDITOR_SELECTORS = ["div.public-DraftEditor-content", "div[contenteditable='true']", "[role='textbox']"]


def log(msg: str) -> None:
    print(msg, flush=True)


def progress(i: int, n: int, msg: str) -> None:
    print(f"PROGRESS|{i}|{n}|{msg}", flush=True)


def _frames(page):
    return [page] + [f for f in page.frames if f != page.main_frame]


def find_file_input(page, timeout_s: int = 90):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for fr in _frames(page):
            loc = fr.locator("input[type='file']")
            if loc.count():
                return loc.first
        page.wait_for_timeout(1000)
    raise RuntimeError("No encuentro el selector de archivo en TikTok Studio (¿sesión iniciada?).")


def find_editor(page, timeout_s: int = 240):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for fr in _frames(page):
            for sel in EDITOR_SELECTORS:
                loc = fr.locator(sel)
                if loc.count() and loc.first.is_visible():
                    return loc.first
        page.wait_for_timeout(1500)
    raise RuntimeError("No apareció el editor de descripción tras subir el vídeo.")


def click_save_draft(page, timeout_s: int = 300) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for fr in _frames(page):
            btns = fr.get_by_role("button", name=DRAFT_BUTTON_RE)
            for k in range(btns.count()):
                b = btns.nth(k)
                try:
                    if b.is_visible() and b.is_enabled():
                        b.click()
                        return True
                except Exception:
                    continue
        page.wait_for_timeout(2000)
    return False


def run_upload(video: Path, description: str, profile_dir: Path) -> None:
    if not video.exists():
        raise FileNotFoundError(f"No existe {video}. Ejecuta primero el Paso 3.")
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        saved = False
        try:
            progress(0, 4, "Abriendo TikTok Studio…")
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if "login" in page.url:
                log("Inicia sesión en TikTok en la ventana de Chrome (se guardará en chrome_profile/).")
                page.wait_for_url(re.compile(r"tiktokstudio"), timeout=300_000)
                page.goto(UPLOAD_URL, wait_until="domcontentloaded")

            progress(1, 4, "Subiendo el vídeo…")
            find_file_input(page).set_input_files(str(video))

            progress(2, 4, "Esperando al editor y pegando la descripción…")
            editor = find_editor(page)
            editor.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.keyboard.insert_text(description)
            page.wait_for_timeout(1500)

            progress(3, 4, "Guardando en borradores…")
            saved = click_save_draft(page)
            if saved:
                page.wait_for_timeout(6000)
                progress(4, 4, "Guardado en borradores ✔")
                log("TIKTOK_DRAFT_SAVED")
            else:
                log("No localicé el botón de borrador. Revísalo y guárdalo a mano en la ventana abierta "
                    "(la dejo abierta 10 minutos).")
                page.wait_for_event("close", timeout=600_000)
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        run_upload(Path(job["video"]), job["description"], Path(job["profile_dir"]))
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
