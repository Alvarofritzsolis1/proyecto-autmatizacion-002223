"""Extractor conservador para comprobantes Previred multipágina.

- Lee detalle de Seguro Social (días), Fonasa/Isapre (días y base salud),
  AFP (base AFP) e ISL/Mutual (base de accidentes).
- Una persona puede figurar en múltiples líneas de movimiento y varias instituciones.
  Consolida por RUT *dentro de cada fuente* y luego cruza fuentes, nunca suma
  la misma renta de distintas instituciones.
- PDF sin texto: OCR (Tesseract) y la misma validación estricta. Si OCR no reconoce
  una fuente o las cifras, el dato queda faltante y NO se aprueba automáticamente.
- Rechaza RUT con dígito verificador inválido antes de consolidar.
"""
from __future__ import annotations

import io
import re
import unicodedata
from collections import defaultdict
from typing import Any, Callable

import pandas as pd

RUT = r"\d{1,2}\.?(?:\d{3})\.?(?:\d{3})\s*-\s*[0-9Kk]"
RUT_RE = re.compile(r"(?<!\d)(" + RUT + r")(?!\w)")
# Nombre admite tildes, guiones, apóstrofos; evita interpretar montos como nombre.
ROW_RE = re.compile(
    r"^\s*(?:\d{1,3}\s+)?(?P<rut>" + RUT + r")\s+"
    r"(?P<nombre>[A-ZÁÉÍÓÚÜÑa-záéíóúüñ'\- .]+?)\s+"
    r"(?P<numeros>\d[\d.,]*(?:\s+.+)?)\s*$"
)
DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
MONEY = re.compile(r"^\d{1,3}(?:\.\d{3})*$|^\d+$")
FIELDS = ("dias_reales_pagados", "renta_imponible_salud", "renta_imponible_afp", "renta_imponible_mutual")


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s).lower() if not unicodedata.combining(c))


def _rut_clean(s: str) -> str:
    return re.sub(r"[^0-9K]", "", s.upper())


def _rut_ok(s: str) -> bool:
    v = _rut_clean(s)
    if len(v) < 2 or len(v) > 9 or not v[:-1].isdigit():
        return False
    total = sum(int(c) * (2 + i % 6) for i, c in enumerate(reversed(v[:-1])))
    n = 11 - total % 11
    return v[-1] == ("0" if n == 11 else "K" if n == 10 else str(n))


def _peso(s: str) -> int | None:
    s = s.strip().replace(" ", "")
    return int(s.replace(".", "")) if MONEY.fullmatch(s) else None


def _periodos(texto: str) -> set[str]:
    encontrados = set()
    for m in re.finditer(r"periodo\s+de\s+remuneraci(?:ones|on)\s*:?\s*(\d{1,2})\s*[/\-]\s*(20\d{2})", _fold(texto)):
        mes, year = int(m.group(1)), int(m.group(2))
        if 1 <= mes <= 12:
            encontrados.add(f"{year}-{mes:02d}")
    for m in re.finditer(r"periodo\s+de\s+remuneraci(?:ones|on)\s*:?\s*(\d{1,2})\s+(20\d{2})", _fold(texto)):
        mes, year = int(m.group(1)), int(m.group(2))
        if 1 <= mes <= 12:
            encontrados.add(f"{year}-{mes:02d}")
    return encontrados


def _tipo_pagina(t: str) -> str:
    k = _fold(t)
    head = k[:1300]
    if "detalle de comprobante pago de cotizaciones previsionales" in head and any(x in k for x in ("instituto de seguridad laboral", "mutual de seguridad", "achs", "instituto de seguridad del trabajo")):
        return "mutual"
    if "anexos de detalle" in k and ("dias" in k and "imponible" in k) and ("cotizaciones" in k):
        return "salud"
    if "identificacion del trabajador" in k and "seguro social" in head and "dias" in k and "jornada" in k:
        return "seguro_social"
    if "detalle de pago de cotizaciones previsionales" in head and "fondo de pensiones" in k and ("afp" in k or "sis" in k):
        return "afp"
    return ""


