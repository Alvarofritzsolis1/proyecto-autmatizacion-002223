"""Pruebas de integración que evitan presentar resultados OCR viejos de Streamlit.

Estas pruebas no incluyen PDF privados ni datos identificatorios.
"""
from pathlib import Path
import ast


APP = Path(__file__).resolve().parents[1] / "app.py"


def _codigo():
    codigo = APP.read_text(encoding="utf-8")
    ast.parse(codigo)  # validar además sintaxis de la aplicación real
    return codigo


def test_la_version_es_parte_de_firma_documental():
    codigo = _codigo()
    funcion = codigo.split("def _firma_actual():", 1)[1].split("\nif st.button(", 1)[0]
    assert 'h.update(VERSION.encode("utf-8"))' in funcion


def test_un_click_reprocesa_y_descarta_cache_anterior():
    codigo = _codigo()
    boton = codigo.split('if st.button(', 1)[1].split("    inicio = time.perf_counter()", 1)[0]
    assert 'st.session_state.pop("reporte_galant", None)' in boton
    assert 'st.session_state.pop("galant_cache_pago", None)' in boton


def test_sesion_antigua_no_puede_mostrar_tabla_como_actual():
    codigo = _codigo()
    assert 'reporte.get("engine_release") != VERSION' in codigo
    assert '"engine_release": VERSION' in codigo
    assert 'st.session_state.pop("reporte_galant", None)' in codigo


def test_editor_de_dias_no_reutiliza_estado_entre_versiones():
    codigo = _codigo()
    assert 'key="correccion_fonasa_" + VERSION + "_" + reporte["firma"][:12]' in codigo


def test_dias_ilegibles_no_se_muestran_como_texto_none():
    codigo = _codigo()
    assert 'tabla_fonasa["Días trabajados"] = pd.to_numeric(' in codigo
    assert ').astype("Int64")' in codigo


def test_version_nueva_identificable_en_pantalla():
    codigo = _codigo()
    assert 'VERSION = "18.6.2-Fonasa-actualizado"' in codigo
    assert 'st.caption(f"Control documental de contratistas · {VERSION}")' in codigo
