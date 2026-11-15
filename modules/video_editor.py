"""Editor & Subtitulador: FFmpeg (montaje) + Whisper (subtítulos virales)."""
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

W, H, FPS = 1080, 1920, 30
YELLOW, WHITE = "#FFE600", "#FFFFFF"

ProgressCb = Optional[Callable[[float, str], None]]


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def _find_bin(name: str) -> str:
    custom = os.getenv(f"{name.upper()}_PATH")
    found = None
    if custom:
        p = Path(custom)
        if p.is_dir():
            p = p / (name + (".exe" if os.name == "nt" else ""))
        if p.exists():
            found = str(p)
    if not found:
        found = shutil.which(name)
    if not found:
        raise FileNotFoundError(
            f"No se encontró '{name}'. Instala FFmpeg y añádelo al PATH o define {name.upper()}_PATH en .env."
        )
    d = str(Path(found).parent)
    if d not in os.environ.get("PATH", ""):
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    return found


def _run(cmd, cwd=None):
    r = subprocess.run(
        [str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg falló:\n{' '.join(map(str, cmd))}\n\n{r.stderr[-2500:]}")
    return r


def _duration(path: Path) -> float:
    r = _run([_find_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", path])
    return float(r.stdout.strip())


def _has_audio(path: Path) -> bool:
    r = _run([_find_bin("ffprobe"), "-v", "error", "-select_streams", "a",
              "-show_entries", "stream=index", "-of", "csv=p=0", path])
    return bool(r.stdout.strip())


def _natural_key(p: Path) -> int:
    m = re.search(r"(\d+)", p.stem)
    return int(m.group(1)) if m else 0


def ffmpeg_filter_path(p) -> str:
    """Escapa una ruta de Windows para usarla dentro de un filtro de FFmpeg (C:\\x -> C\\:/x)."""
    s = str(p).replace("\\", "/")
    s = re.sub(r"^([A-Za-z]):", r"\1\\:", s)
    return s.replace("'", r"\'")


def normalize_clip(src: Path, dst: Path, start: Optional[float] = None, dur: Optional[float] = None) -> None:
    """Re-codifica a 1080x1920 / 30fps / AAC estéreo para poder concatenar sin problemas."""
    ffmpeg = _find_bin("ffmpeg")
    audio = _has_audio(src)
    cmd = [ffmpeg, "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", src]
    if not audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p")
    cmd += ["-vf", vf, "-map", "0:v:0", "-map", "0:a:0" if audio else "1:a:0"]
    if not audio:
        cmd += ["-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k", dst]
    _run(cmd)


def concat(files, dst: Path, work: Path) -> None:
    lst = work / "concat.txt"
    lines = []
    for f in files:
        p = str(Path(f).resolve()).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{p}'")
    lst.write_text("\n".join(lines), encoding="utf-8")
    _run([_find_bin("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dst])


# ----------------------------------------------------------------------------
# Subtítulos
# ----------------------------------------------------------------------------
def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _word_chunks(words, max_words=3, max_gap=0.7):
    cur = []
    for w in words:
        if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > max_gap):
            yield cur
            cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", w["word"].strip()):
            yield cur
            cur = []
    if cur:
        yield cur


def build_srt(result: dict) -> str:
    words = []
    for seg in result.get("segments", []):
        if seg.get("words"):
            words.extend({"word": w["word"], "start": w["start"], "end": w["end"]} for w in seg["words"])
        else:  # sin timestamps por palabra: usa el segmento entero
            words.append({"word": seg["text"], "start": seg["start"], "end": seg["end"]})
    blocks = []
    for idx, chunk in enumerate(_word_chunks(words), start=1):
        text = " ".join(w["word"].strip() for w in chunk).upper()
        text = re.sub(r"[,;:]+$", "", text)
        color = YELLOW if idx % 2 else WHITE
        start, end = chunk[0]["start"], max(chunk[-1]["end"], chunk[0]["start"] + 0.2)
        blocks.append(f"{idx}\n{_srt_time(start)} --> {_srt_time(end)}\n<font color=\"{color}\">{text}</font>\n")
    return "\n".join(blocks)


def transcribe(video: Path, model_name: str) -> dict:
    import whisper  # import perezoso: es pesado

    model = whisper.load_model(model_name)
    return model.transcribe(str(video), language="es", word_timestamps=True, fp16=False)


def burn_subtitles(video_in: Path, srt: Path, video_out: Path, work: Path,
                   font="Arial", fontsize=12, margin_v=55) -> None:
    """Quema el .srt. Truco anti-Windows: copiamos el SRT a `work` y ejecutamos FFmpeg con cwd=work,
    así el filtro usa una ruta relativa (`subs.srt`) sin 'C:' ni barras que escapar."""
    shutil.copy(srt, work / "subs.srt")
    style = (f"FontName={font},FontSize={fontsize},Bold=1,PrimaryColour=&H00FFFFFF,"
             f"OutlineColour=&H00000000,BackColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,"
             f"Alignment=2,MarginV={margin_v}")
    vf = f"subtitles=subs.srt:force_style='{style}'"
    _run([_find_bin("ffmpeg"), "-y", "-i", Path(video_in).resolve(), "-vf", vf,
          "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy",
          "-movflags", "+faststart", Path(video_out).resolve()], cwd=str(work))


# ----------------------------------------------------------------------------
# Pipeline completo
# ----------------------------------------------------------------------------
def build_episode(
    clips_dir: Path,
    cta_path: Path,
    out_path: Path,
    ff_clip_index: int = 9,
    ff_start: float = 6.0,
    ff_dur: float = 0.9,
    whisper_model: str = "small",
    font: str = "Arial",
    fontsize: int = 12,
    progress: ProgressCb = None,
) -> dict:
    def report(frac: float, msg: str):
        if progress:
            progress(frac, msg)

    clips_dir, out_path = Path(clips_dir).resolve(), Path(out_path).resolve()
    clips = sorted(clips_dir.glob("clip_*.mp4"), key=_natural_key)
    if not clips:
        raise FileNotFoundError(f"No hay clips en {clips_dir}. Ejecuta primero el Paso 2.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent / "_tmp"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    _find_bin("ffmpeg")
    _find_bin("ffprobe")

    # 1) Normalizar clips
    norm = []
    for k, c in enumerate(clips):
        report(0.03 + 0.37 * k / len(clips), f"Normalizando {c.name}…")
        dst = work / f"n_{k:02d}.mp4"
        normalize_clip(c, dst)
        norm.append(dst)

    # 2) Flash-forward de 0.9 s (clip 9; si no existe, el penúltimo)
    report(0.42, "Extrayendo flash-forward…")
    ff_idx = ff_clip_index - 1 if len(clips) >= ff_clip_index else max(len(clips) - 2, 0)
    ff_src = clips[ff_idx]
    start = max(0.0, min(ff_start, _duration(ff_src) - ff_dur))
    flash = work / "flash.mp4"
    normalize_clip(ff_src, flash, start=start, dur=ff_dur)

    # 3) CTA a mitad del vídeo
    sequence = [flash]
    mid = len(norm) // 2
    cta_path = Path(cta_path)
    cta_norm = None
    if cta_path.exists():
        report(0.46, "Preparando CTA…")
        cta_norm = work / "cta.mp4"
        normalize_clip(cta_path, cta_norm)
    for k, n in enumerate(norm):
        if k == mid and cta_norm:
            sequence.append(cta_norm)
        sequence.append(n)

    # 4) Unir
    report(0.5, "Uniendo clips…")
    joined = work / "joined.mp4"
    concat(sequence, joined, work)

    # 5) Whisper
    report(0.55, f"Transcribiendo con Whisper ({whisper_model})… esto puede tardar.")
    result = transcribe(joined, whisper_model)
    srt_text = build_srt(result)
    srt_path = out_path.with_suffix(".srt")
    srt_path.write_text(srt_text, encoding="utf-8")

    # 6) Subtítulos quemados
    report(0.88, "Quemando subtítulos…")
    if srt_text.strip():
        burn_subtitles(joined, srt_path, out_path, work, font=font, fontsize=fontsize)
    else:
        shutil.copy(joined, out_path)
    shutil.rmtree(work, ignore_errors=True)
    report(1.0, "Episodio listo ✔")
    return {
        "video": str(out_path),
        "srt": str(srt_path),
        "clips": len(clips),
        "cta_insertado": bool(cta_norm),
        "flash_forward_de": ff_src.name,
    }
