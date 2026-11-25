"""
Sello de integridad de los informes de GUIOS EVAL.

Cada informe PDF recibe un folio único, un código QR y dos huellas SHA-256:
  * hash_datos: resume los datos de la evaluación (recomendación, FODA, decisión, fecha).
  * hash_archivo: huella del archivo PDF exacto que se descargó.
Para verificar, se sube el PDF (si un solo byte cambió, la huella no coincide) o se
escribe el folio impreso para ver los datos que quedaron registrados al emitirlo.
"""
import hashlib
import io
import json
import re
import secrets

import segno

PATRON_FOLIO = re.compile(rb"GE-[0-9A-F]{10}")


def datos_sellables(ev, res, fecha):
    rec = res.get("recomendacion") or {}
    return {
        "codigo": ev["codigo"], "organizacion": ev["org_nombre"],
        "software": f"{ev['sw_nombre']} {ev['sw_version'] or ''}".strip(),
        "estado": ev["estado"], "decision": ev["decision"],
        "recomendacion": f"{rec.get('tipo', '-')}: {rec.get('titulo', 'sin resultado')}",
        "indice": res.get("puntaje"),
        "foda": {f["nombre"]: [f["foda"], round(f["pm"], 2)] for f in res["factores"] if f["foda"]},
        "emitido": fecha,
    }


def huella_datos(datos):
    texto = json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def nuevo_folio():
    return "GE-" + secrets.token_hex(5).upper()


def qr_png(texto, escala=6):
    buf = io.BytesIO()
    segno.make(texto, error="m").save(buf, kind="png", scale=escala, border=1)
    buf.seek(0)
    return buf


def huella_archivo(contenido):
    return hashlib.sha256(contenido).hexdigest()


def folio_en_pdf(contenido):
    m = PATRON_FOLIO.search(contenido or b"")
    return m.group(0).decode() if m else None