def _mutual_name(texto: str) -> str:
    k = _fold(texto[:1500])
    if "instituto de seguridad laboral" in k or re.search(r"\bisl\b", k):
        return "ISL"
    if "asociacion chilena de seguridad" in k or re.search(r"\bachs\b", k):
        return "ACHS"
    if "instituto de seguridad del trabajo" in k or re.search(r"\bist\b", k):
        return "IST"
    if "mutual de seguridad" in k:
        return "Mutual de Seguridad"
    return ""


def _empleador(textos: list[str]) -> tuple[str, str]:
    # Preferir páginas resumen con encabezado formal de empleador; nunca leer
    # accidentalmente el RUT del representante legal o del primer trabajador.
    for texto in textos:
        lineas = texto.splitlines()
        for i, line in enumerate(lineas):
            k = _fold(line.strip())
            if "nombre o razon social" in k and "rut" in k:
                for fila in lineas[i + 1:i + 4]:
                    m = RUT_RE.search(fila)
                    if m:
                        prefijo = fila[:m.start()].strip()
                        # Comprobantes ISL incluyen correo entre nombre y RUT.
                        prefijo = re.sub(r"\b\S+@\S+\b", "", prefijo).strip()
                        if len(prefijo) >= 5 and not any(x.isdigit() for x in prefijo):
                            return prefijo.upper(), _rut_clean(m.group(1))
            if k.startswith("razon social o nombre:"):
                nombre = line.split(":", 1)[1].strip()
                for siguiente in lineas[i + 1:i + 4]:
                    mr = re.search(r"\br\.?u\.?t\.?:?\s*(" + RUT + r")", siguiente, re.I)
                    if mr and len(nombre) >= 5:
                        return nombre.upper(), _rut_clean(mr.group(1))
    return "", ""


def _parsear_fila(linea: str, tipo: str) -> dict[str, Any] | None:
    m = ROW_RE.match(linea)
    if not m:
        return None
    rut = _rut_clean(m.group("rut"))
    if not _rut_ok(rut):
        return None
    nombre = " ".join(m.group("nombre").upper().split())
    datos = m.group("numeros").split()
    if len(datos) < 4:
        return None
    renta = None
    dias = None
    if tipo == "seguro_social":
        # Base primera; antes de JC/JP: 5 cifras. Días: EXACTAMENTE después de jornada.
        jornada = next((i for i, tok in enumerate(datos) if tok.upper() in ("JC", "JP")), -1)
        if jornada < 5 or jornada + 4 >= len(datos):
            return None
        if not (DATE.fullmatch(datos[-1]) and DATE.fullmatch(datos[-2])):
            return None
        renta = _peso(datos[0])
        dias = _peso(datos[jornada + 1])
    elif tipo == "salud":
        # En Fonasa: <dias> <AFP/IPS> <renta imponible> <cotización 7%> <mov> fechas.
        if len(datos) < 10 or datos[1].upper() not in ("AFP", "IPS", "INP", "SSS", "DIPRECA", "CAPRECA"):
            return None
        if not re.fullmatch(r"\d{1,2}", datos[0]):
            return None
        dias = _peso(datos[0])
        renta = _peso(datos[2])
        # Requiere códigos de movimiento y fecha desglosada.
        if not all(x.isdigit() for x in datos[-6:]):
            return None
    elif tipo == "afp":
        # Remuneración imponible AFP es la PRIMERA cifra de la fila, no la cotización.
        if len(datos) < 7 or not (DATE.fullmatch(datos[-1]) and DATE.fullmatch(datos[-2])):
            return None
        renta = _peso(datos[0])
    elif tipo == "mutual":
        # Base ISL / Mutual es remuneración, no el monto de cotización.
        if len(datos) < 5 or not (DATE.fullmatch(datos[-1]) and DATE.fullmatch(datos[-2])):
            return None
        renta = _peso(datos[0])
    else:
        return None
    if renta is None or (dias is None and tipo in ("seguro_social", "salud")):
        return None
    if dias is not None and not 0 <= dias <= 31:
        return None
    if renta < 0:
        return None
    return {"rut": rut, "nombre": nombre, "renta": renta, "dias": dias}


