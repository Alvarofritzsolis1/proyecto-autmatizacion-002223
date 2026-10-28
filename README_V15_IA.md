# IA actual: chat con Google Gemini (modalidad gratuita)

El asistente interno ahora usa Gemini, no OpenAI. Para instalar la clave sigue [README_GEMINI.md](README_GEMINI.md).

- **Secret**: `GEMINI_API_KEY = "TU_CLAVE"`
- **Modelo inicial**: `GEMINI_MODEL = "gemini-3.5-flash-lite"`
- La clave se guarda solo en **Streamlit App settings → Secrets**, nunca en GitHub.
- El chat usa preguntas parcialmente anonimizadas y métricas generales; no envía PDFs ni nóminas.
- El plan gratuito tiene cuotas y Google puede usar entradas para mejorar productos. No introduzcas datos personales.
- No cambia código, cifras ni estados automáticamente.


## Aprendizaje y pruebas nocturnas

El workflow de GitHub Actions ejecuta pruebas y prepara evaluaciones sin alterar las reglas de auditoría. Los casos de entrenamiento requieren datos aprobados almacenados en privado. Consulta la guía de Gemini para conectar el chat.
