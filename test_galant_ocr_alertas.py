"""Errores OCR técnicos se asignan a la fila afectada sin ocultar pérdidas de RUT."""
from previred_scan_fast import _advertencias_ocr_por_trabajador

def test_una_fila_ocr_erronea_no_marca_otro_trabajador():
    avisos = [
        "p.4, fila 1: lecturas alternativas de renta [12, 120]; cotejar",
        "p.4, fila 2: días Salud no verificados",
    ]
    primero = {"salud": [(4, 0, 120, 5)]}
    segundo = {"salud": [(4, 1, 150, 7)]}
    assert len(_advertencias_ocr_por_trabajador(avisos, primero)) == 1
    assert "fila 1" in _advertencias_ocr_por_trabajador(avisos, primero)[0]
    assert "fila 2" in _advertencias_ocr_por_trabajador(avisos, segundo)[0]

def test_fila_perdida_sin_rut_es_error_global():
    avisos = ["p.4, fila 5: RUT no reconocido"]
    otro = {"salud": [(4, 0, 120, 5)]}
    assert _advertencias_ocr_por_trabajador(avisos, otro) == avisos

def test_base_desconocida_no_se_oculta():
    avisos = ["p.4, fila 3: base imponible no reconocida"]
    otro = {"salud": [(4, 0, 120, 5)]}
    assert _advertencias_ocr_por_trabajador(avisos, otro) == avisos

def test_header_incompleto_afecta_todos():
    avisos = ["Falta información verificada de empleador o período en cabecera OCR"]
    assert _advertencias_ocr_por_trabajador(avisos, {}) == avisos

def test_duplicados_identicos_no_duplican_razones():
    avisos = ["p.2, fila 1: días Salud no verificados"] * 2
    assert len(_advertencias_ocr_por_trabajador(avisos, {"salud":[(2,0,90,5)]})) == 1
