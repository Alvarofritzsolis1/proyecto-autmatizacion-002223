"""Lee las planillas digitales de Fonasa y contrasta días con Seguro Social.

Esta ruta usa la capa de texto y la geometría de BLOQUES del PDF. No se
necesita Tesseract y no se infiere pago desde el OCR del encabezado.
Los PDF escaneados sin texto siguen a la ruta anterior de OCR.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import fitz


_RUT = re.compile(r"^\d{1,2}\.\d{3}\.\d{3}-[\dkK]$")


def normalizar(texto):
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto or "").lower())
        if unicodedata.category(c) != "Mn"
    )


def normalizar_rut(rut):
    s = re.sub(r"[^\dkK]", "", str(rut))
    if not 8 <= len(s) <= 9:
        return ""
    digito = s[-1].upper()
    if digito not in "0123456789K":
        return ""
    return f"{int(s[:-1]):,}".replace(",", ".") + "-" + digito


def _bloques_reconstruidos(pagina):
    """Reconstruye una fila vertical dividida en bloques por PyMuPDF.

    PyMuPDF >= 1.28 puede separar cada línea de texto con giro 90 grados
    en bloques sucesivos. Unir exclusivamente fragmentos contiguos
    con el MISMO borde inferior, a partir de N° y RUT en el bloque inicial.
    No concatenar bloques de otras filas ni columnas sin esa geometría.
    """
    bloques = [
        b for b in pagina.get_text("blocks", sort=False)
        if len(b) >= 5 and str(b[4]).strip()
    ]
    for bloque in bloques:
        yield bloque
        campos = [s.strip() for s in bloque[4].splitlines() if s.strip()]
        if (
            len(campos) < 2 or not campos[0].isdigit()
            or not _RUT.fullmatch(campos[1])
            or any(x in ("AFP", "IPS", "JC", "JP") for x in campos)
        ):
            continue
        piezas = [bloque]
        usados = {id(bloque)}
        borde_x, borde_y = float(bloque[2]), float(bloque[3])
        for _ in range(12):
            cercanos = [
                x for x in bloques
                if id(x) not in usados
                and abs(float(x[3]) - borde_y) < 2.5
                and borde_x - 0.8 <= float(x[0]) <= borde_x + 3.0
                and float(x[0]) > float(bloque[0])
            ]
            if not cercanos:
                break
            siguiente = min(cercanos, key=lambda x: float(x[0]))
            piezas.append(siguiente)
            usados.add(id(siguiente))
            borde_x = float(siguiente[2])
            texto_unido = "\\n".join(p[4].strip() for p in piezas)
            lineas = [s.strip() for s in texto_unido.splitlines() if s.strip()]
            if any(x in ("AFP", "IPS") for x in lineas):
                break
            if any(
                x in ("JC", "JP") and i + 1 < len(lineas)
                for i, x in enumerate(lineas)
            ):
                break
        if len(piezas) > 1:
            yield (
                min(float(x[0]) for x in piezas),
                min(float(x[1]) for x in piezas),
                max(float(x[2]) for x in piezas),
                max(float(x[3]) for x in piezas),
                "\\n".join(x[4].strip() for x in piezas),
            )


def _filas_texto(pagina, tipo):
    """Una fila debe proceder del MISMO bloque de PDF, no de otras columnas."""
    salida = []
    for bloque in _bloques_reconstruidos(pagina):
        if len(bloque) < 5:
            continue
        campos = [x.strip() for x in bloque[4].splitlines() if x.strip()]
        if (
            len(campos) < 6 or not campos[0].isdigit()
            or not _RUT.fullmatch(campos[1])
        ):
            continue
        rut = normalizar_rut(campos[1])
        if tipo == "Fonasa":
            # N°, RUT, apellidos, nombres, DIAS, AFP|IPS, remuneración...
            try:
                posicion = next(
                    i for i, v in enumerate(campos[2:], 2)
                    if v in ("AFP", "IPS")
                )
            except StopIteration:
                continue
            if posicion < 5:
                continue
            valor = campos[posicion - 1]
            nombre = " ".join(campos[2:posicion - 1])
            metodo = "texto_pdf_fonasa"
        elif tipo == "Seguro Social":
            # N°, RUT, nombre, remuneraciones, JC|JP, DIAS, movimiento...
            try:
                posicion = next(
                    i for i, v in enumerate(campos[2:], 2)
                    if v in ("JC", "JP")
                )
            except StopIteration:
                continue
            if posicion < 5 or posicion + 1 >= len(campos):
                continue
            valor = campos[posicion + 1]
            nombre = campos[2]
            metodo = "texto_pdf_seguro_social"
        else:
            continue
        if not re.fullmatch(r"[1-9]|[12]\d|3[01]", valor):
            continue
        if not nombre or not re.search(r"[A-Za-zÁÉÍÓÚÑ]", nombre):
            continue
        dias = int(valor)
        salida.append({
            "trabajador_rut": rut,
            "trabajador_nombre": " ".join(nombre.split()).upper(),
            "dias_trabajados_fonasa": dias,
            "filas_movimientos": 1,
            "dias_requieren_revision": False,
            "traza_dias": [{
                "fila": int(campos[0]),
                "valor": dias,
                "metodo": metodo,
                "texto_fuente": valor,
                "pagina": pagina.number + 1,
                "celda_pdf": [
                    round(float(coord), 2) for coord in bloque[:4]
                ],
            }],
            "fuente": (
                "Fonasa - texto PDF" if tipo == "Fonasa"
                else "Seguro Social - texto PDF"
            ),
            "metodo_dias": metodo,
        })
    return salida


def _periodo(pagina):
    texto = normalizar(pagina.get_text())
    m = re.search(
        r"periodo de remuneraci[oó]n\s*(?:es)?\s*:?"
        r"[\s\S]{0,25}?\b(0?[1-9]|1[012])\s+(20\d\d)",
        texto
    )
    return f"{m.group(2)}-{int(m.group(1)):02d}" if m else ""


def extraer_nominas_pdf_texto(
    contenido, paginas_candidatas=None, instituciones_candidatas=None
):
    """Prioriza texto PDF; Fonasa exige respaldo de encabezado y folio.

    Si no hay página Fonasa digital, Seguro Social puede informar días
    como referencia SIN certificar salud, nunca clasificándolos como Fonasa.
    """
    pistas = dict(instituciones_candidatas or {})
    salida = []
    with fitz.open(stream=contenido, filetype="pdf") as pdf:
        seguros = defaultdict(dict)
        for pagina in pdf:
            texto = normalizar(pagina.get_text("text"))
            if "seguro social" not in texto or "dias\ntrabajados" not in texto:
                continue
            for fila in _filas_texto(pagina, "Seguro Social"):
                seguros[fila["trabajador_rut"]][pagina.number + 1] = (
                    fila["dias_trabajados_fonasa"]
                )
        for pagina in pdf:
            texto = normalizar(pagina.get_text("text"))
            if "anexos de detalle" not in texto or "dias\ntrabajados" not in texto:
                continue
            previo = (
                normalizar(pdf[pagina.number - 1].get_text("text"))
                if pagina.number else ""
            )
            folio = re.search(
                r"numero de serie\s*:\s*(\d{15,18})", texto
            )
            folio_previo = re.search(
                r"numero de serie\s*:\s*(\d{15,18})", previo
            )
            if "fonasa" not in previo and pistas.get(pagina.number) != "Fonasa":
                continue
            if (
                folio and folio_previo
                and folio.group(1) != folio_previo.group(1)
            ):
                continue
            filas = _filas_texto(pagina, "Fonasa")
            periodo = _periodo(pagina)
            for fila in filas:
                dias = fila["dias_trabajados_fonasa"]
                vistos = seguros.get(fila["trabajador_rut"], {})
                if vistos and (
                    len(set(vistos.values())) > 1 or dias not in vistos.values()
                ):
                    fila["dias_trabajados_fonasa"] = None
                    fila["dias_requieren_revision"] = True
                    fila["traza_dias"][0].update({
                        "valor": None,
                        "metodo": "conflicto_fuente_dias",
                    })
                    fila["observacion_dias"] = (
                        "Días contradictorios entre Fonasa y Seguro Social."
                    )
                elif vistos:
                    fila["traza_dias"][0]["cotejo_seguro_social"] = "coincide"
                fila.update({
                    "institucion_salud": "Fonasa",
                    "sistema_salud": "Fonasa",
                    "periodo_documento": periodo,
                })
            if filas:
                salida.append({
                    "pagina": pagina.number + 1,
                    "trabajadores": filas,
                    "institucion_salud": "Fonasa",
                    "rotacion": 0,
                    "tipo_extraccion": "texto_pdf",
                    "periodo": periodo,
                })

        if not salida and seguros:
            # Fuente secundaria. NO convertir Seguro Social en comprobante
            # de pago Fonasa ni de una Isapre desconocida.
            for numero in sorted({
                pagina for valores in seguros.values() for pagina in valores
            }):
                pagina = pdf[numero - 1]
                filas = _filas_texto(pagina, "Seguro Social")
                for fila in filas:
                    fila["institucion_salud"] = (
                        "Salud (institución por confirmar)"
                    )
                    fila["sistema_salud"] = "Por verificar"
                    fila["dias_requieren_revision"] = True
                if filas:
                    salida.append({
                        "pagina": numero,
                        "trabajadores": filas,
                        "institucion_salud": "Salud (institución por confirmar)",
                        "tipo_extraccion": "texto_pdf",
                        "rotacion": 0,
                    })
    return salida
