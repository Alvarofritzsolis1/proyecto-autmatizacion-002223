"""Nómina única de días declarados y respaldo documental de salud.

El reporte no deduce que un trabajador está pagado solo porque exista
un comprobante de otra AFP o de otro sistema de salud en el mismo PDF.
Las planillas Fonasa e Isapres son fuentes válidas, nunca una excluye a la otra.
"""
from __future__ import annotations

from collections import defaultdict

from fonasa_validacion import comprobar_traza_dias


def _sistema(nombre):
    t = str(nombre or "").casefold()
    if t.startswith("fonasa"):
        return "Fonasa"
    if t.startswith("isapre"):
        return "Isapre"
    return "Por verificar"


def _compatibles(inst_planilla, inst_pago):
    """No asignar un recibo Fonasa a un afiliado de Isapre (ni al revés)."""
    plan = str(inst_planilla or "").casefold()
    recibo = str(inst_pago or "").casefold()
    if not plan or plan.startswith("salud ("):
        return False
    if plan.startswith("fonasa"):
        return recibo == "fonasa"
    if not plan.startswith("isapre") or not recibo.startswith("isapre"):
        return False
    nombre_plan = plan.removeprefix("isapre").strip()
    nombre_pago = recibo.removeprefix("isapre").strip()
    indeterminados = {"", "(no identificada)", "(sin identificar)"}
    if nombre_plan in indeterminados or nombre_pago in indeterminados:
        return True
    return nombre_plan == nombre_pago


def _recibo_para_trabajador(anexo, pagos):
    candidatos = [
        e for e in pagos
        if _compatibles(
            anexo.get("institucion_salud"), e.get("institucion")
        )
    ]
    if not candidatos:
        return None, "No se encontró comprobante de la misma institución"
    pagina = int(anexo.get("pagina_fonasa") or 0)
    # Cuando existen planillas de distintos períodos o instituciones en un
    # mismo archivo, el recibo debe estar cerca del anexo correspondiente.
    candidatos = sorted(
        candidatos, key=lambda e: abs(int(e.get("pagina") or 0) - pagina)
    )
    mejor = candidatos[0]
    distancia = abs(int(mejor.get("pagina") or 0) - pagina)
    if distancia > 2:
        return None, "Comprobante demasiado alejado: confirmar asociación"
    if len(candidatos) > 1:
        segundo = candidatos[1]
        if abs(int(segundo.get("pagina") or 0) - pagina) == distancia:
            return None, "Dos comprobantes igualmente próximos: revisar"
    return mejor, ""


def _estado_respaldo(recibo, dias, conflicto, razon):
    if not recibo:
        return "Respaldo pendiente"
    if conflicto:
        return "Revisión documental"
    if not dias:
        return "Días por verificar"
    if (
        recibo.get("estado") == "PAGO_RESPALDADO_EN_DOCUMENTO"
        and recibo.get("fecha_pago") and recibo.get("folio")
        and recibo.get("periodo")
    ):
        return "Pago respaldado en PDF"
    if (
        recibo.get("estado") == "PAGO_POSTERIOR_DOCUMENTADO_REVISAR"
        and recibo.get("fecha_pago")
    ):
        return "Pago posterior: revisar"
    return "Respaldo por verificar"


def construir_nomina_salud(pagos_documentales, trabajadores_anexos):
    """Entrega filas para Streamlit y Excel; deduplica solo la misma institución.

    La ausencia de un trabajador en Fonasa no excluye trabajadores Isapre.
    """
    indexados = defaultdict(list)
    for documento in pagos_documentales:
        indexados[documento.get("archivo", "")].extend(
            documento.get("comprobantes", [])
        )

    resultados = []
    alertas = []
    agrupados = defaultdict(list)
    for trabajador in trabajadores_anexos:
        rut = trabajador.get("trabajador_rut")
        archivo = trabajador.get("archivo", "")
        if not rut or not trabajador.get("trabajador_nombre"):
            continue
        inst = trabajador.get("institucion_salud", "Salud (institución por confirmar)")
        recibo, motivo = _recibo_para_trabajador(
            trabajador, indexados.get(archivo, [])
        )
        verificacion = comprobar_traza_dias(trabajador)
        dias = verificacion.get("valor_confiable")
        periodo = (recibo or {}).get("periodo", "")
        pagina_doc = (recibo or {}).get("pagina")
        # Una misma persona puede aparecer en dos períodos o dos Isapres.
        # No mezclar esos registros, ni hacer sumas automáticas de días.
        clave = (archivo, rut, inst, periodo, pagina_doc)
        agrupados[clave].append({
            "archivo": archivo,
            "nombre": trabajador.get("trabajador_nombre"),
            "rut": rut,
            "sistema": trabajador.get("sistema_salud") or _sistema(inst),
            "institucion_salud": inst,
            "periodo": periodo,
            "dias": dias,
            "metodo_lectura": verificacion.get("estado", ""),
            "fecha_pago": (recibo or {}).get("fecha_pago", ""),
            "folio": (recibo or {}).get("folio", ""),
            "pagina_planilla": trabajador.get("pagina_fonasa"),
            "pagina_comprobante": pagina_doc,
            "estado_documento": (recibo or {}).get("estado", ""),
            "observacion": motivo or verificacion.get("observacion", ""),
            "conflictos": any(
                str(k).startswith("conflicto_") and bool(v)
                for k, v in (recibo or {}).items()
            ),
        })

    for registros in agrupados.values():
        primero = dict(registros[0])
        dias_registrados = {r["dias"] for r in registros if r["dias"] is not None}
        if len(dias_registrados) > 1:
            primero["dias"] = None
            primero["observacion"] = "Días contradictorios en planillas repetidas"
            primero["conflictos"] = True
        elif len(dias_registrados) == 1 and len(registros) > 1:
            primero["dias"] = next(iter(dias_registrados))
            primero["observacion"] = "Registro duplicado de igual institución; revisar"
        primero["situacion"] = _estado_respaldo(
            bool(primero["folio"] or primero["fecha_pago"])
            and {
                "estado": primero["estado_documento"],
                "fecha_pago": primero["fecha_pago"],
                "folio": primero["folio"],
                "periodo": primero["periodo"],
            },
            primero["dias"], primero["conflictos"], primero["observacion"]
        )
        resultados.append(primero)

    # Alertar cuando existen planillas de Isapre sin anexo de trabajadores
    # identificable. El silencio no equivale a cobertura completa.
    archivos_registrados = {
        r["archivo"] for r in resultados
        if r["sistema"] == "Isapre"
    }
    for doc in pagos_documentales:
        if doc.get("archivo") in archivos_registrados:
            continue
        if any(
            str(e.get("institucion", "")).startswith("Isapre")
            for e in doc.get("comprobantes", [])
        ):
            alertas.append({
                "archivo": doc.get("archivo"),
                "detalle": "Se identificó comprobante Isapre, pero no "
                           "se recuperó una nómina Isapre: revisar anexo.",
            })
    return sorted(
        resultados, key=lambda r: (
            r["archivo"], r["periodo"], r["nombre"], r["institucion_salud"]
        )
    ), alertas
