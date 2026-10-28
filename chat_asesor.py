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

def respuesta_ia(pregunta: str, resumen: dict, historial: list[dict],
                 clave: str, modelo: str = "gpt-5-mini") -> str:
    from openai import OpenAI
    mensajes = [
        {"role": m["role"], "content": anonimizar(m["content"])}
        for m in historial[-6:] if m.get("role") in ("user", "assistant")
    ]
    mensajes.append({"role": "user", "content": anonimizar(pregunta)})
    respuesta = OpenAI(api_key=clave, timeout=22.0, max_retries=1).responses.create(
        model=modelo, store=False, max_output_tokens=500,
        instructions=(
            "Asistente de auditoría laboral chilena. Sé claro. Explica qué puede estar mal "
            "y cómo cotejarlo. Distingue OCR, datos incompletos y diferencias reales. "
            "No afirmes haber editado archivos, validado la DT ni corregido montos. "
            "No inventes cifras. Sugiere revisión humana. Resumen estadístico: "
            + json.dumps(resumen, ensure_ascii=False)
        ),
        input=mensajes,
    )
    return respuesta.output_text or "No se obtuvo respuesta."

def mostrar_chat(reporte: dict | None):
    st.divider()
    st.subheader("Asistente de auditoría")
    st.caption("Explica errores de lectura y sugiere verificaciones. No cambia automáticamente la auditoría.")
    try:
        clave = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        modelo = str(st.secrets.get("OPENAI_MODEL", "gpt-5-mini"))
    except Exception:
        clave, modelo = "", "gpt-5-mini"
    with st.expander("IA, privacidad y consentimiento"):
        st.write("Sin clave funciona como ayuda local. Con API, se envía tu pregunta anonimizada "
                 "y un resumen de cantidades; jamás los PDF ni las nóminas. "
                 "El filtrado de datos no garantiza quitar los nombres que escribas manualmente.")
        consentimiento = st.checkbox("Acepto enviar preguntas anonimizadas a OpenAI", key="chat_consentimiento")
        if not clave:
            st.caption("Para activar la IA configura OPENAI_API_KEY en los secretos de Streamlit.")
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
                texto = (respuesta_ia(pregunta, resumen_seguro(reporte), previo, clave, modelo)
                         if clave and consentimiento else diagnostico_local(pregunta))
            except Exception:
                texto = "No fue posible consultar la API. La auditoría sigue sin cambios. Revisa la clave o el saldo."
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
