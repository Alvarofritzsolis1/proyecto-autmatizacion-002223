"""Benchmark PRIVADO de PDFs reales de cotizaciones (NO guardar corpus en GitHub).

Uso:
  python -m scripts.validar_corpus_privado --root /ruta/segura --manifest /ruta/segura/verdad.json --salida /ruta/segura/resultado.json --min-docs 30

Manifest fuera del repositorio:
{
  "documentos": [{
    "archivo": "ejemplo.pdf",
    "sha256": "hash_sha256_total_del_pdf",
    "trabajadores": [{
      "rut": "rut_real", "dias": 27, "periodo": "2026-09",
      "institucion_salud": "Fonasa"
    }]
  }]
}
Sin truth manual, la prueba NO se puede aprobar.
No imprime nombres, RUT, folios, montos ni rutas privadas.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from pago_documental import analizar_pago_pdf
from fonasa_runtime import extraer_fonasa_con_contrato
from fonasa_nomina_simple import normalizar_rut
from nomina_salud import construir_nomina_salud
from reporte_nomina_excel import generar_excel_nomina


def evaluar(root: Path, manifest: Path, min_docs: int = 30) -> dict:
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    documentos = corpus.get("documentos", [])
    if not documentos:
        raise ValueError("No hay documentos reales con referencia manual.")
    antes = time.monotonic()
    estado = {
        "archivos": 0,
        "documentos_requeridos": min_docs,
        "campos_verificados": 0,
        "dias_correctos": 0,
        "dias_falsos_aceptados": 0,
        "dias_sin_lectura": 0,
        "trabajadores_omitidos": 0,
        "trabajadores_extra": 0,
        "periodos_incorrectos": 0,
        "institucion_incorrecta": 0,
        "documentos_sin_extraccion": 0,
        "archivos_hash_incorrecto": 0,
        "errores_de_procesamiento": 0,
    }
    os.environ["GALANT_OCR_STRICT_MODE"] = "1"
    for fuente in documentos:
        # Nunca abrir rutas absolutas ni escapadas fuera del corpus seguro.
        nombre = Path(str(fuente.get("archivo", "")))
        if nombre.is_absolute() or ".." in nombre.parts:
            raise ValueError("Nombre de archivo inseguro en manifest.")
        archivo = (root / nombre).resolve()
        if not archivo.is_relative_to(root.resolve()):
            raise ValueError("Ruta fuera del corpus.")
        contenido = archivo.read_bytes()
        sha = hashlib.sha256(contenido).hexdigest()
        if not fuente.get("sha256") or fuente["sha256"] != sha:
            estado["archivos_hash_incorrecto"] += 1
            continue
        estado["archivos"] += 1
        try:
            evidencia = analizar_pago_pdf(
                contenido, archivo.name,
                max_paginas_ocr=6, usar_rapidocr=True
            )
            evidencia["archivo"] = archivo.name
            pagos = [
                c for c in evidencia.get("comprobantes", [])
                if str(c.get("institucion", "")).lower() == "fonasa"
                or str(c.get("institucion", "")).lower().startswith("isapre")
            ]
            paginas = [int(c["pagina"]) for c in pagos if c.get("pagina")]
            pistas = {int(c["pagina"]): c["institucion"] for c in pagos if c.get("pagina")}
            anexos = extraer_fonasa_con_contrato(
                contenido,
                paginas_candidatas=paginas or None,
                instituciones_candidatas=pistas,
                usar_ocr_alternativo=True,
            )
            trabajadores = [
                {
                    **fila,
                    "archivo": archivo.name,
                    "pagina_fonasa": anexo.get("pagina"),
                    "institucion_salud": anexo.get("institucion_salud")
                }
                for anexo in anexos
                for fila in anexo.get("trabajadores", [])
            ]
            filas, alertas = construir_nomina_salud([evidencia], trabajadores)
            salida = generar_excel_nomina(filas, alertas)
            if not salida.startswith(b"PK"):
                raise ValueError("No se generó un XLSX real.")
            if not filas:
                estado["documentos_sin_extraccion"] += 1
            predichos = {
                (normalizar_rut(r["rut"]),r.get("institucion_salud","")): r
                for r in filas
            }
            esperados = {
                (normalizar_rut(r["rut"]),r.get("institucion_salud","")):r
                for r in fuente["trabajadores"]
            }
            estado["trabajadores_extra"] += len(predichos.keys()-esperados.keys())
            for clave, real in esperados.items():
                estado["campos_verificados"] += 1
                pred = predichos.get(clave)
                if pred is None:
                    estado["trabajadores_omitidos"] += 1
                    continue
                actual = pred.get("dias")
                esperado = real.get("dias")
                if actual is None:
                    estado["dias_sin_lectura"] += 1
                elif actual != esperado:
                    estado["dias_falsos_aceptados"] += 1
                else:
                    estado["dias_correctos"] += 1
                if real.get("periodo") and pred.get("periodo") != real["periodo"]:
                    estado["periodos_incorrectos"] += 1
                if pred.get("institucion_salud") != real.get("institucion_salud"):
                    estado["institucion_incorrecta"] += 1
        except Exception:
            estado["errores_de_procesamiento"] += 1
    estado["tiempo_segundos"] = round(time.monotonic()-antes,2)
    criticos = [
        "dias_falsos_aceptados", "trabajadores_omitidos",
        "trabajadores_extra", "dias_sin_lectura", "periodos_incorrectos",
        "institucion_incorrecta", "documentos_sin_extraccion",
        "archivos_hash_incorrecto", "errores_de_procesamiento"
    ]
    estado["aprobado_corpus_observado"] = bool(
        estado["archivos"] == len(documentos)
        and estado["archivos"] >= min_docs
        and estado["campos_verificados"] > 0
        and all(estado[c] == 0 for c in criticos)
    )
    return estado


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--manifest",required=True,type=Path)
    p.add_argument("--salida",required=True,type=Path)
    p.add_argument("--min-docs",type=int,default=30)
    a=p.parse_args()
    r=evaluar(a.root,a.manifest,min_docs=a.min_docs)
    a.salida.write_text(json.dumps(r,indent=2,ensure_ascii=False))
    print(json.dumps(r,ensure_ascii=False))
    raise SystemExit(0 if r["aprobado_corpus_observado"] else 2)


if __name__=="__main__":
    main()
