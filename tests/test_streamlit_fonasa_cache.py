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
    assert 'key="edicion_manual_" + VERSION + "_" + reporte["firma"][:12]' in codigo


def test_dias_ilegibles_no_se_muestran_como_texto_none():
    codigo = _codigo()
    assert 'tabla_fonasa["Días trabajados"] = pd.to_numeric(' in codigo
    assert ').astype("Int64")' in codigo


def test_version_nueva_identificable_en_pantalla():
    codigo = _codigo()
    asignaciones = [
        nodo for nodo in ast.parse(codigo).body
        if isinstance(nodo, ast.Assign)
        and any(
            isinstance(objetivo, ast.Name) and objetivo.id == "VERSION"
            for objetivo in nodo.targets
        )
    ]
    assert len(asignaciones) == 1
    version = ast.literal_eval(asignaciones[0].value)
    assert isinstance(version, str) and "." in version and "-" in version
    assert "cobertura_parcial" in codigo
    assert 'f"Control documental de contratistas · {VERSION} "' in codigo


def test_runtime_shows_real_code_and_uploaded_pdf_fingerprints():
    codigo = _codigo()
    assert "def _huella_motor():" in codigo
    assert 'estado_lector_fonasa()' in codigo
    assert 'evidencia["sha256_pdf"]' in codigo
    assert '"tesseract": _version_tesseract()' in codigo


def test_ocr_output_not_overwritten_by_manual_editor():
    codigo = _codigo()
    assert "st.dataframe(" in codigo
    assert "with st.expander(\"Corregir manualmente días cotejados con el PDF\")" in codigo
    assert "GALANT_Nomina_Salud_lectura_original.csv" in codigo
    assert "GALANT_Nomina_Salud_correcciones_manuales.csv" in codigo


def test_debug_can_render_source_cell_and_download_private_trace():
    codigo = _codigo()
    assert "Diagnóstico verificable del OCR de salud" in codigo
    assert "GALANT_Diagnostico_Salud_Privado.json" in codigo
    assert 'muestra = im.crop((' in codigo


def test_usar_modulo_real_con_contrato_y_no_import_cacheado():
    codigo = _codigo()
    assert "from fonasa_runtime import extraer_fonasa_con_contrato" in codigo
    assert "nomina = extraer_fonasa_con_contrato(" in codigo
    assert '"lector_cargado": _estado_motor()' in codigo
    assert "sha256_codigo_activo_16" in Path(
        __file__
    ).resolve().parents[1].joinpath("fonasa_runtime.py").read_text(
        encoding="utf-8"
    )


def test_solo_nomina_trabajadores_y_excel_sin_tabla_de_seis_recibos():
    codigo = _codigo()
    assert 'st.markdown("#### Trabajadores y días cotizados")' in codigo
    assert 'st.markdown("#### Estado documental del pago de cotizaciones")' not in codigo
    assert "GALANT_Trabajadores_Dias_Cotizados.xlsx" in codigo
    assert "generar_excel_nomina(" in codigo


def test_candidatos_de_salud_incluyen_isapre():
    codigo = _codigo()
    assert 'e.get("institucion") == "Fonasa"' in codigo
    assert '.startswith("isapre")' in codigo
    assert 'instituciones_candidatas=instituciones_salud' in codigo
    assert "construir_nomina_salud(" in codigo
