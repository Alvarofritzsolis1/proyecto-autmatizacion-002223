"""Chat interno de auditoría. No edita documentos ni reglas de conformidad."""
from __future__ import annotations
import json
import re
import streamlit as st

RUT = re.compile(r"(?<!\w)(?:\d{1,2}\.?\d{3}\.?\d{3}[- ]?[0-9kK])(?!\w)")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+56\s*)?9\s*\d{4}\s*\d{4}(?!\d)")

def anonimizar(mensaje: str) -> str:
    texto = RUT.sub("[RUT OMITIDO]", mensaje)
    texto = EMAIL.sub("[EMAIL OMITIDO]", texto)
    return PHONE.sub("[TELEFONO OMITIDO]", texto)[:1200]

def resumen_seguro(reporte: dict | None) -> dict:
    """Solo métricas, nunca RUT, nombres ni contenido PDF."""
    if not reporte:
        return {"estado": "sin analisis"}
    matriz = reporte.get("matriz")
    if matriz is None:
        return {"estado": "sin matriz"}
    estados = {}
    if "estado_auditoria" in matriz:
        estados = {str(k)[:40]: int(v) for k, v in
                   matriz["estado_auditoria"].fillna("SIN_ESTADO").value_counts().items()}
    return {"trabajadores": int(len(matriz)), "estados": estados}

def diagnostico_local(pregunta: str) -> str:
    texto = pregunta.lower()
    if "ocr" in texto or "escanea" in texto or "leyó" in texto:
        return ("Posible error de lectura OCR: revisa la celda y página original, "
                "compara AFP, Salud y Mutual por RUT, y no corrijas solo porque un total cuadre.")
    if "f30" in texto or "certificado" in texto:
        return ("Verifica periodo certificado, empleador, cantidad de trabajadores y nómina. "
                "El estado de pago del PDF no es equivalente a autenticidad validada ante DT.")
    if "seguro social" in texto or "días" in texto or "dias" in texto:
        return ("Agrupa movimientos por RUT y periodo, revisa filas de cero días "
                "y comprueba si la cobertura de Seguro Social tiene excepciones.")
    return ("Puedo ayudarte a describir el error. Indica tipo de documento, "
            "campo que falló y página, sin aportar datos personales.")

def respuesta_ia(
    pregunta: str,
    resumen: dict,
    historial: list[dict],
    clave: str,
    modelo: str = "gemini-3.5-flash-lite",
) -> str:
    """Consulta Gemini usando solo mensajes parcialmente anonimizados."""
    from gemini_cliente import consultar_gemini

    mensajes = [
        {"role": m["role"], "content": anonimizar(m.get("content", ""))}
        for m in historial[-6:]
        if m.get("role") in ("user", "assistant")
    ]
    return consultar_gemini(
        pregunta=anonimizar(pregunta),
        resumen=resumen,
        historial=mensajes,
        clave=clave,
        modelo=modelo,
    )


def mostrar_chat(reporte: dict | None):
    st.divider()
    st.subheader("Asistente con Gemini")
    st.caption("Conversación con Gemini para explicar errores de F30-1 y Previred. No modifica la auditoría.")
    try:
        clave = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
        modelo = str(st.secrets.get("GEMINI_MODEL", "gemini-3.5-flash-lite")).strip()
    except Exception:
        clave, modelo = "", "gemini-3.5-flash-lite"

    with st.expander("Privacidad y autorización de Gemini", expanded=bool(clave)):
        st.write(
            "Al utilizar Gemini, Google recibe tu pregunta (con RUT, correos y teléfonos "
            "reemplazados), respuestas previas y estadísticas generales. NO enviamos "
            "los PDFs, la nómina completa ni los archivos Excel. "
            "El filtrado NO garantiza ocultar nombres o datos personales que escribas."
        )
        st.warning(
            "En la modalidad gratuita Google puede usar contenido para mejorar sus productos. "
            "No escribas nombres, RUT, remuneraciones individuales ni otros datos personales."
        )
        consentimiento = st.checkbox(
            "Autorizo enviar a Gemini preguntas sin datos personales",
            key="gemini_consentimiento",
        )
    if clave and consentimiento:
        if st.session_state.get("gemini_respuesta_confirmada"):
            st.success("Gemini conectado: se recibió una respuesta correctamente.")
        else:
            st.info("Clave de Gemini configurada. Escribe una pregunta para comprobar la conexión.")
    elif clave:
        st.info("Gemini configurado. Activa la autorización de privacidad para conversar.")
    else:
        st.warning(
            "Gemini todavía no está conectado. Crea una clave gratis en Google AI Studio "
            "y agrégala a Secrets de Streamlit con el nombre GEMINI_API_KEY."
        )
        st.link_button("Crear clave gratis en Google AI Studio", "https://aistudio.google.com/api-keys")
    historial = st.session_state.setdefault("historial_asistente", [])
    for mensaje in historial[-12:]:
        with st.chat_message(mensaje["role"]):
            st.write(mensaje["content"])
    pregunta = st.chat_input("Ejemplo: el OCR leyó 8 días, pero el PDF dice 6", max_chars=1200)
    if pregunta:
        previo = list(historial)
        historial.append({"role": "user", "content": pregunta})
        with st.chat_message("user"):
            st.write(pregunta)
        with st.chat_message("assistant"):
            try:
                if clave and consentimiento:
                    texto = respuesta_ia(
                        pregunta, resumen_seguro(reporte), previo, clave, modelo
                    )
                    st.session_state["gemini_respuesta_confirmada"] = True
                else:
                    texto = diagnostico_local(pregunta)
            except Exception as exc:
                from gemini_cliente import GeminiError
                texto = (
                    str(exc) if isinstance(exc, GeminiError)
                    else "No se pudo consultar Gemini. La auditoría no cambió."
                )
                st.session_state["gemini_respuesta_confirmada"] = False
            st.write(texto)
        historial.append({"role": "assistant", "content": texto})
        del historial[:-12]
    with st.expander("Guardar un error comprobado para mejorar el programa"):
        st.caption("Se guarda en esta sesión y se descarga como JSON privado. No edita el código ni las rentas.")
        with st.form("correccion_verificada"):
            pagina = st.number_input("Página del PDF", min_value=1, max_value=1000, value=1)
            campo = st.selectbox("Campo", ["dias_reales_pagados","renta_imponible_afp",
                    "renta_imponible_salud","renta_imponible_mutual","trabajador_rut",
                    "periodo_remuneracion","otro"])
            valor_ocr = st.text_input("Valor mostrado", max_chars=150)
            valor_real = st.text_input("Valor comprobado", max_chars=150)
            confirmado = st.checkbox("Revisé el documento original")
            guardar = st.form_submit_button("Registrar corrección")
        if guardar:
            if not confirmado or not valor_ocr.strip() or not valor_real.strip():
                st.warning("Revisa el documento y completa los valores antes de guardar.")
            else:
                st.session_state.setdefault("errores_confirmados", []).append(
                    {"pagina": int(pagina), "campo": campo,
                     "leido": valor_ocr.strip(), "confirmado": valor_real.strip(),
                     "verificado_por_humano": True, "aplicado": False})
                st.success("Caso registrado. No se ha modificado la auditoría.")
        if st.session_state.get("errores_confirmados"):
            st.download_button("Descargar correcciones JSON (guardar en privado)",
                json.dumps(st.session_state["errores_confirmados"], ensure_ascii=False,
                           indent=2).encode("utf-8"),
                "correcciones_privadas.json", "application/json")