def _totales_resumen(textos: list[str]) -> dict[str, int]:
    """Totales de renta de portadas de cada institución, NO cotizaciones pagadas.

    Suma AFP Provida/UNO separadamente y rechaza los montos 'total a pagar',
    que son cotizaciones y no remuneraciones imponibles.
    """
    acumulados: dict[str, list[int]] = defaultdict(list)
    for texto in textos:
        k = _fold(texto)
        cabecera = k[:420]
        if "detalle de pago de cotizaciones previsionales" in cabecera or "detalle de comprobante pago" in cabecera or "anexos de detalle" in cabecera:
            continue
        tipo = ""
        patron = ""
        if "formulario de cotizaciones previsionales" in cabecera and "seguro social" in cabecera:
            tipo = "seguro_social"
            patron = r"total remuneracion imponible declarada en \$\s*\$?\s*([\d.]+)"
        elif "planilla de declaracion y pago simultaneo" in cabecera:
            tipo = "salud"
            patron = r"total remuneracion imponible declarada en \$\s*\$?\s*([\d.]+)"
        elif "comprobante de pago de cotizaciones previsionales" in cabecera and "instituto de seguridad laboral" in k:
            tipo = "mutual"
            patron = r"total remuneraciones\s+([\d.]+)"
        elif "comprobante de pago de cotizaciones previsionales" in cabecera and "afp" in k:
            tipo = "afp"
            patron = r"renta imponible\s+([\d.]+)"
        if not tipo:
            continue
        match = re.search(patron, k)
        if match:
            monto = _peso(match.group(1))
            if monto is not None:
                acumulados[tipo].append(monto)
    return {tipo: sum(importes) for tipo, importes in acumulados.items()}


def _movimiento_sin_renta(linea: str, tipo: str) -> tuple[str, bool]:
    """Permite reconocer un movimiento a $0 aunque su disposición varíe.

    En Previred un mismo trabajador puede tener varias filas de permiso,
    cese o inicio. Una fila a $0 no es otro trabajador ni una diferencia
    de renta; nunca se convierte en base positiva por inferencia.
    """
    m = ROW_RE.match(linea)
    if not m:
        return "", False
    rut = _rut_clean(m.group("rut"))
    if not _rut_ok(rut):
        return rut, False
    datos = m.group("numeros").split()
    if not datos:
        return rut, False
    posicion = 2 if tipo == "salud" else 0
    if tipo == "salud" and (
        len(datos) < 3 or datos[1].upper() not in
        ("AFP", "IPS", "INP", "SSS", "DIPRECA", "CAPRECA")
    ):
        return rut, False
    return rut, len(datos) > posicion and _peso(datos[posicion]) == 0


def _letra_montaje(tipo: str) -> str:
    return {"salud": "renta_imponible_salud", "afp": "renta_imponible_afp", "mutual": "renta_imponible_mutual", "seguro_social": "renta_seguro_social"}[tipo]


