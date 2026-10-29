"""Trabajador Python GALANT.
Ejecutar SOLO en infraestructura privada (nunca en navegador ni Next.js).
Lee trabajos en Supabase y aplica los lectores OCR existentes.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

from supabase import create_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from pago_documental import analizar_pago_pdf  # noqa: E402
from worker.vision_rescue import rescatar_con_vision  # noqa: E402

BUCKET = "galant-documentos"
LOG = logging.getLogger("galant.worker")


def construir_resultado(tipo: str, pdf: bytes, archivo: str, max_paginas: int,
                        lector_vision=None) -> tuple[str, dict]:
    """Estado final y resultado limitado a evidencias documentales."""
    if tipo == "cotizaciones":
        info = analizar_pago_pdf(pdf, archivo, max_paginas_ocr=max_paginas)
        if lector_vision is not None:
            info = lector_vision(pdf, info)
        recibos = info.get("comprobantes", [])
        existe_conflicto = any(
            r.get("conflicto_fecha_ocr")
            or r.get("conflicto_folio_ocr")
            or r.get("conflicto_institucion_ocr")
            or any(k.startswith("conflicto_") and v for k,v in r.items())
            or r.get("estado") in (
                "FECHA_REQUIERE_CONFIRMACION",
                "EVIDENCIA_INSUFICIENTE",
                "DECLARACION_SIN_PAGO_IDENTIFICADO",
                "PAGO_POSTERIOR_DOCUMENTADO_REVISAR",
            )
            or not r.get("folio")
            or "no identificada" in str(r.get("institucion", "")).lower()
            or not r.get("periodo")
            or not r.get("fecha_pago")
            for r in recibos
        )
        # No aprobar un archivo completo por hallar sólo una de sus instituciones.
        parcial = not info.get("revision_integral", False)
        estado = (
            "completado" if recibos and not existe_conflicto and not parcial
            else "requiere_revision"
        )
        return estado, {
            "tipo": tipo,
            "comprobantes": recibos,
            "paginas": info.get("paginas", 0),
            "paginas_ocr": info.get("paginas_ocr", 0),
            "vision_estado": info.get("vision_estado", "deshabilitado"),
            "vision_paginas": info.get("vision_paginas", []),
            "vision_errores": info.get("vision_errores", 0),
            "cobertura": "completa_texto" if not parcial else "parcial_ocr",
            "observacion": (
                "La evidencia documental no equivale a verificación oficial. "
                "Revisar cobertura y folios antes de aprobar el período."
            ),
        }

    if tipo == "f30_1":
        from f301_lector import analizar_f301
        certificados, _, incidencias = analizar_f301([(pdf, archivo)])
        if not certificados:
            return "requiere_revision", {
                "tipo": tipo, "estado_declarado": "SIN_LECTURA",
                "observacion": "No fue posible leer un certificado F30-1 verificable."
            }
        periodos = {str(c.get("periodo") or "") for c in certificados}
        estados = {str(c.get("cotizaciones") or "") for c in certificados}
        estado_declarado = (
            next(iter(estados)) if len(estados) == 1 else "VARIOS_ESTADOS"
        )
        return "requiere_revision", {
            "tipo": tipo,
            "periodo": next(iter(periodos)) if len(periodos) == 1 else "",
            "estado_declarado": estado_declarado,
            "certificados": len(certificados),
            "observaciones": len(incidencias),
            "observacion": "Declaración documental del F30-1: verificar autenticidad ante la DT."
        }

    raise ValueError("Tipo de documento no admitido")


def ejecutar_una_vez(client, limite: int, max_paginas: int) -> tuple[int, int]:
    jobs = client.rpc("galant_reclamar_trabajos", {"max_trabajos": limite}).execute().data or []
    finalizados = 0
    for job in jobs:
        job_id = str(job["id"])
        LOG.info("Procesando trabajo %s, tipo %s", job_id, job["tipo"])
        try:
            data = client.storage.from_(BUCKET).download(job["ruta_storage"])
            if not data or not data.startswith(b"%PDF-"):
                raise ValueError("Archivo PDF inválido o vacío")
            estado, resultado = construir_resultado(
                job["tipo"], data, job["archivo"], max_paginas,
                lector_vision=lambda pdf, info: rescatar_con_vision(
                    pdf, info, cliente_supabase=client
                ),
            )
            client.table("galant_documentos").update({
                "estado": estado,
                "resultado": resultado,
                "error": None,
                "procesado_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", job_id).execute()
            finalizados += 1
            LOG.info("Trabajo %s finalizó: %s", job_id, estado)
        except Exception as exc:
            # Nunca registrar texto OCR privado ni documentos en logs.
            LOG.warning("Fallo en trabajo %s (tipo=%s)", job_id, type(exc).__name__)
            client.table("galant_documentos").update({
                "estado": "error",
                "error": "No se pudo completar el OCR (" + type(exc).__name__ + ")",
            }).eq("id", job_id).execute()
    return len(jobs), finalizados


def main() -> None:
    parser = argparse.ArgumentParser(description="Procesador documental privado de GALANT")
    parser.add_argument("--once", action="store_true", help="Procesar lote actual y salir")
    parser.add_argument("--limit", type=int, default=3, help="Máximo trabajos por lote")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = os.environ.get("SUPABASE_URL")
    secret = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not secret:
        raise SystemExit("Faltan SUPABASE_URL y SUPABASE_SECRET_KEY en entorno PRIVADO")
    client = create_client(url, secret)
    max_pages = max(1, min(int(os.environ.get("GALANT_MAX_OCR_PAGES", "12")), 100))
    poll_seconds = max(2, int(os.environ.get("GALANT_POLL_SECONDS", "10")))
    while True:
        total, done = ejecutar_una_vez(client, max(1, min(args.limit, 10)), max_pages)
        LOG.info("Lote: %d trabajos, %d procesados", total, done)
        if args.once:
            break
        if not total:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
