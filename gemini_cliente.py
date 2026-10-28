"""Cliente REST de Gemini: solo texto anonimizado, sin PDFs ni datos de nóminas.

Usa la API de Gemini sin bibliotecas adicionales. La clave se envía como
cabecera HTTPS y debe permanecer exclusivamente en Streamlit Secrets.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_MODEL = "gemini-3.5-flash-lite"
API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_CHARS_PER_TURN = 1200
MAX_TURNS = 7

SYSTEM_PROMPT = (
    "Eres un asistente de control documental laboral de contratistas en Chile. "
    "Responde en español claro, directo y breve. Distingue errores OCR, documentos "
    "faltantes, descuadres documentales y cotizaciones impagas; no declares un "
    "incumplimiento solo por un error de reconocimiento. Aclara cuando la evidencia "
    "es insuficiente. Un F30-1 que señala pagado NO prueba que se consultó el "
    "verificador de la Dirección del Trabajo. No afirmes haber visto el PDF, "
    "cambiado el programa, consultado portales o corregido valores. "
    "Nunca inventes RUT, días, rentas ni resultados de verificación. "
    "La IA solo propone pasos de revisión; no autoriza ajustes automáticos."
)


class GeminiError(RuntimeError):
    """Error comprensible que no revela credenciales ni datos de respuesta del servidor."""


def _mensaje_error_http(codigo: int) -> str:
    if codigo in (400, 404):
        return (
            "Gemini rechazó la solicitud o no reconoce el modelo. "
            "Comprueba GEMINI_MODEL en los Secrets de Streamlit."
        )
    if codigo in (401, 403):
        return (
            "Gemini rechazó la clave o el proyecto no tiene acceso. "
            "Revisa GEMINI_API_KEY y el acceso al modelo en Google AI Studio."
        )
    if codigo == 429:
        return (
            "Llegaste al límite gratuito de Gemini. "
            "Inténtalo más tarde o revisa tus cuotas en Google AI Studio."
        )
    if 500 <= codigo < 600:
        return "Gemini está presentando un problema temporal. Inténtalo más tarde."
    return f"No se pudo conectar con Gemini (HTTP {codigo}). La auditoría no cambió."


def preparar_solicitud(
    pregunta: str,
    resumen: dict,
    historial: list[dict],
    modelo: str = DEFAULT_MODEL,
) -> tuple[str, dict]:
    """Construye la solicitud sin información de trabajadores ni archivos PDF."""
    if not re.fullmatch(r"gemini-[a-zA-Z0-9._-]{2,75}", modelo):
        raise GeminiError("Nombre de modelo inválido. Revisa GEMINI_MODEL.")

    # El llamador ya anonimiza los mensajes. No enviar log, matriz, PDF ni nombres.
    contents = []
    for turno in historial[-6:]:
        if turno.get("role") not in ("user", "assistant"):
            continue
        texto = str(turno.get("content", ""))[:MAX_CHARS_PER_TURN].strip()
        if texto:
            contents.append({
                "role": "user" if turno["role"] == "user" else "model",
                "parts": [{"text": texto}],
            })
    contents.append({
        "role": "user",
        "parts": [{"text": str(pregunta)[:MAX_CHARS_PER_TURN]}],
    })
    instrucciones = (
        SYSTEM_PROMPT
        + "\nContexto estadístico agregado de la auditoría (no es un documento): "
        + json.dumps(resumen, ensure_ascii=False)[:1200]
    )
    body = {
        "systemInstruction": {"parts": [{"text": instrucciones}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 850,
        },
    }
    return API_ENDPOINT.format(model=modelo), body


def consultar_gemini(
    pregunta: str,
    resumen: dict,
    historial: list[dict],
    clave: str,
    modelo: str = DEFAULT_MODEL,
) -> str:
    """Consulta solo cuando el usuario autorizó el envío.

    No reintenta automáticamente: evita consumo repetido de la cuota gratuita.
    """
    if not clave or not clave.strip():
        raise GeminiError("Falta configurar GEMINI_API_KEY en Streamlit Secrets.")
    url, body = preparar_solicitud(pregunta, resumen, historial, modelo)
    solicitud = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": clave.strip(),
            "x-goog-api-client": "auditoria-laboral-chat/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(solicitud, timeout=25) as respuesta:
            datos = json.loads(respuesta.read(1_500_000).decode("utf-8"))
    except HTTPError as exc:
        raise GeminiError(_mensaje_error_http(exc.code)) from None
    except (TimeoutError, URLError, OSError):
        raise GeminiError(
            "No se pudo comunicar con Gemini. Revisa tu conexión y vuelve a intentar."
        ) from None
    except (UnicodeError, ValueError):
        raise GeminiError("Gemini devolvió una respuesta que no se pudo interpretar.") from None

    try:
        partes = datos["candidates"][0]["content"]["parts"]
        texto = "\n".join(
            part["text"] for part in partes if isinstance(part.get("text"), str)
        ).strip()
    except (KeyError, IndexError, TypeError):
        texto = ""
    if not texto:
        raise GeminiError(
            "Gemini no devolvió una respuesta de texto. Reformula la pregunta."
        )
    return texto[:7000]
