# GALANT: revisión técnica punto por punto

## Problemas observados en el repositorio anterior

| Área | Falencia previa | Cambio implementado | Qué sigue necesitando revisión humana |
|---|---|---|---|
| Identidad | Título genérico de auditoría | Título GALANT en pestaña e interfaz | Nombre legal comercial si procede |
| Chat | Gemini ocupaba espacio y requirió API | Fuera del código, pruebas, documentación y UI | No aplica |
| Pantalla | Tolerancia, mutual y topes visibles al cargar | Dos pasos principales, tres pestañas, configuración avanzada oculta | Uso de políticas documentales internas |
| Duplicados | Dos copias idénticas del mismo PDF procesadas dos veces | Detección SHA-256 sobre bytes y aviso de omisión | Pagos diferentes, aunque nombres coincidan, siguen siendo archivos distintos |
| Tipo de documento | Lectura de PDF heterogéneos | Clasificación F30-1 vs Previred antes de auditar | PDF erróneamente clasificado debe revisarse |
| Certificado | F30-1 y Previred no comparados entre sí | Cruce por empleador, período y RUT | Certificado parcial y ámbito de obra |
| Ámbito | Riesgo de tratar trabajadores extra de Previred como incumplimiento | No exige igualdad de nómina general y nómina por obra | Confirmar obra/faena concreta |
| OCR | Advertencia genérica de escaneo en todos los trabajadores | Cotejo estricto de bases/días/RUT, aviso solo si no alcanza evidencia | No equivale a garantía universal de OCR |
| Seguro Social | Descuadre agregado marcado a todos | Diferencias por trabajador, con posible régimen excepcional | Determinar obligación concreta |
| AFP | Descuadre agregado marcado a todos | Comprobación de bases por trabajador, sin presumir impago | Exenciones y regímenes distintos |
| Documentación incompleta | Riesgo de concluir impago porque falta resumen | Separación explícita entre no lectura, falta de página y declaración de pago | Verificador DT oficial |
| Pérdida de resultado | F30-1 podía quedar oculto si Previred fallaba | Se conserva el resultado F30-1 e informa el fallo de otros archivos | Repetir cotizaciones ilegibles |
| Rendimiento | scikit-learn incluido en servidor de producción sin necesidad directa | Dependencia trasladada a desarrollo y pruebas | ML nocturno requiere datos aprobados |
| Calidad | Escenarios de cruce sin cobertura | Pruebas de igualdad, diferencia, período, empleador, ausencias y duplicados | Pruebas visuales Streamlit y archivos reales, privados |

## Alcance de los estados

- **NOMINAS_COINCIDEN**: cantidad y RUT de la nómina F30-1 coinciden con los registros del mismo empleador y período en Previred; no acredita el pago.
- **REVISAR_NOMINA**: falta RUT en el archivo de cotizaciones o hay duplicación; no presume impago.
- **SIN_COMPROBANTE_COMPARABLE**: el período o empleador no está representado en Previred.
- **REVISAR_COTIZACIONES**: el RUT coincide, pero sus bases/días requieren revisión.
- **NOMINA_F301_INCOMPLETA**: la cantidad extraída del PDF no corresponde a la cantidad declarada.
- **NO_COMPARABLE**: el certificado no aporta un RUT de empleador o un período verificable.

## Controles que GALANT no puede afirmar sin pruebas externas

- Autenticidad oficial ante la Dirección del Trabajo.
- Pago efectivo a las distintas instituciones.
- Ausencia de deuda fiscalizable, multas o exenciones.
- Que las cotizaciones de toda la empresa correspondan exactamente a una sola obra.

## Diseño inspirado en productos comerciales, no copiado

Se adoptan ideas generales que publican ABBYY (revisión humana de excepciones),
Rossum (validaciones por documento) y Nanonets (trazabilidad de reglas).
No hay integración comercial ni dependencia de sus servicios.
Fuentes:
- https://www.abbyy.com/ai-document-processing/human-in-the-loop-verification/
- https://knowledge-base.rossum.ai/docs/configuring-automation-in-rossum
- https://docs.nanonets.com/docs/nanonets-overview

## Mejoras pendientes para producción rigurosa

1. Control de acceso y autenticación de usuarios en Streamlit; no exponer datos laborales.
2. Auditorías longitudinales con respaldo privado y política de retención.
3. Batería de regresión privada con documentos reales autorizados, nunca pública.
4. Verificación oficial DT mediante consulta manual o integración autorizada futura.
5. Revisión técnica de regímenes legales especiales y topes para cada período.
6. Test de interfaz y pruebas de carga en Streamlit Community Cloud.

**Los resultados de GitHub Actions y la revisión local son controles de software;
no son una certificación oficial ni garantía universal de lectura OCR.**
