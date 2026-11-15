"""Productor Google Flow con Playwright.

Se ejecuta como proceso aparte (lo lanza app.py):
    python -m modules.flow_automator output/flow_job.json
Emite líneas `PROGRESS|i|n|mensaje` que la app convierte en barra de progreso.

IMPORTANTE: la interfaz de Flow cambia a menudo. Si algo no encuentra un botón,
ajusta las expresiones regulares / selectores de la sección CONFIG.
"""
import base64
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# ----------------------------------------------------------------------------
# CONFIG (selectores flexibles)
# ----------------------------------------------------------------------------
FLOW_URL = "https://labs.google/fx/tools/flow"
PROMPT_BOX_SELECTORS = ["textarea", "div[contenteditable='true']", "[role='textbox']"]
GENERATE_BUTTON_RE = re.compile(r"(generate|generar|create|crear|send|enviar|arrow_forward)", re.I)
NEW_PROJECT_RE = re.compile(r"(new project|nuevo proyecto)", re.I)
DOWNLOAD_RE = re.compile(r"(download|descargar)", re.I)
LOGIN_WAIT_SECONDS = 300


def log(msg: str) -> None:
    print(msg, flush=True)


def progress(i: int, n: int, msg: str) -> None:
    print(f"PROGRESS|{i}|{n}|{msg}", flush=True)


# ----------------------------------------------------------------------------
# Helpers de página
# ----------------------------------------------------------------------------
def wait_for_login(page) -> None:
    """Si Google pide login, espera a que el usuario lo haga a mano (solo la 1ª vez)."""
    deadline = time.time() + LOGIN_WAIT_SECONDS
    warned = False
    while "accounts.google.com" in page.url and time.time() < deadline:
        if not warned:
            log("Inicia sesión en Google en la ventana de Chrome (tienes 5 minutos). Se guardará en chrome_profile/.")
            warned = True
        page.wait_for_timeout(2000)


def open_flow(page) -> None:
    page.goto(FLOW_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    wait_for_login(page)
    if FLOW_URL.split("/fx")[0] not in page.url:
        page.goto(FLOW_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
    # Si aparece la pantalla de proyectos, crea uno nuevo.
    try:
        btn = page.get_by_role("button", name=NEW_PROJECT_RE)
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            page.wait_for_timeout(4000)
    except Exception:
        pass


def find_prompt_box(page, timeout_s: int = 60):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for sel in PROMPT_BOX_SELECTORS:
            loc = page.locator(sel)
            for k in range(min(loc.count(), 5)):
                el = loc.nth(k)
                try:
                    if el.is_visible() and el.is_enabled():
                        return el
                except Exception:
                    continue
        page.wait_for_timeout(1000)
    raise RuntimeError("No encuentro la caja de prompt en Flow (revisa PROMPT_BOX_SELECTORS).")


def fill_prompt(page, box, text: str) -> None:
    box.click()
    tag = box.evaluate("e => e.tagName.toLowerCase()")
    if tag in ("textarea", "input"):
        box.fill(text)
    else:
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.keyboard.insert_text(text)


def submit_prompt(page, box) -> None:
    buttons = page.get_by_role("button", name=GENERATE_BUTTON_RE)
    for k in reversed(range(buttons.count())):
        b = buttons.nth(k)
        try:
            if b.is_visible() and b.is_enabled():
                b.click()
                return
        except Exception:
            continue
    log("Botón de generar no localizado; pruebo con Enter.")
    box.press("Enter")


def video_srcs(page) -> list:
    return page.eval_on_selector_all(
        "video", "els => els.map(e => e.currentSrc || e.src).filter(Boolean)"
    )


def wait_new_video(page, before: set, timeout_s: int) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        new = [s for s in video_srcs(page) if s not in before]
        if new:
            src = new[0]
            ready = page.evaluate(
                """(src) => { const v = [...document.querySelectorAll('video')]
                    .find(e => (e.currentSrc || e.src) === src);
                    return !!v && v.readyState >= 2 && v.duration > 0; }""",
                src,
            )
            if ready:
                page.wait_for_timeout(2000)
                return src
        page.wait_for_timeout(3000)
    raise TimeoutError("Flow no terminó de renderizar el clip a tiempo.")


def save_video(page, ctx, src: str, dest: Path) -> None:
    if src.startswith("blob:"):
        b64 = page.evaluate(
            """async (src) => { const r = await fetch(src); const b = await r.arrayBuffer();
                const u = new Uint8Array(b); let s = ''; const c = 0x8000;
                for (let i = 0; i < u.length; i += c) { s += String.fromCharCode.apply(null, u.subarray(i, i + c)); }
                return btoa(s); }""",
            src,
        )
        dest.write_bytes(base64.b64decode(b64))
    else:
        resp = ctx.request.get(src)
        if not resp.ok:
            raise RuntimeError(f"Descarga fallida ({resp.status}).")
        dest.write_bytes(resp.body())
    if dest.stat().st_size < 50_000:
        raise RuntimeError("El archivo descargado es demasiado pequeño; probablemente no es el vídeo.")


def save_via_download_button(page, dest: Path) -> None:
    """Plan B: pulsar el botón de descarga de la interfaz."""
    btn = page.get_by_role("button", name=DOWNLOAD_RE).first
    with page.expect_download(timeout=30000) as dl:
        btn.click()
    dl.value.save_as(str(dest))


# ----------------------------------------------------------------------------
# Flujo principal
# ----------------------------------------------------------------------------
def run_flow(prompts, out_dir: Path, profile_dir: Path, start_at: int = 1, timeout_min: int = 8) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    n = len(prompts)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            progress(0, n, "Abriendo Google Flow…")
            open_flow(page)
            for i in range(start_at, n + 1):
                dest = out_dir / f"clip_{i:02d}.mp4"
                progress(i - 1, n, f"Clip {i}/{n}: pegando prompt…")
                before = set(video_srcs(page))
                box = find_prompt_box(page)
                fill_prompt(page, box, prompts[i - 1])
                page.wait_for_timeout(800)
                submit_prompt(page, box)
                progress(i - 1, n, f"Clip {i}/{n}: renderizando (puede tardar varios minutos)…")
                src = wait_new_video(page, before, timeout_min * 60)
                progress(i - 1, n, f"Clip {i}/{n}: descargando…")
                try:
                    save_video(page, ctx, src, dest)
                except Exception as e:
                    log(f"Descarga directa falló ({e}); pruebo el botón de descarga.")
                    save_via_download_button(page, dest)
                progress(i, n, f"Clip {i}/{n} guardado en {dest.name}")
                page.wait_for_timeout(2500)
            log("FLOW_DONE")
        except Exception as e:
            shot = out_dir.parent / "output" / "flow_error.png"
            try:
                shot.parent.mkdir(exist_ok=True)
                page.screenshot(path=str(shot))
                log(f"Captura del error: {shot}")
            except Exception:
                pass
            log(f"ERROR: {e}")
            raise
        finally:
            ctx.close()


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        run_flow(
            prompts=job["prompts"],
            out_dir=Path(job["out_dir"]),
            profile_dir=Path(job["profile_dir"]),
            start_at=int(job.get("start_at", 1)),
            timeout_min=int(job.get("timeout_min", 8)),
        )
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
