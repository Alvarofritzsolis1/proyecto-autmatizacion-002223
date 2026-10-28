"""Regresiones GALANT: cruce documental sin PDF privados en repositorio."""
import pandas as pd
from cruce_documental_galant import conciliar_f301_previred

EMPRESA = "123456785"
TRABAJADOR_1 = "100000008"
TRABAJADOR_2 = "111111111"
OTRA_EMPRESA = "999999999"

def certificado(**extra):
    return {
        "archivo": "sintetico.pdf", "folio": "2000/2026/11111111",
        "contratista": "EMPRESA DE PRUEBA", "rut_contratista": EMPRESA,
        "periodo": "2026-09", "trabajadores_declarados": 2,
        "trabajadores_identificados": 2, "cotizaciones": "SI_DECLARADO_EN_PDF",
        **extra
    }

def nomina(ruts=(TRABAJADOR_1, TRABAJADOR_2)):
    return [
        {"archivo": "sintetico.pdf", "folio": "2000/2026/11111111",
         "trabajador_rut": rut, "trabajador_nombre": "PERSONA DE PRUEBA",
         "pagina": 3}
        for rut in ruts
    ]

def previred(filas=None):
    if filas is None:
        filas = [(EMPRESA, "2026-09", TRABAJADOR_1, "CONFORME"),
                 (EMPRESA, "2026-09", TRABAJADOR_2, "CONFORME")]
    return pd.DataFrame(filas, columns=[
        "contratista_rut", "periodo_remuneracion",
        "trabajador_rut", "estado_auditoria"
    ])

def test_cruce_normal_2_de_2():
    detalle, resumen = conciliar_f301_previred([certificado()], nomina(), previred())
    assert len(detalle) == 2
    assert (detalle.resultado == "RUT_COINCIDE").all()
    assert resumen.iloc[0]["resultado"] == "NOMINAS_COINCIDEN"
    assert resumen.iloc[0]["rut_coincidentes"] == 2
    assert resumen.iloc[0]["verificacion_dt"] == "PENDIENTE_PORTAL_DT"

def test_periodo_distinto_no_se_cruza_nunca():
    _, resumen = conciliar_f301_previred(
        [certificado()], nomina(),
        previred([(EMPRESA, "2026-10", TRABAJADOR_1, "CONFORME"),
                 (EMPRESA, "2026-10", TRABAJADOR_2, "CONFORME")])
    )
    assert resumen.iloc[0]["resultado"] == "SIN_COMPROBANTE_COMPARABLE"

def test_otro_empleador_no_se_cruza():
    detalle, _ = conciliar_f301_previred(
        [certificado()], nomina(),
        previred([(OTRA_EMPRESA, "2026-09", TRABAJADOR_1, "CONFORME")])
    )
    assert set(detalle.resultado) == {"SIN_PREVIRED_MISMO_PERIODO"}

def test_trabajador_ausente_solo_se_marca_el_ausente():
    detalle, resumen = conciliar_f301_previred(
        [certificado()], nomina(),
        previred([(EMPRESA, "2026-09", TRABAJADOR_1, "CONFORME")])
    )
    assert list(detalle.resultado) == ["RUT_COINCIDE", "RUT_NO_HALLADO_PREVIRED"]
    assert resumen.iloc[0]["resultado"] == "REVISAR_NOMINA"

def test_previred_con_trabajador_extra_no_es_infraccion():
    df = previred([(EMPRESA, "2026-09", TRABAJADOR_1, "CONFORME"),
                   (EMPRESA, "2026-09", TRABAJADOR_2, "CONFORME"),
                   (EMPRESA, "2026-09", "222222222", "CONFORME")])
    _, resumen = conciliar_f301_previred([certificado()], nomina(), df)
    assert resumen.iloc[0]["resultado"] == "NOMINAS_COINCIDEN"

def test_observacion_previred_no_es_ocultada():
    df = previred([(EMPRESA, "2026-09", TRABAJADOR_1, "CONFORME"),
                   (EMPRESA, "2026-09", TRABAJADOR_2, "REVISAR_DATOS")])
    detalle, resumen = conciliar_f301_previred([certificado()], nomina(), df)
    assert "RUT_COINCIDE_CON_OBSERVACION" in set(detalle.resultado)
    assert resumen.iloc[0]["resultado"] == "REVISAR_COTIZACIONES"

def test_certificado_incompleto_no_se_aprueba_por_coincidencia():
    _, resumen = conciliar_f301_previred(
        [certificado()], nomina((TRABAJADOR_1,)), previred()
    )
    assert resumen.iloc[0]["resultado"] == "NOMINA_F301_INCOMPLETA"

def test_multiples_filasy_no_suma_dias_ni_bases():
    df = previred([(EMPRESA, "2026-09", TRABAJADOR_1, "CONFORME"),
                   (EMPRESA, "2026-09", TRABAJADOR_1, "CONFORME"),
                   (EMPRESA, "2026-09", TRABAJADOR_2, "CONFORME")])
    _, resumen = conciliar_f301_previred([certificado()], nomina(), df)
    assert resumen.iloc[0]["resultado"] == "REVISAR_NOMINA"

def test_sin_documentos_devuelve_tablas_vacias():
    d, r = conciliar_f301_previred([], [], pd.DataFrame())
    assert d.empty and r.empty

def test_cotizaciones_ausentes_no_equivalen_impago():
    _, resumen = conciliar_f301_previred([certificado()], nomina(), pd.DataFrame())
    assert resumen.iloc[0]["resultado"] == "SIN_COMPROBANTE_COMPARABLE"
    assert resumen.iloc[0]["pago_en_certificado"] == "SI_DECLARADO_EN_PDF"

def test_repositorio_sin_chat_gemini_y_titulo_galant():
    from pathlib import Path
    repo = Path(__file__).parent
    app = (repo / "app.py").read_text(encoding="utf-8")
    assert 'page_title="GALANT | Control Documental"' in app
    assert 'st.title("GALANT")' in app
    assert "mostrar_chat" not in app
    assert not (repo / "chat_asesor.py").exists()
    assert not (repo / "gemini_cliente.py").exists()
