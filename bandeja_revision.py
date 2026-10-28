"""Bandeja de excepciones documentales con evidencia y acción concreta.

Inspirado en el patrón de revisión humana selectiva de plataformas de IDP.
No infiere incumplimientos ni modifica los resultados del motor.
"""
from __future__ import annotations

from hashlib import sha256
import re
import pandas as pd

COLUMNAS_BANDEJA = [
    "prioridad", "categoria", "contratista", "periodo", "rut_trabajador",
    "archivo", "pagina", "hallazgo", "accion_recomendada", "estado",
    "referencia"
]
ORDEN = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}


def _valor(dato) -> str:
    if dato is None:
        return ""
    try:
        if pd.isna(dato):
            return ""
    except (ValueError, TypeError):
        pass
    texto = str(dato).strip()
    return "" if texto.lower() in ("nan", "none", "<na>") else texto


def _detalle_revision(texto: str) -> tuple[str, str]:
    """Separa problemas de extracción de diferencias documentales reales."""
    k = texto.lower()
    # Advertencias del extractor no significan que el RUT del trabajador sea
    # inválido. Evitar elevar todas las filas a prioridad ALTA por una palabra
    # "RUT inválido" dentro de un mensaje técnico global.
    if any(x in k for x in (
        "lectura parcial del pdf",
        "totales del comprobante no cuadran",
        "existen filas no interpretadas",
        "filas sin interpretar",
    )):
        return (
            "Lectura pendiente",
            "Revisar las filas no reconocidas del PDF. No significa deuda ni RUT inválido."
        )
    if re.search(r"r[uú]t.*(?:invalido|inv[aá]lido|d[ií]gito verificador)", k):
        return ("RUT sin validación", "Cotejar RUT con el original y corregir OCR si corresponde.")
    if "duplicad" in k:
        return ("Posible duplicado", "Revisar archivos y movimientos: no sumar dos veces una misma fila.")
    if "faltan" in k or "falta " in k or "ilegible" in k or "ocr" in k:
        return ("Extracción incompleta o no verificable",
                "Abrir la página indicada y cotejar campos con el comprobante original.")
    if "diferencia" in k or "descuadr" in k or "no coinciden" in k:
        return ("Diferencia documental",
                "Comparar base imponible y días del RUT entre AFP, Salud y Mutual/ISL.")
    if "dias" in k or "días" in k:
        return ("Días por confirmar", "Verificar período y días en el anexo individual.")
    return ("Observación documental", "Revisar la evidencia indicada antes de emitir una conclusión.")


