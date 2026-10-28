"""Pruebas de conexión Gemini SIN ejecutar llamadas reales ni usar claves."""
import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from gemini_cliente import (
    DEFAULT_MODEL,
    GeminiError,
    consultar_gemini,
    preparar_solicitud,
)
from chat_asesor import anonimizar, respuesta_ia


class RespuestaFalsa:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body[:size]


def test_modelo_gratuito_y_cantidad_acotada_de_mensajes():
    url, payload = preparar_solicitud(
        "¿Por qué faltan trabajadores?",
        {"trabajadores": 4, "estados": {"REVISAR_DATOS": 1}},
        [{"role": "user", "content": "hola"}] * 10,
    )
    assert DEFAULT_MODEL == "gemini-3.5-flash-lite"
    assert url.endswith(f"/{DEFAULT_MODEL}:generateContent")
    assert len(payload["contents"]) == 7
    assert "trabajadores" in payload["systemInstruction"]["parts"][0]["text"]


def test_usa_clave_solo_en_cabecera_no_en_json():
    capturado = {}

    def responder(request, timeout):
        capturado["request"] = request
        capturado["timeout"] = timeout
        return RespuestaFalsa({
            "candidates": [{"content": {"parts": [{"text": "Revisa la página 3."}]}}]
        })

    with patch("gemini_cliente.urlopen", side_effect=responder):
        texto = consultar_gemini(
            "Ayuda",
            {"trabajadores": 2},
            [],
            "CLAVE_SUPER_PRIVADA",
        )
    assert texto == "Revisa la página 3."
    assert capturado["request"].get_header("X-goog-api-key") == "CLAVE_SUPER_PRIVADA"
    assert "CLAVE_SUPER_PRIVADA" not in capturado["request"].full_url
    assert b"CLAVE_SUPER_PRIVADA" not in capturado["request"].data
    assert capturado["timeout"] == 25


def test_privacidad_anonimiza_pregunta_y_historial():
    guardado = {}

    def stub(**kwargs):
        guardado.update(kwargs)
        return "Pide revisar el comprobante."

    with patch("gemini_cliente.consultar_gemini", side_effect=stub):
        respuesta_ia(
            "El RUT 12.345.678-5 y correo user@example.cl no aparecen",
            {"trabajadores": 1},
            [{"role": "assistant", "content": "Contacto +56 9 1234 5678"}],
            "clave",
        )
    entrada = json.dumps({"pregunta": guardado["pregunta"],
                          "historial": guardado["historial"]})
    assert "12.345.678-5" not in entrada
    assert "user@example.cl" not in entrada
    assert "1234 5678" not in entrada
    assert "RUT OMITIDO" in entrada


@pytest.mark.parametrize("codigo,esperado", [
    (401, "clave"),
    (403, "clave"),
    (429, "límite gratuito"),
    (404, "modelo"),
    (500, "temporal"),
])
def test_errores_entendibles_y_sin_exponer_secreto(codigo, esperado):
    with patch("gemini_cliente.urlopen", side_effect=HTTPError(
        "https://fake.invalid", codigo, "error", None, BytesIO(b"no publicar")
    )):
        with pytest.raises(GeminiError, match=esperado) as err:
            consultar_gemini("hola", {}, [], "CLAVE_PRIVADA")
    assert "CLAVE_PRIVADA" not in str(err.value)


def test_no_hace_solicitud_si_falta_clave():
    with patch("gemini_cliente.urlopen") as mock:
        with pytest.raises(GeminiError, match="GEMINI_API_KEY"):
            consultar_gemini("hola", {}, [], "")
        mock.assert_not_called()


def test_modelo_invalido_bloqueado():
    with pytest.raises(GeminiError, match="modelo"):
        preparar_solicitud("hola", {}, [], "https://dominio-inseguro")


def test_respuesta_vacia_no_inventa_resultado():
    with patch("gemini_cliente.urlopen", return_value=RespuestaFalsa({"candidates": []})):
        with pytest.raises(GeminiError, match="respuesta de texto"):
            consultar_gemini("hola", {}, [], "clave")


def test_usuario_sin_poner_datos_personales():
    assert "usuario@" not in anonimizar("contacto usuario@ejemplo.cl")
