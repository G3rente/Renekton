"""Guionista IA: genera el episodio completo con Gemini 2.5 Pro.

Usa `google-genai` con salida estructurada (Pydantic). El prompt final de cada
clip se ensambla en Python para garantizar SIEMPRE el formato exacto que exige
Google Flow.
"""
from typing import List

from pydantic import BaseModel, Field
from google import genai
from google.genai import types

MODEL_NAME = "gemini-2.5-pro"

PROTAGONIST = "glossy white 2D stickman"
START_LOCATION = (
    "floating red-rimmed glass platform suspended over a dark abyss with purple "
    "lightning, robotic laser turrets aiming at him, and a giant spark-spitting "
    "neon roulette wheel"
)
START_OUTFIT = "torn grey shorts and barefoot"


# ----------------------------------------------------------------------------
# Esquema estructurado
# ----------------------------------------------------------------------------
class Clip(BaseModel):
    numero: int = Field(description="Número de clip, empezando en 1.")
    character: str = Field(
        description="Descripción COMPLETA y autocontenida del protagonista en este clip, "
        "en inglés, incluyendo TODA la ropa/equipo que lleva en este momento."
    )
    action: str = Field(
        description="Acción y escenario del clip, en inglés, cinematográfica y concreta. "
        "Si el personaje obtiene una prenda/arma/objeto, debe verse cómo se lo equipa."
    )
    sfx: str = Field(description="Efectos de sonido y música, en inglés, breves.")
    narracion: str = Field(
        description="Narración del locutor en ESPAÑOL, energética, máximo 28 palabras."
    )


class Episodio(BaseModel):
    titulo: str = Field(description="Título gancho para TikTok en español (máx. 70 caracteres).")
    texto_en_pantalla: str = Field(description="Texto fijo en pantalla en español (máx. 8 palabras).")
    descripcion: str = Field(description="Descripción en español, 1-2 frases + pregunta a la audiencia.")
    hashtags: List[str] = Field(description="5-8 hashtags, incluye #stickman y #animacion.")
    clips: List[Clip]


# ----------------------------------------------------------------------------
# Prompt del sistema con las reglas obligatorias
# ----------------------------------------------------------------------------
def build_system_prompt(n_clips: int) -> str:
    return f"""You are the head screenwriter of a viral TikTok series (@re.stickman) of 2D stickman animation.
Each episode has exactly {n_clips} clips of 10 seconds each. Each clip will be rendered independently by an
AI video model that has NO memory of previous clips, so every clip must be fully self-contained.

MANDATORY RULES (never break them):

1. PROTAGONIST: always "{PROTAGONIST}".

2. CLIP 1 (forced opening): the episode ALWAYS starts at "La Plataforma del Abismo":
   the Action of clip 1 must describe this exact setting: "{START_LOCATION}".
   In clip 1 the Character field is: "{PROTAGONIST} wearing only {START_OUTFIT}".
   In clip 1 the roulette wheel spins and lands on the WORLD requested by the user, which launches him into it.

3. STRICT WARDROBE CONTINUITY:
   - Keep a mental ledger of everything the character wears or carries.
   - Whenever he obtains clothing, boots, weapons, masks or backpacks, the Action of THAT clip must show him
     physically putting it on / equipping it on screen (use explicit verbs: puts on, straps, pulls over, slings).
   - From that clip onward, the Character field of EVERY following clip must list ALL items with EXACTLY the same
     wording (same colors, same adjectives). Never rename, never drop an item unless the Action shows it being
     lost or destroyed, and then remove it from the following Character fields.

4. FAITHFUL AESTHETICS: use realistic, cinematic locations that are thematically coherent with the chosen world.
   No generic cyberpunk look unless the world explicitly asks for it. Colorful 2D stickman style over detailed backgrounds.

5. LANGUAGE: Character, Action and SFX in English. Narration ONLY in Spanish, energetic male narrator,
   at most 28 words (it must fit in 10 seconds). Escalate tension: every clip ends with a mini cliffhanger.
   Never use double quotes inside the narration.

6. LAST CLIP (clip {n_clips}): it MUST end with an interactive dilemma. The Action must show a split screen with large
   on-screen text "A: ..." on one side and "B: ..." on the other (two different choices for what he does next),
   and the narration must ask the audience to comment A or B.

7. METADATA: titulo (Spanish hook, max 70 chars), texto_en_pantalla (Spanish, max 8 words),
   descripcion (Spanish, 1-2 sentences + a question), hashtags (5-8, include #stickman and #animacion).

Return ONLY the structured JSON."""


