# 🎰 Ruleta Stickman Studio

App en Streamlit para automatizar la serie de animación 2D de TikTok **@re.stickman**:
guion con Gemini → clips en Google Flow → montaje + subtítulos (FFmpeg + Whisper) → borrador en TikTok Studio.

## Estructura

```
ruleta-stickman-studio/
├── app.py
├── modules/
│   ├── __init__.py
│   ├── script_generator.py
│   ├── flow_automator.py
│   ├── video_editor.py
│   └── tiktok_uploader.py
├── assets/            # pon aquí cta_megusta.mp4
├── clips_raw/         # clips descargados de Flow
├── output/            # episodio_final_tiktok.mp4
├── chrome_profile/    # sesión persistente de Chrome (NO se sube a Git)
├── .streamlit/config.toml
├── requirements.txt
├── .env.example
└── .gitignore
```

## Instalación en Windows

1. **Python 3.10–3.12** (marca *Add Python to PATH*) y **Google Chrome** instalado.
2. **FFmpeg**:
   - Con winget: `winget install Gyan.FFmpeg` y reabre la terminal, o
   - Descarga el zip de https://www.gyan.dev/ffmpeg/builds/, descomprímelo en `C:\ffmpeg` y añade `C:\ffmpeg\bin` al PATH
     (Inicio → "Variables de entorno" → Path → Nuevo).
   - Comprueba: `ffmpeg -version`. Si no quieres tocar el PATH, define `FFMPEG_PATH` y `FFPROBE_PATH` en `.env`.
3. Terminal en la carpeta del proyecto:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   playwright install chromium
   copy .env.example .env
   ```
   (`playwright install chromium` es solo un respaldo: la app usa tu Chrome instalado.)
4. Edita `.env` con tu `GEMINI_API_KEY` (o pégala en la barra lateral de la app).
5. Copia tu clip fijo a `assets\cta_megusta.mp4`.
6. Arranca: `streamlit run app.py`

## Primer uso

- **Paso 2:** se abre Chrome; inicia sesión en Google y deja Flow en vertical 9:16. La sesión queda en `chrome_profile/`.
- **Paso 4:** inicia sesión en TikTok en esa misma ventana la primera vez.
- Si Flow o TikTok cambian su interfaz, ajusta los selectores/regex de la sección `CONFIG` de
  `modules/flow_automator.py` y de `modules/tiktok_uploader.py`.
- El Paso 4 solo guarda en **Borradores**; nunca publica.

## Notas técnicas

- Flash-forward: 0.9 s del clip 9 (si el episodio es de 6 clips, del penúltimo) al segundo 0.0.
- CTA: se inserta a mitad del vídeo (tras el clip 3 en 6 clips, tras el 5 en 10).
- Rutas de Windows en `subtitles=`: el `.srt` se copia a una carpeta temporal y FFmpeg se ejecuta ahí con ruta relativa
  (sin `C:\`). Hay además un helper `ffmpeg_filter_path()` por si lo necesitas.
- Whisper: `tiny`/`base` van rápido; `small` es el equilibrio recomendado en español.

## Subir a GitHub

```bat
git init
git add .
git commit -m "Ruleta Stickman Studio: primera versión"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/ruleta-stickman-studio.git
git push -u origin main
```

Antes del primer push comprueba con `git status` que **no** aparecen `.env` ni `chrome_profile/`.
