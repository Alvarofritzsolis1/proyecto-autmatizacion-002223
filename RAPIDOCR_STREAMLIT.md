# GALANT en Streamlit — OCR gratuito de rescate

## Qué cambia
La plataforma **sigue siendo Streamlit + Python**. No se usa Vercel, Supabase,
Google Cloud ni se envían los PDF a una API externa.

El reconocimiento de pagos sigue este orden:
1. Texto digital de PDF, sin OCR cuando es posible.
2. Tesseract existente (rotación y lectura espacial).
3. **RapidOCR + ONNX Runtime**, solo si faltan datos de recibos PREVIRED
   escaneados: fecha, período, folio o institución.
4. Mostrar contradicciones y páginas sin resolver. Nunca convertir una
   ausencia de lectura en `NO PAGADO`.

RapidOCR recibe imágenes de páginas en memoria y devuelve palabras reconocidas
y sus recuadros. Esto permite recuperar las casillas separadas de período
(`MES 09` y `AÑO 2026`) y la fecha situada junto a `Pago Electrónico`.

## Activación en Streamlit
En **Configuración opcional**:
- `OCR de rescate mejorado (RapidOCR, gratuito)`: activado por defecto.
- Desactivarlo restaura el comportamiento de Tesseract.
- Por defecto procesa **como máximo 2 páginas candidatas por PDF**.
- Con `Ampliar la búsqueda...` el límite pasa a **3 páginas** para RapidOCR.
- En `Rendimiento por archivo` se muestra el uso y tiempo total del OCR.
- Los PDF digitales no entran en RapidOCR; los modelos se cargan al necesitarlos.

En el servidor Streamlit instalar automáticamente desde `requirements.txt`:
```
rapidocr>=3.10,<4
onnxruntime>=1.19,<2
```
El proyecto conserva `opencv-python-headless` para servidores sin interfaz.
RapidOCR es software gratuito: no hay cuotas por página ni claves de API.
**El alojamiento Streamlit y los recursos de memoria/CPU pueden tener límites.**

## Seguridad de los respaldos de cotizaciones
- Las dos lecturas corren localmente en el proceso Python del servidor Streamlit.
- Evitar subir PDF reales a repositorios públicos o adjuntarlos a los registros.
- Si RapidOCR y Tesseract informan **diferente fecha, período, folio o
  institución**, se marca **EVIDENCIA_INSUFICIENTE** para revisión humana.
- La presencia de un comprobante con fecha NO verifica autenticidad oficial ni
  acredita todos los trabajadores/instituciones del período.
- El OCR adicional nunca cambia automáticamente un registro a `PAGADO`.
- No incorpora un servicio de terceros que retenga o procese el PDF.

## Qué falta validar con los PDF reales
- Ejecutar el lote de 20 PDF con y sin RapidOCR, en entorno privado.
- Medir **fecha + período correctos** contra el original, no solo cantidad
  de cadenas encontradas.
- Medir tiempo total, memoria máxima, cantidad de páginas y folios por PDF.
- Verificar los casos de fecha contradictoria y períodos en casillas.
- Elegir habilitación definitiva tras comparar falsos positivos y rendimiento.

Esta integración es una rama de prueba dependiente de
`fix/galant-pago-prioritario-ocr-20261029` (PR #10).
La rama principal `main` aún debe integrar primero el lector de pagos
prioritario antes de desplegar RapidOCR.