def generar_bandeja(
    certificados=None, incidencias=None, detalle=None, log=None,
    cruce_detalle=None, cruce_resumen=None, errores=None, duplicados=None,
) -> pd.DataFrame:
    """Construye cola deduplicada de hallazgos sin crear conformidades nuevas."""
    certificados = certificados or []
    incidencias = incidencias or []
    errores = errores or []
    duplicados = duplicados or []
    filas = []
    claves = set()

    def agregar(prioridad, categoria, hallazgo, accion, archivo="", pagina="",
                contratista="", periodo="", rut="", referencia=""):
        registro = {
            "prioridad": prioridad, "categoria": categoria,
            "contratista": _valor(contratista), "periodo": _valor(periodo),
            "rut_trabajador": _valor(rut), "archivo": _valor(archivo),
            "pagina": _valor(pagina), "hallazgo": _valor(hallazgo),
            "accion_recomendada": _valor(accion),
            "estado": "PENDIENTE_REVISION",
            "referencia": _valor(referencia),
        }
        identidad = (
            registro["categoria"], registro["archivo"], registro["pagina"],
            registro["rut_trabajador"], registro["hallazgo"]
        )
        if identidad not in claves:
            claves.add(identidad)
            filas.append(registro)

    for cert in certificados:
        archivo = cert.get("archivo", "")
        folio = cert.get("folio", "")
        base = {
            "archivo": archivo, "contratista": cert.get("contratista", ""),
            "periodo": cert.get("periodo", ""), "referencia": folio
        }
        total = cert.get("trabajadores_declarados")
        identificados = cert.get("trabajadores_identificados")
        if total is not None and identificados is not None and int(identificados) != int(total):
            agregar("ALTA", "F30-1",
                    f"Nómina recuperada: {identificados} de {total} trabajadores.",
                    "Revisar la tabla de trabajadores y recuperar los RUT no leídos.",
                    pagina=cert.get("paginas", ""), **base)
        if not _valor(cert.get("rut_contratista")):
            agregar("ALTA", "F30-1", "No se pudo validar RUT de empresa.",
                    "Contrastar encabezado del certificado con la razón social.",
                    pagina=cert.get("paginas", ""), **base)
        if not _valor(cert.get("periodo")):
            agregar("ALTA", "F30-1", "Período certificado no identificado.",
                    "Revisar el apartado de período certificado, no el nombre del archivo.",
                    pagina=cert.get("paginas", ""), **base)
        pago = _valor(cert.get("cotizaciones"))
        if pago == "SIN_RESUMEN_NO_SE_PUEDE_CONFIRMAR":
            agregar("MEDIA", "F30-1",
                    "Falta el resumen de cotizaciones del certificado.",
                    "Solicitar el certificado completo. No concluir impago a partir de la ausencia.",
                    pagina=cert.get("paginas", ""), **base)
        elif pago == "NO_DECLARADO_EN_PDF":
            agregar("ALTA", "F30-1",
                    "El PDF informa cotizaciones no pagadas.",
                    "Revisar el resumen y respaldos antes de determinar obligaciones pendientes.",
                    pagina=cert.get("paginas", ""), **base)
        elif pago in ("", "NO_LEIBLE"):
            agregar("MEDIA", "F30-1",
                    "No se pudo interpretar el estado de pago declarado.",
                    "Leer visualmente el resumen original y verificar en el organismo correspondiente.",
                    pagina=cert.get("paginas", ""), **base)

    for item in incidencias:
        d = _valor(item.get("detalle"))
        if not d or "Falta página de resumen" in d or "Nómina incompleta" in d:
            continue  # Ya incorporados como hallazgos agrupados por certificado.
        agregar("MEDIA", "OCR F30-1", d,
                "Revisar el archivo y la página de origen; no corregir por suposición.",
                archivo=item.get("archivo", ""), referencia=item.get("folio", ""))

    if detalle is not None and not detalle.empty:
        for _, fila in detalle.iterrows():
            motivo = _valor(fila.get("motivo_revision"))
            estado = _valor(fila.get("estado_auditoria"))
            problema, accion = _detalle_revision(motivo)
            prioridad = "ALTA" if estado.startswith("ALERTA") else "MEDIA"
            if "RUT sin validación" == problema:
                prioridad = "ALTA"
            if problema == "Lectura pendiente":
                # Un problema de extracción del ARCHIVO no debe aparecer como
                # tres errores de RUT individuales. Se muestra una sola vez.
                prioridad = "MEDIA"
                agregar(
                    prioridad, "Cotizaciones",
                    "Hay filas o montos que GALANT no logró leer completamente.",
                    accion, archivo=fila.get("archivo_origen", ""),
                    contratista=fila.get("contratista_nombre", ""),
                    periodo=fila.get("periodo_remuneracion", "")
                )
            else:
                agregar(
                    prioridad, "Cotizaciones", problema + ": " + motivo[:240],
                    accion, archivo=fila.get("archivo_origen", ""),
                    pagina=fila.get("hoja_o_pagina", ""),
                    contratista=fila.get("contratista_nombre", ""),
                    periodo=fila.get("periodo_remuneracion", ""),
                    rut=fila.get("trabajador_rut", ""), referencia=estado
                )

    if cruce_resumen is not None and not cruce_resumen.empty:
        for _, fila in cruce_resumen.iterrows():
            estado = _valor(fila.get("resultado"))
            if estado in ("SIN_COMPROBANTE_COMPARABLE", "NO_COMPARABLE"):
                agregar(
                    "MEDIA", "Cruce F30-1/Previred",
                    ("No hay cotizaciones comparables para empresa y período."
                     if estado == "SIN_COMPROBANTE_COMPARABLE"
                     else "Faltan datos para cruzar F30-1 con Previred."),
                    fila.get("accion", ""),
                    archivo=fila.get("archivo", ""),
                    contratista=fila.get("contratista", ""),
                    periodo=fila.get("periodo", ""),
                    referencia=fila.get("certificado", "")
                )

    if cruce_detalle is not None and not cruce_detalle.empty:
        pendientes = {
            "RUT_NO_HALLADO_PREVIRED", "MULTIPLES_REGISTROS_PREVIRED"
        }
        for _, fila in cruce_detalle.iterrows():
            estado = _valor(fila.get("resultado"))
            if estado not in pendientes:
                continue  # No duplicar problemas ya presentes en la matriz Previred.
            agregar(
                "MEDIA", "Cruce F30-1/Previred",
                ("RUT F30-1 no hallado en cotizaciones del mismo mes."
                 if estado == "RUT_NO_HALLADO_PREVIRED"
                 else "RUT con movimientos repetidos en cotizaciones."),
                fila.get("accion", ""), archivo=fila.get("archivo_f301", ""),
                pagina=fila.get("pagina_f301", ""),
                periodo=fila.get("periodo", ""), rut=fila.get("rut_trabajador", ""),
                contratista=fila.get("contratista", ""),
                referencia=fila.get("certificado", "")
            )

    if log is not None and not log.empty:
        for _, item in log.iterrows():
            if _valor(item.get("resultado")).upper() == "ERROR":
                agregar("ALTA", "Archivo",
                        "No se procesó correctamente un documento.",
                        _valor(item.get("detalle"))[:350] or
                        "Revisar formato, integridad y legibilidad del archivo.",
                        archivo=item.get("archivo", ""))
    for error in errores:
        agregar("ALTA", "Archivo", "Falló un grupo de documentos.",
                _valor(error)[:350])
    for nombre, otro in duplicados:
        agregar("BAJA", "Archivo", "Archivo repetido omitido.",
                f"Se conserva el archivo idéntico «{_valor(otro)}» sin sumar dos veces.",
                archivo=nombre)

    if not filas:
        return pd.DataFrame(columns=COLUMNAS_BANDEJA)
    result = pd.DataFrame(filas, columns=COLUMNAS_BANDEJA)
    result["__orden"] = result["prioridad"].map(ORDEN)
    result = result.sort_values(
        ["__orden", "categoria", "archivo", "rut_trabajador"], kind="stable"
    ).drop(columns=["__orden"])
    return result.reset_index(drop=True)


def resumen_calidad(certificados, matriz, bandeja) -> dict:
    """Indicadores de cobertura, no porcentajes inventados de acierto OCR."""
    certs = certificados or []
    completos = sum(
        int(c["trabajadores_declarados"]) == int(c["trabajadores_identificados"])
        for c in certs if c.get("trabajadores_declarados") is not None
        and c.get("trabajadores_identificados") is not None
    )
    revisar = 0 if matriz is None or matriz.empty else int(
        matriz["estado_auditoria"].ne("CONFORME").sum()
    )
    return {
        "certificados": len(certs),
        "nominas_completas": completos,
        "filas_cotizaciones": 0 if matriz is None else len(matriz),
        "filas_con_observacion": revisar,
        "pendientes_prioridad_alta": (
            0 if bandeja is None or bandeja.empty
            else int(bandeja["prioridad"].eq("ALTA").sum())
        ),
    }
