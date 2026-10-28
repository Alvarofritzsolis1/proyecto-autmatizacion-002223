# Chat gratuito con Google Gemini — Auditoría Laboral

El chat de la portada está conectado a **Gemini** mediante la API REST oficial.
No se necesita una clave de OpenAI ni una suscripción a ChatGPT Plus.
El plan gratis tiene cuotas y depende de la disponibilidad de tu cuenta.

## Paso a paso (sin programar)

1. Visita https://aistudio.google.com/api-keys
2. Inicia sesión con Google y selecciona **Create API key**.
3. Copia la clave. **No la pegues en GitHub, ni la compartas por chat o correo.**
4. Entra a https://share.streamlit.io/ → tu aplicación → **Settings → Secrets**.
5. Pega estas dos líneas, cambiando solo el contenido entre comillas de la primera:

    GEMINI_API_KEY = "TU_CLAVE_SECRETA_DE_GOOGLE"
    GEMINI_MODEL = "gemini-3.5-flash-lite"

6. Haz clic en **Save** y, si hace falta, reinicia tu app.
7. Arriba de la página verás **Asistente con Gemini**.
8. Abre **Privacidad y autorización de Gemini** y marca la casilla.
9. Escribe una pregunta de prueba sin datos privados: "¿Cómo revisar un F30-1 con menos RUT reconocidos que trabajadores declarados?"

Si responde, se mostrará "Gemini conectado". Si ves "llegaste al límite gratuito", revisa tus cuotas en AI Studio e intenta más tarde. Si informa que el modelo no está disponible, consulta qué modelos gratis tiene habilitados tu proyecto y modifica solo GEMINI_MODEL.

## ¿Qué puede hacer?

- Explicar diferencias de AFP, Fonasa, ACHS, Seguro Social y F30-1.
- Proponer pruebas para investigar fallos de OCR.
- Aconsejar revisiones humanas y guardar correcciones en sesión descargables como JSON.
- Mostrar mensajes claros cuando falta la clave o se alcanza el límite.

## ¿Qué NO hace?

- No cambia ni aprueba cotizaciones, días, rentas o resultados de auditoría.
- No edita automáticamente el código Python.
- No verifica automáticamente certificados contra la Dirección del Trabajo.
- No envía PDFs, Excel ni nóminas a Gemini; solo preguntas y estadísticas generales.

## Datos personales y modalidad gratuita

**Google puede utilizar contenido enviado en el nivel gratuito para mejorar sus productos.**
No introduzcas en el chat nombres, RUT, datos bancarios, montos individuales de trabajadores,
números de certificado con claves, ni otros datos sensibles. La plataforma sustituye
automáticamente patrones reconocibles de RUT, correos y teléfonos, pero **esto no garantiza
anonimización completa**, especialmente para nombres y direcciones escritos manualmente.

El repositorio GitHub es público. Nunca publiques allí los documentos ni la clave.
Conviene restringir el acceso de tu app Streamlit antes de procesar documentos laborales.

Referencia técnica: https://ai.google.dev/api/generate-content
Precios/cuotas: https://ai.google.dev/gemini-api/docs/pricing

## Nota sobre el estado del proyecto

Esta actualización conecta Gemini con la versión del código **actualmente publicada en GitHub**.
No sustituye ni sincroniza automáticamente los módulos OCR V14 preparados en otros paquetes.
El chat se encuentra en chat_asesor.py y gemini_cliente.py; la interfaz lo invoca en app.py.
