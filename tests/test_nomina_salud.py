"""Contratos de coberturas Fonasa/Isapre y asociación de recibos PREVIRED."""
from nomina_salud import construir_nomina_salud, _compatibles


def trabajador(rut, nombre, institucion, dias, pagina):
    return {
        "archivo": "simulado.pdf",
        "trabajador_nombre": nombre,
        "trabajador_rut": rut,
        "institucion_salud": institucion,
        "sistema_salud": (
            "Isapre" if institucion.startswith("Isapre") else "Fonasa"
        ),
        "pagina_fonasa": pagina,
        "dias_trabajados_fonasa": dias,
        "traza_dias": [
            {"valor": dias, "metodo": "ocr_numero"} if dias is not None
            else {"valor": None, "metodo": "dias_no_informados_en_planilla_isapre"}
        ],
    }


def recibo(institucion, pagina, estado="PAGO_RESPALDADO_EN_DOCUMENTO"):
    return {
        "institucion": institucion,
        "pagina": pagina,
        "periodo": "2026-09",
        "fecha_pago": "23/10/2026",
        "folio": f"20002609010{pagina:07}",
        "estado": estado,
    }


def test_fonasa_y_isapre_aparecen_en_una_sola_nomina():
    t = [
        trabajador("12.345.678-5", "TRABAJADOR FONASA", "Fonasa", 24, 4),
        trabajador("21.539.151-5", "TRABAJADOR ISAPRE", "Isapre Colmena", None, 8),
    ]
    docs = [{
        "archivo": "simulado.pdf",
        "comprobantes": [
            recibo("Fonasa", 3),
            recibo("Isapre Colmena", 7),
            recibo("AFP Modelo", 9),
        ],
    }]
    filas, alertas = construir_nomina_salud(docs, t)
    assert len(filas) == 2
    assert {f["sistema"] for f in filas} == {"Fonasa", "Isapre"}
    fona = next(f for f in filas if f["sistema"] == "Fonasa")
    isapre = next(f for f in filas if f["sistema"] == "Isapre")
    assert fona["dias"] == 24
    assert fona["situacion"] == "Pago respaldado en PDF"
    assert isapre["dias"] is None
    assert isapre["situacion"] == "Días por verificar"
    assert not alertas


def test_nunca_vincular_pago_fonasa_a_isapre():
    doc = [{
        "archivo": "simulado.pdf",
        "comprobantes": [recibo("Fonasa", 3)],
    }]
    rows, _ = construir_nomina_salud(doc, [
        trabajador("12.345.678-5", "TRABAJADOR ISAPRE", "Isapre Colmena", None, 4)
    ])
    assert len(rows) == 1
    assert rows[0]["fecha_pago"] == ""
    assert rows[0]["situacion"] == "Respaldo pendiente"


def test_nunca_vincular_isapres_distintas():
    assert not _compatibles("Isapre Consalud", "Isapre Colmena")
    assert _compatibles("Isapre Consalud", "Isapre Consalud")
    assert not _compatibles("Fonasa", "Isapre Consalud")
    assert not _compatibles("Salud (institución por confirmar)", "Fonasa")


def test_pago_regularizado_exige_revision():
    rows, _ = construir_nomina_salud([{
        "archivo":"simulado.pdf",
        "comprobantes":[recibo("Fonasa", 3, "PAGO_POSTERIOR_DOCUMENTADO_REVISAR")],
    }], [trabajador("12.345.678-5","TRABAJADOR","Fonasa",27,4)])
    assert rows[0]["situacion"] == "Pago posterior: revisar"


def test_si_no_se_identifica_isapre_no_se_certifica_pago():
    t = trabajador("12.345.678-5", "TRABAJADOR", "Isapre (no identificada)", 11, 4)
    rows, _ = construir_nomina_salud([{
        "archivo": "simulado.pdf",
        "comprobantes": [recibo("Isapre Consalud", 3)],
    }], [t])
    assert rows[0]["situacion"] == "Revisión documental"


def test_alertar_por_isapre_no_leida_incluso_si_hay_otra_isapre():
    docs = [{
        "archivo": "simulado.pdf",
        "comprobantes": [recibo("Isapre Colmena", 3), recibo("Isapre Consalud", 7)],
    }]
    t = [trabajador("12.345.678-5","TRABAJADOR","Isapre Colmena",None,4)]
    rows, alertas = construir_nomina_salud(docs, t)
    assert len(rows) == 1
    assert len(alertas) == 1
    assert "Consalud" in alertas[0]["detalle"]


def test_registros_duplicados_misma_institucion_no_sumar_dias():
    t1 = trabajador("12.345.678-5", "TRABAJADOR", "Fonasa", 24, 4)
    t2 = trabajador("12.345.678-5", "TRABAJADOR", "Fonasa", 27, 4)
    rows, _ = construir_nomina_salud([{
        "archivo":"simulado.pdf",
        "comprobantes":[recibo("Fonasa",3)]
    }], [t1,t2])
    assert len(rows)==1
    assert rows[0]["dias"] is None
    assert rows[0]["situacion"] == "Revisión documental"


def test_si_no_hay_planilla_salud_alertar_sin_inventar_trabajador():
    docs=[{"archivo":"simulado.pdf","comprobantes":[recibo("AFP Modelo",3)]}]
    rows, alertas=construir_nomina_salud(docs,[])
    assert rows==[]
    assert len(alertas)==1
    assert "nómina de salud" in alertas[0]["detalle"]


def test_dias_no_informados_no_se_convierten_en_cero():
    rows, _=construir_nomina_salud([{
        "archivo":"simulado.pdf",
        "comprobantes":[recibo("Isapre Colmena",3)]
    }],[trabajador("12.345.678-5","TRABAJADOR","Isapre Colmena",None,4)])
    assert rows[0]["dias"] is None
    assert rows[0]["situacion"] == "Días por verificar"
