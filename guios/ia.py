"""
Asistente de inteligencia artificial de GUIOS EVAL (RF-13, optativo).

Reglas de diseño:
  * La IA solo SUGIERE. El evaluador acepta o descarta cada sugerencia y la
    recomendación A, B o C siempre sale del motor de cálculo de la guía GUIOS.
  * Las fuentes que la IA cita se filtran: solo se aceptan DOI que vienen de la
    calibración bibliográfica (OpenAlex). Si inventa una referencia, se descarta.
  * Varios proveedores con respaldo automático: Groq -> Gemini -> IA local
    (Ollama, sin internet) -> sin IA. Si ninguno responde, el sistema sigue
    funcionando con el motor de reglas.
  * Las claves se leen de claves_guios.env (en la carpeta del proyecto) o de
    variables de entorno; nunca se envían al navegador ni se guardan en la base.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Se buscan claves en: variables de entorno, claves_guios.env y .env del proyecto y, por compatibilidad,
# ../claves_guios.env de versiones anteriores
ARCHIVOS_CLAVES = [os.path.join(RAIZ, "claves_guios.env"), os.path.join(RAIZ, ".env"),
                   os.path.join(os.path.dirname(RAIZ), "claves_guios.env")]

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELOS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
GEMINI_MODELOS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]
OLLAMA_MODELO = "qwen2.5:3b"

NOMBRES = {"groq": "Groq", "gemini": "Gemini", "ollama": "IA local (Ollama)"}


def _leer_claves():
    datos = {}
    for ruta in ARCHIVOS_CLAVES:
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as fh:
                for linea in fh:
                    linea = linea.strip()
                    if linea and not linea.startswith("#") and "=" in linea:
                        k, v = linea.split("=", 1)
                        datos.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "OLLAMA_URL", "OLLAMA_MODEL"):
        if os.environ.get(k):
            datos[k] = os.environ[k]
    return datos


def estado():
    c = _leer_claves()
    url = c.get("OLLAMA_URL", "http://127.0.0.1:11434")
    modelo = c.get("OLLAMA_MODEL", OLLAMA_MODELO)
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=1) as r:
            nombres = [m.get("name", "") for m in json.loads(r.read().decode("utf-8")).get("models", [])]
        local = "lista" if modelo in nombres else "sin modelo"
    except Exception:
        local = "no disponible"
    return {"groq": bool(c.get("GROQ_API_KEY")), "gemini": bool(c.get("GEMINI_API_KEY")),
            "ollama_url": url, "ollama_modelo": modelo, "ollama": local}


def orden_proveedores(modo):
    if modo == "desactivado":
        return []
    if modo == "local":
        return ["ollama"]
    if modo == "nube":
        return ["groq", "gemini"]
    return ["groq", "gemini", "ollama"]  # automático


def _post(url, cuerpo, cabeceras, timeout):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode("utf-8"),
                                 headers=dict({"Content-Type": "application/json", "Accept": "application/json",
                                               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GUIOS-EVAL/2.1"},
                                              **cabeceras))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _groq(sistema, usuario, c):
    ultimo = None
    for m in GROQ_MODELOS:
        try:
            d = _post(GROQ_URL, {"model": m, "temperature": 0.2, "response_format": {"type": "json_object"},
                                 "messages": [{"role": "system", "content": sistema},
                                              {"role": "user", "content": usuario}]},
                      {"Authorization": "Bearer " + c["GROQ_API_KEY"]}, 60)
            return d["choices"][0]["message"]["content"], m
        except Exception as e:
            ultimo = e
    raise RuntimeError(f"Groq: {ultimo}")


def _gemini(sistema, usuario, c):
    ultimo = None
    for m in GEMINI_MODELOS:
        for intento in range(3):
            try:
                d = _post(GEMINI_URL.format(m=m),
                          {"systemInstruction": {"parts": [{"text": sistema}]},
                           "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                           "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}},
                          {"x-goog-api-key": c["GEMINI_API_KEY"]}, 90)
                return "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"]), m
            except urllib.error.HTTPError as e:
                ultimo = e
                if e.code in (429, 500, 503) and intento < 2:
                    time.sleep(3 * (intento + 1))
                    continue
                break
            except Exception as e:
                ultimo = e
                break
    raise RuntimeError(f"Gemini: {ultimo}")


def _ollama(sistema, usuario, c):
    url = c.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    m = c.get("OLLAMA_MODEL", OLLAMA_MODELO)
    d = _post(url, {"model": m, "stream": False, "format": "json", "options": {"temperature": 0.2},
                    "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]},
              {}, 300)
    return d["message"]["content"], m


def _json(texto):
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.M).strip()
    try:
        return json.loads(texto)
    except ValueError:
        m = re.search(r"\{.*\}", texto, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def preguntar(sistema, usuario, modo="automatico"):
    """Prueba los proveedores en orden. Devuelve (dict, proveedor, modelo, errores)."""
    c = _leer_claves()
    errores = []
    for p in orden_proveedores(modo):
        if p == "groq" and not c.get("GROQ_API_KEY"):
            continue
        if p == "gemini" and not c.get("GEMINI_API_KEY"):
            continue
        try:
            texto, modelo = {"groq": _groq, "gemini": _gemini, "ollama": _ollama}[p](sistema, usuario, c)
            return _json(texto), p, modelo, errores
        except Exception as e:
            errores.append(f"{NOMBRES[p]}: {str(e)[:160]}")
    return None, None, None, errores


def probar(modo="automatico"):
    d, p, m, err = preguntar("Responde solo con JSON.", 'Devuelve {"ok": true}', modo)
    return {"ok": bool(d and d.get("ok")), "proveedor": NOMBRES.get(p), "modelo": m, "errores": err}


# ------------------------------------------------------------------ prompts
SISTEMA_SUB = (
    "Eres un auditor experto en adopción de software libre (FLOSS) que aplica la guía GUIOS "
    "(Rea Sánchez, 2022). Calificas subfactores con la escala literal de la guía: "
    "1 = No cumple el requisito, 2 = Desconozco si cumple el requisito, 3 = Cumple parcialmente "
    "el requisito, 4 = Cumple el requisito. Puedes usar el conocimiento público y verificable sobre el "
    "software (documentación oficial, características conocidas, comunidad); usa 2 solo cuando no exista "
    "información suficiente y nunca inventes datos. Respondes en español, con justificaciones breves y "
    "concretas sobre el software "
    "indicado. Solo puedes citar los DOI que aparecen en la lista de estudios; si ninguno aplica, "
    "deja la lista vacía. Respondes solo con JSON válido."
)


def prompt_subfactores(ev, factor, estudios):
    lineas = [f"Organización: {ev['org_nombre']} (sector: {ev['org_sector'] or 'no indicado'}).",
              f"Software evaluado: {ev['sw_nombre']} {ev['sw_version'] or ''}; tipo: {ev['sw_tipo'] or 'no indicado'}; "
              f"licencia: {ev['sw_licencia'] or 'no indicada'}; proveedor o comunidad: {ev['sw_proveedor'] or 'no indicado'}.",
              f"Descripción: {ev['sw_descripcion'] or 'sin descripción'}.",
              f"Factor: {factor['nombre']} ({factor['dimension']}, alcance {factor['alcance']}). "
              f"{factor.get('descripcion') or ''}",
              "Subfactores a calificar:"]
    for s in factor["subfactores"]:
        lineas.append(f'- clave "{s["key"]}": {s["texto"]}')
    if estudios:
        lineas.append("Estudios 2020-2025 sobre este factor (OpenAlex) que puedes citar por su DOI:")
        for t, y, _, doi in estudios[:6]:
            if doi:
                lineas.append(f"- {doi} | {t} ({y})")
    lineas.append('Devuelve: {"propuestas": [{"key": "<clave>", "valor": 1-4, "confianza": 0-100, '
                  '"justificacion": "<máximo 35 palabras>", "fuentes": ["<DOI de la lista>"]}]} '
                  "con una propuesta por cada subfactor.")
    return "\n".join(lineas)


def sugerir_subfactores(ev, factor, estudios, modo="automatico"):
    d, p, m, err = preguntar(SISTEMA_SUB, prompt_subfactores(ev, factor, estudios), modo)
    if d is None:
        return {"ok": False, "errores": err}
    validas = {s["key"] for s in factor["subfactores"]}
    dois = {e[3] for e in estudios if e[3]}
    dois_cortos = {x.replace("https://doi.org/", "").lower(): x for x in dois}
    out = []
    for x in d.get("propuestas", []):
        try:
            k, v = str(x.get("key")), int(x.get("valor"))
        except (TypeError, ValueError):
            continue
        if k not in validas or v not in (1, 2, 3, 4):
            continue
        fuentes = []
        for f in x.get("fuentes") or []:
            f2 = str(f).replace("https://doi.org/", "").lower().strip()
            if f2 in dois_cortos:
                fuentes.append(dois_cortos[f2])
        conf = max(0, min(100, int(x.get("confianza") or 50)))
        out.append({"key": k, "valor": v, "confianza": conf,
                    "justificacion": str(x.get("justificacion") or "")[:400], "fuentes": fuentes})
    return {"ok": bool(out), "propuestas": out, "proveedor": NOMBRES[p], "modelo": m, "errores": err}


SISTEMA_RES = (
    "Eres analista de la Dirección de TIC y redactas informes de adopción de software libre con la "
    "guía GUIOS. No calculas la recomendación: te la dan ya calculada y debes respetarla "
    "exactamente, sin contradecirla ni suavizarla. Escribes en español formal, en prosa, sin "
    "viñetas en el resumen y sin inventar cifras. Respondes solo con JSON válido."
)


def sugerir_resumen(ev, res, modo="automatico"):
    rec = res["recomendacion"]
    lineas = [f"Organización: {ev['org_nombre']}. Software: {ev['sw_nombre']} {ev['sw_version'] or ''}.",
              f"Recomendación calculada por GUIOS: tipo {rec['tipo']} ({rec['titulo']}).",
              f"Índice de adopción: {res['puntaje']}/100.",
              "Clasificación FODA de los factores relevantes:"]
    for f in res["factores"]:
        if f["foda"]:
            lineas.append(f"- {f['nombre']}: {f['foda']}, PM {f['pm']:.2f}, importancia relativa {f['ir']}")
    if rec["causas"]:
        lineas.append("Causas de la recomendación y subfactores que no se cumplen:")
        for c in rec["causas"]:
            lineas.append(f"- {c['factor']} ({c['foda']}): {'; '.join(c['subfactores'][:4]) or 'sin detalle'}")
    lineas.append('Devuelve: {"resumen": "<resumen ejecutivo de 110 a 160 palabras que mencione la '
                  f'recomendación tipo {rec["tipo"]}>", "plan": [{{"factor": "<factor>", "accion": "<acción concreta>", '
                  '"entregable": "<entregable verificable>", "plazo": "<semanas>", "responsable": "<área>"}]} '
                  "con una fila del plan por cada causa (o, si no hay causas, de 2 a 3 acciones para la implantación).")
    d, p, m, err = preguntar(SISTEMA_RES, "\n".join(lineas), modo)
    if d is None:
        return {"ok": False, "errores": err}
    texto = str(d.get("resumen") or "").strip()
    coherente = coherencia(texto, rec["tipo"])
    plan = [{k: str(x.get(k) or "")[:300] for k in ("factor", "accion", "entregable", "plazo", "responsable")}
            for x in (d.get("plan") or []) if isinstance(x, dict)]
    return {"ok": bool(texto), "resumen": texto, "plan": plan, "coherente": coherente,
            "proveedor": NOMBRES[p], "modelo": m, "errores": err}


def coherencia(texto, tipo):
    """El texto no debe mencionar otra recomendación ni frases propias de otro tipo."""
    letras = set(re.findall(r"[Rr]ecomendaci[oó]n\s+(?:de\s+)?(?:tipo\s+)?[«\"']?([ABC])\b", texto))
    if letras and letras != {tipo}:
        return False
    contrarias = {"A": ["posponer", "no se recomienda adoptar"],
                  "C": ["adoptar sin reservas", "se recomienda adoptar de inmediato", "puede adoptarse sin"],
                  "B": ["adoptar sin reservas"]}
    bajo = texto.lower()
    return not any(c in bajo for c in contrarias[tipo])