def build_prompt(clip: Clip) -> str:
    """Ensambla el prompt final con el formato EXACTO que pide Google Flow."""
    narr = clip.narracion.strip().replace('"', "'")
    return (
        "Duration: 10 seconds. Vertical 9:16 2D colorful stickman animation, 60fps. "
        f"Character: {clip.character.strip().rstrip('. ')}. "
        f"Action: {clip.action.strip().rstrip('. ')}. "
        f'Audio: [{clip.sfx.strip().rstrip(". ")} + energetic male narrator speaking in Spanish: "{narr}"]'
    )


# ----------------------------------------------------------------------------
# Validación de reglas duras
# ----------------------------------------------------------------------------
def validate_episode(ep: Episodio, n_clips: int) -> List[str]:
    problems = []
    if len(ep.clips) != n_clips:
        problems.append(f"Debe haber exactamente {n_clips} clips y hay {len(ep.clips)}.")
        return problems
    first, last = ep.clips[0], ep.clips[-1]
    if "torn grey shorts" not in first.character.lower() or "barefoot" not in first.character.lower():
        problems.append("El Character del clip 1 debe llevar solo 'torn grey shorts and barefoot'.")
    fa = first.action.lower()
    if "abyss" not in fa or "roulette" not in fa or "red-rimmed" not in fa:
        problems.append("La Action del clip 1 debe describir la Plataforma del Abismo con la ruleta de neón.")
    la = last.action
    if "A:" not in la or "B:" not in la:
        problems.append("La Action del último clip debe mostrar el dilema en pantalla dividida con 'A:' y 'B:'.")
    if "A" not in last.narracion.upper() or "B" not in last.narracion.upper():
        problems.append("La narración del último clip debe pedir comentar A o B.")
    return problems


# ----------------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------------
def generate_episode(api_key: str, mundo: str, n_clips: int, max_retries: int = 3) -> dict:
    """Devuelve un dict con título, texto en pantalla, descripción, hashtags y prompts listos."""
    if not api_key:
        raise ValueError("Falta la GEMINI_API_KEY.")
    client = genai.Client(api_key=api_key)
    system = build_system_prompt(n_clips)
    user_prompt = (
        f"World / theme of the episode: {mundo.strip()}\n"
        f"Write the full episode with exactly {n_clips} clips."
    )

    last_problems: List[str] = []
    ep = None
    for attempt in range(1, max_retries + 1):
        contents = user_prompt
        if last_problems:
            contents += "\n\nYour previous attempt broke these rules, fix them:\n- " + "\n- ".join(last_problems)
        resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=Episodio,
                temperature=0.9,
            ),
        )
        ep = resp.parsed if getattr(resp, "parsed", None) else Episodio.model_validate_json(resp.text)
        last_problems = validate_episode(ep, n_clips)
        if not last_problems:
            break
    if last_problems:
        # Se devuelve igualmente (el usuario puede editar), pero con aviso.
        warning = " | ".join(last_problems)
    else:
        warning = ""

    for i, c in enumerate(ep.clips, start=1):
        c.numero = i
    hashtags = [h if h.startswith("#") else f"#{h}" for h in (h.strip().replace(" ", "") for h in ep.hashtags) if h]
    return {
        "titulo": ep.titulo.strip(),
        "texto_en_pantalla": ep.texto_en_pantalla.strip(),
        "descripcion": ep.descripcion.strip(),
        "hashtags": hashtags,
        "prompts": [build_prompt(c) for c in ep.clips],
        "warning": warning,
    }
