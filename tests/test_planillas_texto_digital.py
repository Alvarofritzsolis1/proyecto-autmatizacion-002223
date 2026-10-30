"""248 pruebas sobre PDF digitales sintéticos de 1-2 trabajadores.

Se generan con PyMuPDF (sin datos laborales reales). El PDF PRIVADO del
usuario se cotejó aparte, fuera de GitHub, para no publicar su nómina.
"""
import fitz
import pytest

from planillas_texto_digital import extraer_nominas_pdf_texto


def construir_pdf(
    dias=24, seguro_social=None, recibo=True,
    folio_distinto=False, pagina_afp=False,
    rotacion=0, segundo=None,
):
    documento = fitz.open()
    if seguro_social is not None:
        p = documento.new_page(width=792, height=612)
        p.insert_text((30, 30), "SEGURO SOCIAL\nDías\nTrabajados", fontsize=8)
        p.insert_text(
            (120, 200),
            f"1\n12.345.678-5\nPEREZ GOMEZ JUAN ALBERTO\n442.842\n0\n"
            f"3.188\n3.986\n7.883\nJC\n{seguro_social}\n0",
            fontsize=8,
        )
    p = documento.new_page(width=792, height=612)
    if recibo:
        p.insert_text(
            (30, 30), "FONASA PLANILLA DE DECLARACION Y PAGO",
            fontsize=8
        )
        p.insert_text(
            (30, 45), "NÚMERO DE SERIE: 2017260900397682",
            fontsize=8
        )
    p = documento.new_page(width=792, height=612)
    folio = (
        "2000000000000000" if folio_distinto else "2017260900397682"
    )
    p.insert_text(
        (30, 30),
        "ANEXOS DE DETALLE\nNÚMERO DE SERIE: " + folio,
        fontsize=8,
    )
    p.insert_text((30, 75), "Días\nTrabajados", fontsize=8)
    p.insert_text(
        (500, 100), "PERIODO DE REMUNERACIÓN\n09\n2026",
        fontsize=8
    )
    fila = (
        f"1\n12.345.678-5\nPEREZ\nGOMEZ\nJUAN ALBERTO\n{dias}\n"
        "AFP\n442.842\n30.999\n0"
    )
    if rotacion == 90:
        p.insert_text((350, 100), fila, rotate=90, fontsize=8)
    else:
        p.insert_text((120, 170), fila, fontsize=8)
    if segundo is not None:
        p.insert_text(
            (320, 170),
            f"2\n12.345.679-3\nMORALES\nRUIZ\nLUIS FELIPE\n{segundo}\n"
            "AFP\n530.489\n37.134\n0",
            fontsize=8,
        )
    if pagina_afp:
        p = documento.new_page(width=792, height=612)
        p.insert_text((20, 70), "COMPROBANTE AFP MODELO", fontsize=8)
    salida = documento.tobytes()
    documento.close()
    return salida


@pytest.mark.parametrize("dia", range(1, 32))
@pytest.mark.parametrize("rotacion", [0, 90])
def test_62_dias_y_orientaciones_digitales(dia, rotacion):
    r = extraer_nominas_pdf_texto(
        construir_pdf(dias=dia, rotacion=rotacion)
    )
    assert len(r) == 1
    assert r[0]["pagina"] == 2
    assert r[0]["trabajadores"][0]["dias_trabajados_fonasa"] == dia
    assert r[0]["trabajadores"][0]["traza_dias"][0]["metodo"] == (
        "texto_pdf_fonasa"
    )


@pytest.mark.parametrize("dia", range(1, 32))
def test_31_dias_concordantes_seguro_social(dia):
    r = extraer_nominas_pdf_texto(
        construir_pdf(dias=dia, seguro_social=dia)
    )
    assert len(r) == 1
    assert r[0]["trabajadores"][0]["dias_trabajados_fonasa"] == dia
    assert (
        r[0]["trabajadores"][0]["traza_dias"][0]["cotejo_seguro_social"]
        == "coincide"
    )


@pytest.mark.parametrize("dia", range(1, 32))
def test_31_conflictos_de_dias_se_bloquean(dia):
    diferente = 1 if dia != 1 else 2
    r = extraer_nominas_pdf_texto(
        construir_pdf(dias=dia, seguro_social=diferente)
    )
    assert len(r) == 1
    assert r[0]["trabajadores"][0]["dias_trabajados_fonasa"] is None
    assert r[0]["trabajadores"][0]["dias_requieren_revision"]


@pytest.mark.parametrize("dia", range(1, 32))
def test_31_anexos_sin_recibo_no_acreditan_fonasa(dia):
    r = extraer_nominas_pdf_texto(
        construir_pdf(dias=dia, recibo=False)
    )
    assert r == []


@pytest.mark.parametrize("dia", range(1, 32))
def test_31_folios_contradictorios_se_rechazan(dia):
    r = extraer_nominas_pdf_texto(
        construir_pdf(dias=dia, folio_distinto=True)
    )
    assert r == []


@pytest.mark.parametrize("dia", range(1, 32))
def test_31_anexos_con_dos_trabajadores(dia):
    r = extraer_nominas_pdf_texto(
        construir_pdf(dias=dia, segundo=23)
    )
    assert len(r) == 1
    assert len(r[0]["trabajadores"]) == 2
    assert sorted(
        x["dias_trabajados_fonasa"] for x in r[0]["trabajadores"]
    ) == sorted([dia, 23])


@pytest.mark.parametrize("dia", range(1, 32))
def test_31_archivos_con_afp_adicional_no_duplican(dia):
    r = extraer_nominas_pdf_texto(
        construir_pdf(dias=dia, pagina_afp=True)
    )
    assert len(r) == 1
    assert r[0]["trabajadores"][0]["dias_trabajados_fonasa"] == dia
