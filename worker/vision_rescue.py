"""Google Vision solo como OCR de rescate; nunca como prueba de pago oficial.

No usa credenciales JSON ni claves API: en Cloud Run utiliza Application
Default Credentials (cuenta de servicio). Los PDF y el texto OCR nunca se
registran en logs. Reserva cuota Postgres ANTES de cada solicitud facturable.
"""
from __future__ import annotations

import io
import logging
import os

import fitz
from PIL import Image

from pago_documental import _interpretar

LOG = logging.getLogger("galant.vision")


def _entero_env(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    try:
        return min(max(int(os.environ.get(nombre, str(defecto))), minimo), maximo)
    except (ValueError, TypeError):
        return defecto


def vision_habilitada() -> bool:
    return os.environ.get("GALANT_VISION_ENABLED", "false").strip().lower() == "true"


def _paginas_candidatas(info: dict, max_paginas: int) -> list[int]:
    """Primero recibos incompletos. No enviar páginas digitales ni nóminas sin necesidad."""
    candidatas = []
    if info.get("paginas_imagen", 0) == 0:
        return candidatas
    for c in info.get("comprobantes", []):
        if (not c.get("periodo") or not c.get("fecha_pago")
            or not c.get("folio")
            or "no identificada" in str(c.get("institucion", "")).lower()
            or c.get("conflicto_fecha_ocr")
            or c.get("estado") == "EVIDENCIA_INSUFICIENTE"):
            pagina = c.get("pagina")
            if isinstance(pagina, int) and pagina >= 1 and pagina not in candidatas:
                candidatas.append(pagina)
    # Si no aparece ningún comprobante, revisar primero las portadas más probables.
    if not info.get("comprobantes"):
        candidatas.extend([1, 3])
    paginas = int(info.get("paginas", 0))
    return [p for p in dict.fromkeys(candidatas) if 1 <= p <= paginas][:max_paginas]


def _png_pagina(pagina: fitz.Page, limite_lado: int = 2200) -> bytes:
    """Limita resolución/tamaño para el endpoint de Vision, sin subir el PDF."""
    pix = pagina.get_pixmap(matrix=fitz.Matrix(1.75, 1.75),
                            colorspace=fitz.csRGB, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img.thumbnail((limite_lado, limite_lado), Image.Resampling.LANCZOS)
    salida = io.BytesIO()
    img.save(salida, format="JPEG", quality=82, optimize=True)
    return salida.getvalue()


def _texto_google_vision(pagina: fitz.Page, cliente=None) -> str:
    """Una sola llamada Document Text Detection por página."""
    from google.cloud import vision
    client = cliente if cliente is not None else vision.ImageAnnotatorClient()
    respuesta = client.document_text_detection(
        image=vision.Image(content=_png_pagina(pagina)),
        timeout=12,
    )
    if respuesta.error.message:
        # El contenido de un error remoto puede contener detalles privados;
        # nunca escribir el mensaje íntegro ni enviarlo al frontend.
        raise RuntimeError("Google Vision devolvió un error de procesamiento")
    return respuesta.full_text_annotation.text or ""


def _reservar_unidad(cliente_supabase) -> bool:
    """Fallar cerrado: si Supabase no valida la cuota, NO llamar Vision."""
    max_mes = _entero_env("GALANT_VISION_MAX_MES", 300, 0, 900)
    max_dia = _entero_env("GALANT_VISION_MAX_DIA", 20, 0, 30)
    if max_mes == 0 or max_dia == 0:
        return False
    r = cliente_supabase.rpc("galant_reservar_vision", {
        "max_mensual": max_mes,
        "max_diario": max_dia,
    }).execute()
    return r.data is True


def _combinar_con_precaucion(comprobantes: list[dict], nuevo: dict) -> bool:
    """No combinar información entre folios/instituciones diferentes."""
    matches = [c for c in comprobantes if c.get("pagina") == nuevo["pagina"]]
    if len(matches) > 1:
        return False  # varias instituciones en misma página: no atribuir datos
    if not matches:
        nuevo["fuente"] = "Google Vision — página rescate"
        nuevo["estado"] = (
            "EVIDENCIA_INSUFICIENTE" if not nuevo.get("fecha_pago")
            else nuevo.get("estado", "EVIDENCIA_INSUFICIENTE")
        )
        nuevo["observacion"] = (
            "Extraído con OCR alternativo; validar folio/institución y cobertura del PDF."
        )
        comprobantes.append(nuevo)
        return True
    base = matches[0]
    if base.get("folio") and nuevo.get("folio") and base["folio"] != nuevo["folio"]:
        base["observacion"] = (
            str(base.get("observacion", "")) +
            " | Vision detectó folio diferente: requiere revisión humana."
        ).strip(" |")
        base["conflicto_folio_ocr"] = True
        base["estado"] = "EVIDENCIA_INSUFICIENTE"
        return False
    if (base.get("institucion") and nuevo.get("institucion")
        and "no identificada" not in str(base["institucion"]).lower()
        and "no identificada" not in str(nuevo["institucion"]).lower()
        and base["institucion"] != nuevo["institucion"]):
        base["conflicto_institucion_ocr"] = True
        base["estado"] = "EVIDENCIA_INSUFICIENTE"
        return False
    for campo in ("fecha_pago", "periodo", "folio", "institucion"):
        valor = nuevo.get(campo, "")
        actual = base.get(campo, "")
        vacio = not actual or (
            campo == "institucion" and "no identificada" in str(actual).lower()
        )
        if vacio and valor and "no identificada" not in str(valor).lower():
            base[campo] = valor
        elif not vacio and valor and actual != valor:
            base[f"conflicto_{campo}_vision"] = True
            base["estado"] = "EVIDENCIA_INSUFICIENTE"
    base["fuente_rescate"] = "Google Vision (validación OCR alternativa)"
    if any(str(k).startswith("conflicto_") and v for k,v in base.items()):
        base["observacion"] = (
            str(base.get("observacion", "")) +
            " | Lecturas contradictorias: confirmar contra PDF original."
        ).strip(" |")
    # La lectura por Vision es documental y no verifica el estado en la AFP.
    return True


def rescatar_con_vision(contenido: bytes, info: dict, cliente_supabase,
                       cliente_vision=None) -> dict:
    """Mejora campos faltantes sin declarar que un lote incompleto está pagado.

    No enviar ninguna página si Vision no está habilitada. Si se agotó la
    cuota, mantener el resultado Tesseract sin inferir impago.
    """
    info = dict(info)
    if not vision_habilitada():
        info["vision_estado"] = "deshabilitado"
        info["vision_paginas"] = []
        return info

    max_paginas = _entero_env("GALANT_VISION_MAX_PAGINAS_PDF", 2, 0, 3)
    paginas = _paginas_candidatas(info, max_paginas)
    info["vision_estado"] = "no_necesario" if not paginas else "ejecutado"
    info["vision_paginas"] = []
    info["vision_errores"] = 0
    info["vision_cuota_agotada"] = False
    comprobantes = [dict(x) for x in info.get("comprobantes", [])]
    if not paginas:
        return info

    with fitz.open(stream=contenido, filetype="pdf") as pdf:
        for numero in paginas:
            try:
                permitido = _reservar_unidad(cliente_supabase)
            except Exception:
                LOG.warning("No se pudo verificar cuota Vision; omitiendo rescate.")
                info["vision_estado"] = "sin_cuota_verificable"
                break
            if not permitido:
                info["vision_cuota_agotada"] = True
                info["vision_estado"] = "cuota_agotada"
                break
            info["vision_paginas"].append(numero)
            try:
                texto = _texto_google_vision(pdf[numero - 1], cliente_vision)
                rec = _interpretar(texto, numero, "Google Vision")
                if rec is not None:
                    _combinar_con_precaucion(comprobantes, rec)
            except Exception:
                info["vision_errores"] += 1
                LOG.warning("Fallo OCR alternativo en página %d", numero)
    info["comprobantes"] = comprobantes
    info["revision_integral"] = False  # jamás declarar lote completo por rescate
    return info