def extraer_previred(
    contenido: bytes,
    nombre: str,
    ocr_pagina: Callable[[bytes, int, str], bytes] | None = None,
) -> pd.DataFrame | None:
    """Retorna tabla estandarizada o None si no identifica formato Previred.

    Si una fuente esperada no queda completa, conserva registro con campos vacíos
    y observación. El motor de auditoría lo califica como REVISAR_DATOS.
    """
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            textos = [(pagina.extract_text(x_tolerance=2, y_tolerance=3) or "") for pagina in pdf.pages]
    except Exception as exc:
        raise ValueError(f"{nombre}: no fue posible leer el PDF: {exc}") from exc

    pagina_ocr: set[int] = set()
    if ocr_pagina:
        for i, txt in enumerate(textos):
            if len(txt.strip()) < 70:
                try:
                    pdf_ocr = ocr_pagina(contenido, i, nombre)
                    with pdfplumber.open(io.BytesIO(pdf_ocr)) as convertido:
                        reemplazo = convertido.pages[0].extract_text(x_tolerance=2, y_tolerance=3) or ""
                    if len(reemplazo) > len(txt):
                        textos[i] = reemplazo
                        pagina_ocr.add(i)
                except Exception:
                    # El OCR podría fallar una página de portada. Las fuentes ausentes
                    # se informan como revisión; nunca se inventan cifras.
                    pagina_ocr.add(i)

    tipos = [(i, _tipo_pagina(txt)) for i, txt in enumerate(textos)]
    tipos = [(i, tipo) for i, tipo in tipos if tipo]
    origen_previred = any("previred" in _fold(t) for t in textos) or "previred" in _fold(nombre)
    if not tipos and not origen_previred:
        return None
    if not tipos:
        raise ValueError(
            f"{nombre}: se identificó un documento de Previred pero no se reconocieron "
            "páginas de detalle de trabajadores. Revisa la resolución y las tablas del PDF."
        )

    periodos = set().union(*(_periodos(txt) for txt in textos))
    if len(periodos) > 1:
        raise ValueError(f"{nombre}: el PDF tiene períodos de remuneración contradictorios: {sorted(periodos)}")
    periodo = next(iter(periodos), "")
    contratista, rut_empleador = _empleador(textos)
    mutual = next((_mutual_name(textos[i]) for i, t in tipos if t == "mutual" and _mutual_name(textos[i])), "")
    if not mutual:
        mutual = next((_mutual_name(txt) for txt in textos if _mutual_name(txt)), "")

    # Agrupar movimientos en cada institución, sin duplicar rentas AFP, Salud o Mutual.
    por_fuente: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    paginas_por_fuente: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    fuentes_encontradas = {tipo for _, tipo in tipos}
    filas_rechazadas: list[tuple[int, str, str, bool]] = []
    for index, tipo in tipos:
        texto = textos[index]
        for linea in texto.splitlines():
            if not RUT_RE.search(linea):
                continue
            dato = _parsear_fila(linea, tipo)
            if dato is None:
                # El parser puede rechazar un MOVIMIENTO a $0 cuyo RUT sea
                # válido. No llamarlo RUT inválido ni duplicado: revisar si
                # ese RUT sí tiene otro movimiento interpretable en la fuente.
                m = re.match(r"^\s*(?:\d{1,3}\s+)?(" + RUT + r")", linea)
                if m:
                    rut = _rut_clean(m.group(1))
                    _, cero = _movimiento_sin_renta(linea, tipo)
                    filas_rechazadas.append((index + 1, tipo, rut, cero))
                continue
            dato["pagina"] = index + 1
            por_fuente[tipo][dato["rut"]].append(dato)
            paginas_por_fuente[tipo][dato["rut"]].add(index + 1)
    # No emitir advertencias falsas por movimientos de $0 de trabajadores
    # ya identificados correctamente en la misma institución.
    filas_no_verificadas = [
        (pagina, tipo, rut)
        for pagina, tipo, rut, cero in filas_rechazadas
        if not (cero and rut in por_fuente[tipo])
    ]

    # Cuadratura contra comprobantes resumen. Detecta omisiones silenciosas de
    # trabajadores o rentas, incluso cuando el OCR devolvió otras filas válidas.
    totales_resumen = _totales_resumen(textos)
    alertas_totales: list[str] = []
    for tipo, monto_resumen in totales_resumen.items():
        monto_detalle = sum(x["renta"] for grupos in por_fuente[tipo].values() for x in grupos)
        if monto_detalle != monto_resumen:
            alertas_totales.append(
                f"{tipo.upper()}: resumen ${monto_resumen:,}; leído ${monto_detalle:,}"
            )

    ruts = set().union(*(set(fuente.keys()) for fuente in por_fuente.values()))
    if not ruts:
        raise ValueError(
            f"{nombre}: encontré secciones Previred, pero no pude extraer filas de trabajadores confiables. "
            "Comprueba la orientación/calidad del PDF y que contenga detalle por trabajador."
        )

    resultados = []
    for rut in sorted(ruts):
        fuentes_trabajador = {tipo: por_fuente[tipo].get(rut, []) for tipo in ("seguro_social", "salud", "afp", "mutual")}
        obs: list[str] = []
        nombres = {x["nombre"] for grupo in fuentes_trabajador.values() for x in grupo}
        if len(nombres) > 1:
            # Distintos formatos de nombres pueden diferir en orden o espaciado: comprobar,
            # pero no usarlo para agregar personas distintas, esa clave es el RUT validado.
            if {" ".join(sorted(n.split())) for n in nombres}.__len__() > 1:
                obs.append("Los nombres difieren entre instituciones; verificar")
        nombre_trab = next((grupo[0]["nombre"] for grupo in (fuentes_trabajador["salud"], fuentes_trabajador["seguro_social"], fuentes_trabajador["afp"], fuentes_trabajador["mutual"]) if grupo), "")
        valores: dict[str, int | None] = {}
        paginas: set[int] = set()
        for tipo, grupo in fuentes_trabajador.items():
            if not grupo:
                if tipo != "seguro_social":
                    obs.append(f"Falta detalle individual en {tipo.upper()}")
                continue
            paginas.update(x["pagina"] for x in grupo)
            # Dos movimientos distintos pueden tener 0 y montos; detectamos repetición
            # exacta solo si los importes no son cero y podrían inflar la renta.
            for monto in {x["renta"] for x in grupo if x["renta"] > 0}:
                if sum(x["renta"] == monto for x in grupo) > 1:
                    obs.append(f"{tipo}: varias líneas con la misma renta positiva, revisar posible duplicado")
            clave = _letra_montaje(tipo)
            valores[clave] = sum(x["renta"] for x in grupo)
            if tipo in ("salud", "seguro_social"):
                valores["dias_" + tipo] = sum(x["dias"] for x in grupo if x["dias"] is not None)
        # Fuente primaria de días: ANEXO FONASA/ISAPRE. SS como control cruzado
        # o respaldo excepcional si no está la fuente de salud (con advertencia).
        dias_salud = valores.get("dias_salud")
        dias_ss = valores.get("dias_seguro_social")
        if dias_salud is not None and dias_ss is not None and dias_salud != dias_ss:
            obs.append(f"Días Salud ({dias_salud}) distintos de Seguro Social ({dias_ss})")
        dias = dias_salud if dias_salud is not None else dias_ss
        if dias_salud is None and dias_ss is not None:
            obs.append("Días tomados del Seguro Social, sin confirmación en anexo Salud")
        renta_salud = valores.get("renta_imponible_salud")
        renta_ss = valores.get("renta_seguro_social")
        if renta_salud is not None and renta_ss is not None and renta_salud != renta_ss:
            obs.append(f"Renta Salud ({renta_salud}) no coincide con Renta Seguro Social ({renta_ss})")
        if not periodo:
            obs.append("Período de remuneraciones no encontrado en el contenido del PDF")
        if not contratista or not rut_empleador:
            obs.append("Nombre/RUT del empleador no encontrado en cabecera")
        if not mutual:
            obs.append("Mutual no identificada en el documento")
        if alertas_totales:
            # Es una diferencia de LECTURA automática, no una prueba de
            # cotizaciones erradas ni de RUT inválido del trabajador.
            obs.append("Lectura parcial del PDF: no fue posible conciliar "
                       + "; ".join(alertas_totales))
        if filas_no_verificadas:
            paginas = sorted({p for p, _, _ in filas_no_verificadas})
            obs.append("Filas sin interpretar en páginas "
                       + ", ".join(str(p) for p in paginas[:6])
                       + "; revisar lectura automática")
        if pagina_ocr:
            obs.append("Se aplicó OCR; verificar cifras de las páginas escaneadas antes de aprobar")
        resultados.append({
            "periodo_remuneracion": periodo,
            "contratista_nombre": contratista,
            "contratista_rut": rut_empleador,
            "trabajador_nombre": nombre_trab,
            "trabajador_rut": rut,
            "dias_reales_pagados": dias,
            "renta_imponible_salud": renta_salud,
            "renta_imponible_afp": valores.get("renta_imponible_afp"),
            "renta_imponible_mutual": valores.get("renta_imponible_mutual"),
            "mutual_adherida": mutual,
            "__hoja_origen": ", ".join("p." + str(p) for p in sorted(paginas)),
            "__conflicto_pdf": "; ".join(obs),
        })

    # Verificar totales de fuente si se han leído las filas; no confundir resumen
    # del monto A PAGAR con la RENTA IMPONIBLE (la cotización es un concepto diferente).
    return pd.DataFrame(resultados)
