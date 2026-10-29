"""Excel real compatible con Microsoft Excel, no CSV renombrado."""
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from reporte_nomina_excel import generar_excel_nomina

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _ejemplo():
    return [
        {
            "archivo": "ejemplo.pdf", "nombre": "TRABAJADOR DE PRUEBA",
            "rut": "12.345.678-5", "sistema": "Fonasa",
            "institucion_salud": "Fonasa", "periodo": "2026-09",
            "dias": 11, "situacion": "Pago respaldado en PDF",
            "fecha_pago": "23/10/2026", "folio": "2000000000000000",
            "pagina_planilla": 4, "pagina_comprobante": 3,
            "observacion": "",
        },
        {
            "archivo": "ejemplo.pdf", "nombre": "SEGUNDO TRABAJADOR",
            "rut": "11.111.111-1", "sistema": "Isapre",
            "institucion_salud": "Isapre Consalud", "periodo": "2026-09",
            "dias": None, "situacion": "Días por verificar",
            "fecha_pago": "23/10/2026", "folio": "2000000000000001",
            "pagina_planilla": 8, "pagina_comprobante": 7,
            "observacion": "No inventar días",
        },
    ]


def _abrir():
    raw = generar_excel_nomina(_ejemplo(), [
        {"archivo": "ejemplo2.pdf", "detalle": "Isapre sin nómina"}
    ])
    assert raw[:2] == b"PK"
    return ZipFile(BytesIO(raw))


def test_xlsx_tiene_hojas_trabajadores_resumen_y_revisar():
    with _abrir() as z:
        xml = z.read("xl/workbook.xml")
        root = ET.fromstring(xml)
        nombres = {
            s.attrib["name"] for s in root.findall(".//m:sheet", NS)
        }
    assert nombres == {"Trabajadores", "Resumen", "Revisar"}


def test_fonasa_isapre_rut_y_periodo_no_se_pierden():
    with _abrir() as z:
        contenido = z.read("xl/sharedStrings.xml").decode("utf-8")
    assert "TRABAJADOR DE PRUEBA" in contenido
    assert "SEGUNDO TRABAJADOR" in contenido
    assert "12.345.678-5" in contenido
    assert "Isapre Consalud" in contenido
    assert "2026-09" in contenido


def test_once_dias_son_celda_numerica_no_texto():
    with _abrir() as z:
        xml = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        cells = {
            c.attrib["r"]: c
            for c in xml.findall(".//m:c", NS)
        }
    assert cells["G2"].find("m:v", NS).text == "11"
    assert cells["G3"].find("m:v", NS) is None


def test_no_aceptar_formula_inyectada_desde_pdf():
    dato = _ejemplo()
    dato[0]["nombre"] = "=HYPERLINK(\"http://evil.invalid\",\"hack\")"
    raw = generar_excel_nomina(dato)
    with ZipFile(BytesIO(raw)) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        shared = z.read("xl/sharedStrings.xml").decode("utf-8")
    assert "HYPERLINK" in shared
    assert '<f>' not in xml


def test_exportar_sin_trabajadores_no_fabrica_datos():
    raw = generar_excel_nomina([])
    with ZipFile(BytesIO(raw)) as z:
        assert "xl/worksheets/sheet1.xml" in z.namelist()
