# V15: chat de auditoría y controles nocturnos

## Chat de IA
La aplicación muestra un chat debajo de la auditoría. Sin clave, da ayuda local. Para activar OpenAI:
1. En Streamlit Cloud, App settings > Secrets, agrega `OPENAI_API_KEY = "tu_clave"` y opcionalmente `OPENAI_MODEL = "gpt-5-mini"`.
2. Marca consentimiento de envío de preguntas a OpenAI. Nunca guardes claves en GitHub.
3. El chat analiza solo métricas agregadas y la pregunta redactada. No envía PDF ni nómina. La redacción regex NO garantiza anonimizar nombres que introduzcas en el chat: evita escribir datos personales.

**No es el ChatGPT de tu suscripción:** es la API de OpenAI, con facturación independiente.

## Correcciones
El usuario puede anotar correcciones comprobadas y descargar JSON. No modifica cotizaciones ni prueba la autenticidad DT; tampoco guarda ese JSON automáticamente entre sesiones. No lo subas al repositorio público.

## Aprendizaje nocturno
El workflow `.github/workflows/calidad_nocturna.yml` ejecuta pruebas y una evaluación de metadatos validados a diario. GitHub Actions puede retrasarse. Sin un conjunto privado de ejemplos aprobados, la evaluación señala `faltan_ejemplos_verificados`. Los candidatos no se promueven ni modifican el sistema automáticamente.

## Seguridad
Este repositorio es **público**. No subas PDF, F30-1, RUT, Excel, claves, correcciones privadas, documentos originales ni modelos derivados de ellos. Se recomienda un repositorio privado y control de acceso a Streamlit antes de procesar datos laborales reales.

## Situación del código
Esta rama añade un chat y controles sobre la aplicación que ya existe en GitHub; ese repositorio no contiene todos los módulos de la V14 desarrollada fuera de GitHub. El paquete V15 completo se entrega aparte y debe sincronizarse mediante una actualización controlada, verificando la compatibilidad de dependencias y tests.
