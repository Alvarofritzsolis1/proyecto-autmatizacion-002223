import json
import pandas as pd
from chat_asesor import anonimizar, resumen_seguro, diagnostico_local
from aprendizaje_continuo import evaluar_candidato, leer_metadatos_validos

def test_chat_oculta_rut_y_correo():
    texto = anonimizar("12.345.678-5 persona@empresa.cl")
    assert "12.345.678-5" not in texto
    assert "persona@empresa.cl" not in texto

def test_contexto_solo_metricas():
    resultado = {"matriz": pd.DataFrame([
        {"trabajador_rut": "123456785", "trabajador_nombre": "Dato privado",
         "estado_auditoria": "REVISAR_DATOS"}])}
    contexto = json.dumps(resumen_seguro(resultado))
    assert "123456785" not in contexto and "Dato privado" not in contexto
    assert "REVISAR_DATOS" in contexto

def test_sin_ia_no_se_inventa_validacion():
    assert "no es equivalente" in diagnostico_local("Certificado F30-1")

def test_aprendizaje_no_entrena_sin_aprobaciones(tmp_path):
    assert leer_metadatos_validos(str(tmp_path / "ninguno.jsonl")) == []
    assert evaluar_candidato([])["estado"] == "faltan_ejemplos_verificados"
