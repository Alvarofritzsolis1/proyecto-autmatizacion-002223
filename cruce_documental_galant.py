"""Cruce documental F30-1 vs Previred: trabajador, empleador y período.

No acredita pago ni autenticidad DT. Los F30-1 pueden tener ámbito de obra,
mientras Previred puede cubrir toda la empresa: no exigir nóminas idénticas.
"""
from __future__ import annotations
from collections import defaultdict
import pandas as pd
from auditoria_laboral import clave_rut, normalizar_periodo

COLUMNAS = ["archivo_f301", "certificado", "contratista", "periodo", "rut_trabajador",
            "trabajador", "resultado", "accion", "estado_previred", "pagina_f301"]

def _str(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()

def conciliar_f301_previred(certificados, nomina, matriz):
    """Comparar solo misma empresa y período; jamás inferir pago de un RUT."""
    if not certificados:
        return pd.DataFrame(columns=COLUMNAS), pd.DataFrame()
    por_clave = defaultdict(list)
    cobertura = set()
    if matriz is not None and not matriz.empty:
        for _, fila in matriz.iterrows():
            empleador = clave_rut(fila.get("contratista_rut"))
            periodo = normalizar_periodo(fila.get("periodo_remuneracion"))
            rut = clave_rut(fila.get("trabajador_rut"))
            if empleador and periodo:
                cobertura.add((empleador, periodo))
                if rut:
                    por_clave[(empleador, periodo, rut)].append(
                        _str(fila.get("estado_auditoria")))

    detalle, resumen = [], []
    for cert in certificados:
        folio, archivo = _str(cert.get("folio")), _str(cert.get("archivo"))
        empleador = clave_rut(cert.get("rut_contratista"))
        periodo = normalizar_periodo(cert.get("periodo"))
        trabajadores = [x for x in nomina if _str(x.get("folio")) == folio
                        and _str(x.get("archivo")) == archivo]
        vistos, estados = set(), []
        for trabajador in trabajadores:
            rut = clave_rut(trabajador.get("trabajador_rut"))
            if not rut or rut in vistos:
                continue
            vistos.add(rut)
            matches = por_clave.get((empleador, periodo, rut), [])
            if not empleador or not periodo:
                estado, accion = ("SIN_IDENTIDAD_O_PERIODO",
                    "Revisar RUT del empleador y período antes de cotejar.")
            elif (empleador, periodo) not in cobertura:
                estado, accion = ("SIN_PREVIRED_MISMO_PERIODO",
                    "Adjuntar cotizaciones del mismo empleador y mes; no significa impago.")
            elif not matches:
                estado, accion = ("RUT_NO_HALLADO_PREVIRED",
                    "Revisar si falta una planilla, si cambió de empleador o hubo error OCR.")
            elif len(matches) > 1:
                estado, accion = ("MULTIPLES_REGISTROS_PREVIRED",
                    "Revisar duplicaciones o movimientos sin sumarlos automáticamente.")
            elif matches[0] != "CONFORME":
                estado, accion = ("RUT_COINCIDE_CON_OBSERVACION",
                    "RUT coincide; revisar observación documental de Previred.")
            else:
                estado, accion = ("RUT_COINCIDE",
                    "RUT, empleador y mes coinciden. No certifica pago ni autenticidad DT.")
            estados.append(estado)
            detalle.append({
                "archivo_f301": archivo, "certificado": folio, "contratista": _str(cert.get("contratista")),
                "periodo": periodo, "rut_trabajador": rut,
                "trabajador": _str(trabajador.get("trabajador_nombre")),
                "resultado": estado, "accion": accion,
                "estado_previred": " | ".join(matches),
                "pagina_f301": trabajador.get("pagina", "")
            })
        declarados = cert.get("trabajadores_declarados")
        incompleta = declarados is not None and len(vistos) != int(declarados)
        if not vistos or incompleta:
            estado_global = "NOMINA_F301_INCOMPLETA"
            accion = "Recuperar RUT faltantes cotejando cada página de nómina."
        elif "SIN_IDENTIDAD_O_PERIODO" in estados:
            estado_global = "NO_COMPARABLE"
            accion = "Completar RUT del contratista y período certificado."
        elif "SIN_PREVIRED_MISMO_PERIODO" in estados:
            estado_global = "SIN_COMPROBANTE_COMPARABLE"
            accion = "Subir Previred del mismo contratista y período."
        elif any(x in estados for x in ("RUT_NO_HALLADO_PREVIRED",
                                         "MULTIPLES_REGISTROS_PREVIRED")):
            estado_global = "REVISAR_NOMINA"
            accion = "Revisar únicamente los RUT marcados y sus respaldos."
        elif "RUT_COINCIDE_CON_OBSERVACION" in estados:
            estado_global = "REVISAR_COTIZACIONES"
            accion = "Consultar observaciones Previred de esos trabajadores."
        else:
            estado_global = "NOMINAS_COINCIDEN"
            accion = "Cruce documental conforme; pago y verificación DT siguen separados."
        resumen.append({
            "archivo": archivo, "certificado": folio,
            "contratista": _str(cert.get("contratista")),
            "rut_empleador": empleador, "periodo": periodo,
            "trabajadores_declarados": declarados,
            "trabajadores_reconocidos": len(vistos),
            "rut_coincidentes": sum(x in ("RUT_COINCIDE", "RUT_COINCIDE_CON_OBSERVACION") for x in estados),
            "rut_pendientes": sum(x not in ("RUT_COINCIDE", "RUT_COINCIDE_CON_OBSERVACION") for x in estados),
            "resultado": estado_global, "accion": accion,
            "pago_en_certificado": _str(cert.get("cotizaciones")),
            "verificacion_dt": "PENDIENTE_PORTAL_DT"
        })
    return pd.DataFrame(detalle, columns=COLUMNAS), pd.DataFrame(resumen)
