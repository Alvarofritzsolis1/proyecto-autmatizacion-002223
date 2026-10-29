"""Regresiones sintéticas para no confundir OCR de nómina con estado de pago."""
import pandas as pd

from bandeja_revision import _detalle_revision, _separar_cobertura_ocr, generar_bandeja


def test_missing_contractor_id_is_not_invalid_worker():
    mensaje=(
        "Faltan valores en la fila: contratista_rut, renta_imponible_afp; "
        "Falta el RUT del contratista; "
        "No se pudo identificar la mutual adherida"
    )
    titulo,accion=_detalle_revision(mensaje)
    assert titulo == "RUT del contratista no identificado"
    assert "trabajador" in accion.lower()


def test_explicit_invalid_worker_id_is_separate_issue():
    titulo,_=_detalle_revision(
        "RUT del trabajador inválido: dígito verificador incorrecto"
    )
    assert "dígito verificador" in titulo.lower()


def test_repeated_scan_warning_moves_to_document_level():
    motivo=("Conflicto entre tablas del PDF: Revisión cobertura OCR: "
            "p.1: columnas de seguro_social ilegibles")
    clean,coberturas=_separar_cobertura_ocr(motivo)
    assert clean == ""
    assert coberturas == ["p.1: columnas de seguro_social ilegibles"]

    filas=pd.DataFrame([
        dict(archivo_origen="ensayo.pdf", trabajador_rut="12.345.678-5",
             motivo_revision=motivo, estado_auditoria="REVISAR_DATOS"),
        dict(archivo_origen="ensayo.pdf", trabajador_rut="11.111.111-1",
             motivo_revision=motivo, estado_auditoria="REVISAR_DATOS"),
    ])
    b=generar_bandeja(detalle=filas)
    assert len(b)==1
    assert b.iloc[0]["categoria"] == "Cobertura OCR (avanzado)"
    assert b.iloc[0]["pagina"] == "p.1"


def test_keep_individual_issue_and_group_scan_warning():
    motivo=(
        "Faltan valores en la fila: renta_imponible_afp; "
        "Conflicto entre tablas del PDF: Revisión cobertura OCR: "
        "p.7: columnas ilegibles"
    )
    base,avisos=_separar_cobertura_ocr(motivo)
    assert "renta_imponible_afp" in base
    assert len(avisos)==1
    b=generar_bandeja(detalle=pd.DataFrame([
        dict(archivo_origen="ficticio.pdf", trabajador_rut="12.345.678-5",
             motivo_revision=motivo, estado_auditoria="REVISAR_DATOS"),
    ]))
    assert len(b)==2
    assert set(b["categoria"])=={"Cotizaciones","Cobertura OCR (avanzado)"}


def test_payment_evidence_survives_advanced_payroll_failure():
    logs=pd.DataFrame([
        {"archivo":"sintetico.pdf", "resultado":"ERROR",
         "detalle":"No se encontraron filas de trabajadores confiables"}
    ])
    pagos=[{
        "archivo":"sintetico.pdf",
        "comprobantes":[{
            "periodo":"2026-09","fecha_pago":"13/10/2026",
            "estado":"PAGO_RESPALDADO_EN_DOCUMENTO",
        }]
    }]
    bandeja=generar_bandeja(log=logs,pagos_documentales=pagos)
    assert len(bandeja)==1
    assert bandeja.iloc[0]["categoria"]=="Auditoría avanzada"
    assert "nómina" in bandeja.iloc[0]["hallazgo"]
    assert "puede estar incompleto" in bandeja.iloc[0]["hallazgo"]


def test_no_evidence_still_raises_document_warning():
    logs=pd.DataFrame([
        {"archivo":"sintetico.pdf","resultado":"ERROR","detalle":"PDF ilegible"}
    ])
    bandeja=generar_bandeja(
        log=logs,
        pagos_documentales=[{"archivo":"sintetico.pdf","comprobantes":[]}],
    )
    assert len(bandeja)==1
    assert bandeja.iloc[0]["categoria"]=="Archivo"
    assert bandeja.iloc[0]["prioridad"]=="ALTA"
