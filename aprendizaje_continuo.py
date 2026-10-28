"""Control de aprendizaje: solo metadatos sin datos personales, con etiquetas verificadas.

No altera el extractor, los resultados ni el estado de conformidad.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json

FEATURES = ("page_count", "text_density", "landscape_ratio", "table_lines", "has_fonasa", "has_afp", "has_dt_logo", "has_nomina")
CLASSES = {"f301", "cotizaciones", "otro"}

def leer_metadatos_validos(path: str) -> list[dict]:
    archivo = Path(path)
    if not archivo.is_file():
        return []
    datos = []
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            item = json.loads(linea)
            if item.get("approved") is not True or item.get("label") not in CLASSES:
                continue
            valores = {k: float(item[k]) for k in FEATURES}
            valores["label"] = item["label"]
            datos.append(valores)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return datos

def evaluar_candidato(datos: list[dict]) -> dict:
    cantidades = Counter(d["label"] for d in datos)
    if len(datos) < 45 or len(cantidades) < 2 or min(cantidades.values(), default=0) < 10:
        return {"estado": "faltan_ejemplos_verificados", "cantidad": len(datos), "clases": dict(cantidades)}
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import f1_score
    from sklearn.model_selection import train_test_split

    X = [[d[k] for k in FEATURES] for d in datos]
    y = [d["label"] for d in datos]
    x_train, x_test, y_train, y_test = train_test_split(X, y, test_size=.25, random_state=42, stratify=y)
    base = DummyClassifier(strategy="most_frequent").fit(x_train, y_train)
    modelo = RandomForestClassifier(n_estimators=80, min_samples_leaf=3, max_depth=8, random_state=42).fit(x_train, y_train)
    score_base = f1_score(y_test, base.predict(x_test), average="macro")
    score_modelo = f1_score(y_test, modelo.predict(x_test), average="macro")
    return {"estado": "candidato_para_revision" if score_modelo >= .92 and score_modelo > score_base + .03 else "no_supera_controles",
            "cantidad": len(datos), "base_f1": round(score_base, 4), "candidato_f1": round(score_modelo, 4),
            "aviso": "No se aplica automáticamente al sistema de auditoría."}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="datos_privados/metadata_aprobada.jsonl")
    p.add_argument("--output", default="informe_calidad_nocturno.json")
    args = p.parse_args()
    resultado = evaluar_candidato(leer_metadatos_validos(args.input))
    resultado["fecha"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    Path(args.output).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False))
