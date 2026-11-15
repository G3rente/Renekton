"""Ruleta Stickman Studio · interfaz principal (Streamlit)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from modules.script_generator import generate_episode
from modules.video_editor import build_episode

ROOT = Path(__file__).parent.resolve()
CLIPS_DIR = ROOT / "clips_raw"
OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = ROOT / "assets"
PROFILE_DIR = ROOT / "chrome_profile"
FINAL_VIDEO = OUTPUT_DIR / "episodio_final_tiktok.mp4"
DEFAULT_CTA = ASSETS_DIR / "cta_megusta.mp4"
for d in (CLIPS_DIR, OUTPUT_DIR, ASSETS_DIR, PROFILE_DIR):
    d.mkdir(exist_ok=True)

load_dotenv(ROOT / ".env")

st.set_page_config(page_title="Ruleta Stickman Studio", page_icon="🎰", layout="wide")

# ----------------------------------------------------------------------------
# Estilo oscuro/táctico "Lunar 333": fondo negro, acentos neón rojo y dorado
# ----------------------------------------------------------------------------
st.markdown(
    """
<style>
.stApp { background: radial-gradient(circle at 50% -10%, #2a050c 0%, #0b0b10 45%, #060608 100%); }
h1, h2, h3 { letter-spacing: .04em; }
.hero { text-align:center; padding: 6px 0 14px 0; }
.hero h1 { font-size: 2.6rem; margin: 0; color:#ffd700;
  text-shadow: 0 0 8px #ff1744, 0 0 22px rgba(255,23,68,.65); text-transform: uppercase; }
.hero p { color:#ff5470; margin:0; letter-spacing:.35em; font-size:.8rem; text-transform: uppercase; }
button[data-baseweb="tab"] { font-weight: 700; letter-spacing:.05em; }
button[data-baseweb="tab"][aria-selected="true"] { color:#ffd700 !important; }
div[data-baseweb="tab-highlight"] { background-color:#ff1744 !important; box-shadow:0 0 10px #ff1744; }
.stButton > button { border:1px solid #ff1744; border-radius:6px; transition: all .15s; }
.stButton > button:hover { box-shadow: 0 0 14px rgba(255,23,68,.8); border-color:#ffd700; color:#ffd700; }
.stButton > button[kind="primary"] { background: linear-gradient(90deg,#b00020,#ff1744); color:#fff; border:none; }
textarea, input { border-color:#3a1a22 !important; }
[data-testid="stSidebar"] { background:#0d0d12; border-right:1px solid #2a0f16; }
.tag { display:inline-block; border:1px solid #ffd700; color:#ffd700; border-radius:4px;
  padding:1px 8px; font-size:.75rem; margin-right:6px; }
</style>
<div class="hero"><p>@re.stickman</p><h1>🎰 Ruleta Stickman Studio</h1><p>Guion · Flow · Edición · TikTok</p></div>
""",
    unsafe_allow_html=True,
)

ss = st.session_state


# ----------------------------------------------------------------------------
# Sidebar: credenciales seguras
# ----------------------------------------------------------------------------
def _load_env_key():
    load_dotenv(ROOT / ".env", override=True)
    key = os.getenv("GEMINI_API_KEY", "")
    if key:
        ss["api_key_input"] = key
        ss["_env_msg"] = "ok"
    else:
        ss["_env_msg"] = "missing"


if "api_key_input" not in ss:
    ss["api_key_input"] = os.getenv("GEMINI_API_KEY", "")

with st.sidebar:
    st.markdown("### 🔐 Credenciales")
    st.text_input("GEMINI_API_KEY", type="password", key="api_key_input",
                  help="Solo vive en memoria de esta sesión. Nunca se guarda en el código.")
    st.button("Cargar desde .env", on_click=_load_env_key, use_container_width=True)
    if ss.get("_env_msg") == "ok":
        st.success("Clave cargada desde .env")
    elif ss.get("_env_msg") == "missing":
        st.warning("No hay GEMINI_API_KEY en .env")

    st.markdown("### 🧰 Sistema")
    st.write(("✅" if shutil.which("ffmpeg") or os.getenv("FFMPEG_PATH") else "❌") + " FFmpeg")
    st.write(("✅" if DEFAULT_CTA.exists() else "⚠️") + " assets/cta_megusta.mp4")
    st.write(("✅" if any(PROFILE_DIR.iterdir()) else "ℹ️") + " Perfil Chrome (se crea al 1er uso)")


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def get_prompts():
    return [ss.get(f"prompt_{i}", "") for i in range(ss.get("n_clips", 0))]


def full_caption() -> str:
    tags = " ".join(ss.get("ep_tags", "").split())
    return (ss.get("ep_desc", "").strip() + "\n\n" + tags).strip()


def run_worker(module: str, job_path: Path, bar, log_box) -> int:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-m", module, str(job_path)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env, bufsize=1,
    )
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        if line.startswith("PROGRESS|"):
            try:
                _, i, n, msg = line.split("|", 3)
                bar.progress(min(int(i) / max(int(n), 1), 1.0), text=msg)
            except ValueError:
                pass
        elif line:
            lines.append(line)
            log_box.code("\n".join(lines[-20:]), language="text")
    return proc.wait()


tab1, tab2, tab3, tab4 = st.tabs([
    "① Guionista IA", "② Productor Google Flow", "③ Editor & Subtitulador", "④ Publicador TikTok",
])

# ----------------------------------------------------------------------------
# PASO 1 · Guionista IA
# ----------------------------------------------------------------------------
with tab1:
    st.subheader("Guionista IA · Gemini 2.5 Pro")
    mundo = st.text_area("Mundo o tema del episodio", height=90, key="mundo",
                         placeholder="Ej: Antiguo Egipto bajo una tormenta de arena, con tumbas llenas de trampas…")
    dur = st.radio("Duración", [60, 100], format_func=lambda s: f"{s}s · {s // 10} clips",
                   horizontal=True, key="dur")

    if st.button("🎰 Generar historia", type="primary", disabled=not mundo.strip()):
        if not ss.get("api_key_input"):
            st.error("Introduce tu GEMINI_API_KEY en la barra lateral.")
        else:
            try:
                n = dur // 10
                with st.spinner(f"Gemini está escribiendo {n} clips…"):
                    ep = generate_episode(ss["api_key_input"], mundo, n)
                ss["ep_titulo"] = ep["titulo"]
                ss["ep_texto"] = ep["texto_en_pantalla"]
                ss["ep_desc"] = ep["descripcion"]
                ss["ep_tags"] = " ".join(ep["hashtags"])
                for i, p in enumerate(ep["prompts"]):
                    ss[f"prompt_{i}"] = p
                ss["n_clips"] = n
                ss["gen_warning"] = ep["warning"]
            except Exception as e:
                st.error(f"Error al generar: {e}")

    if ss.get("n_clips"):
        if ss.get("gen_warning"):
            st.warning("Revisa a mano estas reglas, Gemini no las cumplió del todo: " + ss["gen_warning"])
        st.success("Historia generada. Edita lo que quieras antes de producir.")
        c1, c2 = st.columns(2)
        c1.text_input("Título", key="ep_titulo")
        c2.text_input("Texto fijo en pantalla", key="ep_texto")
        st.text_area("Descripción", key="ep_desc", height=80)
        st.text_input("Hashtags", key="ep_tags")
        st.markdown("##### Prompts de cada clip (10 s)")
        for i in range(ss["n_clips"]):
            st.text_area(f"Clip {i + 1}", key=f"prompt_{i}", height=170)

# ----------------------------------------------------------------------------
# PASO 2 · Productor Google Flow
# ----------------------------------------------------------------------------
with tab2:
    st.subheader("Productor · Google Flow (Playwright)")
    prompts = get_prompts()
    if not prompts:
        st.info("Primero genera la historia en el Paso 1.")
    else:
        st.caption("Se abrirá Chrome con el perfil persistente `chrome_profile/`. La primera vez, inicia sesión "
                   "en Google en esa ventana y configura Flow en vertical 9:16.")
        c1, c2 = st.columns(2)
        start_at = c1.number_input("Empezar en el clip", 1, len(prompts), 1)
        timeout_min = c2.number_input("Timeout por clip (min)", 2, 20, 8)
        if st.button("🎬 Lanzar Google Flow", type="primary"):
            job = OUTPUT_DIR / "flow_job.json"
            job.write_text(json.dumps({
                "prompts": get_prompts(), "out_dir": str(CLIPS_DIR), "profile_dir": str(PROFILE_DIR),
                "start_at": int(start_at), "timeout_min": int(timeout_min),
            }, ensure_ascii=False), encoding="utf-8")
            bar = st.progress(0.0, text="Iniciando…")
            log_box = st.empty()
            rc = run_worker("modules.flow_automator", job, bar, log_box)
            if rc == 0:
                bar.progress(1.0, text="Todos los clips descargados ✔")
                st.success("Producción terminada. Pasa al Paso 3.")
            else:
                st.error("El productor se detuvo con error. Mira el log (y output/flow_error.png).")
    existing = sorted(CLIPS_DIR.glob("clip_*.mp4"))
    if existing:
        st.markdown(f"**Clips en `clips_raw/`:** {len(existing)} → " + ", ".join(p.name for p in existing))

# ----------------------------------------------------------------------------
# PASO 3 · Editor & Subtitulador
# ----------------------------------------------------------------------------
with tab3:
    st.subheader("Editor & Subtitulador · FFmpeg + Whisper")
    cta = st.text_input("Clip CTA (me gusta)", value=str(DEFAULT_CTA))
    if not Path(cta).exists():
        st.warning("No existe el CTA: el vídeo se montará sin él.")
    c1, c2, c3 = st.columns(3)
    ff_clip = c1.number_input("Clip del flash-forward", 1, 10, 9,
                              help="Si el episodio tiene menos clips, usa el penúltimo.")
    ff_start = c2.number_input("Segundo de inicio del flash (s)", 0.0, 9.0, 6.0, 0.5)
    wmodel = c3.selectbox("Modelo Whisper", ["tiny", "base", "small", "medium"], index=2)
    c4, c5 = st.columns(2)
    font = c4.text_input("Fuente de subtítulos", "Arial")
    fsize = c5.number_input("Tamaño de subtítulos", 6, 30, 12)

    if st.button("✂️ Montar y subtitular", type="primary"):
        bar = st.progress(0.0, text="Preparando…")
        try:
            res = build_episode(
                clips_dir=CLIPS_DIR, cta_path=Path(cta), out_path=FINAL_VIDEO,
                ff_clip_index=int(ff_clip), ff_start=float(ff_start), whisper_model=wmodel,
                font=font, fontsize=int(fsize),
                progress=lambda f, m: bar.progress(min(max(f, 0.0), 1.0), text=m),
            )
            st.success(f"Listo: {res['clips']} clips · flash-forward de {res['flash_forward_de']} · "
                       f"CTA {'insertado' if res['cta_insertado'] else 'omitido'}")
        except Exception as e:
            st.error(str(e))
    if FINAL_VIDEO.exists():
        st.video(str(FINAL_VIDEO))

# ----------------------------------------------------------------------------
# PASO 4 · Publicador TikTok Studio
# ----------------------------------------------------------------------------
with tab4:
    st.subheader("Publicador · TikTok Studio (Borradores)")
    if not ss.get("n_clips"):
        st.info("Genera la historia en el Paso 1 para tener título y descripción.")
    else:
        st.markdown("**Título**")
        st.code(ss.get("ep_titulo", ""), language="text")
        st.markdown("**Texto fijo en pantalla**")
        st.code(ss.get("ep_texto", ""), language="text")
        st.markdown("**Descripción + hashtags** (la que se pega en TikTok)")
        st.code(full_caption(), language="text")
        st.caption("Cada bloque tiene su botón de copiar arriba a la derecha.")

    if not FINAL_VIDEO.exists():
        st.warning("Aún no existe output/episodio_final_tiktok.mp4 (Paso 3).")
    elif st.button("📤 Subir a Borradores de TikTok Studio", type="primary"):
        job = OUTPUT_DIR / "tiktok_job.json"
        job.write_text(json.dumps({
            "video": str(FINAL_VIDEO), "description": full_caption(), "profile_dir": str(PROFILE_DIR),
        }, ensure_ascii=False), encoding="utf-8")
        bar = st.progress(0.0, text="Iniciando…")
        log_box = st.empty()
        rc = run_worker("modules.tiktok_uploader", job, bar, log_box)
        if rc == 0:
            st.success("Vídeo en Borradores. Revísalo y publícalo desde TikTok Studio.")
        else:
            st.error("La subida falló. Mira el log; puedes subirlo a mano con los textos de arriba.")
