"""
Calibración bibliográfica de GUIOS EVAL.

Calcula la importancia de la literatura (IL) de cada factor con artículos
científicos recientes, siguiendo el procedimiento de la tesis GUIOS
(Sección 5.2.3, Ecuaciones 5.1 y 5.2):

  1. Se arma un corpus de estudios sobre adopción o migración de software libre
     publicados en la ventana de años elegida (por defecto 2020 a 2025).
  2. Para cada factor se cuentan los estudios del corpus que mencionan sus
     términos de búsqueda en el título o el resumen (c_i).
  3. r_i = c_i / n_i, donde n_i es el número de subfactores del factor.
  4. IL = cuartil que ocupa r_i entre todos los factores (1 a 4).
  5. IS = Figura 5.10 aplicada a (IE, IL). IE es la importancia del experto;
     la tesis la obtuvo por encuesta y aquí queda en 3 por defecto, editable.

Fuente: OpenAlex (https://openalex.org), base abierta y gratuita que indexa
más de 250 millones de trabajos (incluye lo publicado en Scopus, IEEE, ACM y
WoS con DOI). No requiere clave. Se usa solo la biblioteca estándar.
"""
import json
import os
import time
import urllib.parse
import urllib.request

API = "https://api.openalex.org/works"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARDADO = os.path.join(RAIZ, "datos", "openalex_2020_2025.json")

# Corpus FLOSS: el título habla de software libre y el resumen de adopción o
# migración, dentro de las áreas de sistemas de información y software.
CORPUS_TITULO = '"open source" OR "free software" OR "FLOSS" OR "FOSS" OR "libre"'
CORPUS_RESUMEN = '"adoption" OR "migration" OR "adopt"'
# Subcampos de OpenAlex: 1710 Information Systems, 1712 Software,
# 1802 Information Systems and Management, 1404 Management Information Systems,
# 3309 Library and Information Sciences.
SUBCAMPOS = "1710|1712|1802|1404|3309"

# Términos por factor (en inglés porque la literatura indexada está en inglés).
# El administrador puede cambiarlos desde la pantalla Calibración bibliográfica.
TERMINOS = {
    "Compatibilidad": '"compatibility" OR "interoperability" OR "file format" OR "open standard"',
    "Fiabilidad": '"reliability" OR "stability" OR "fault tolerance" OR "robustness"',
    "Mantenibilidad": '"maintainability" OR "maintenance" OR "software evolution"',
    "Personalización": '"customization" OR "customisation" OR "configurability" OR "tailoring"',
    "Prueba": '"trialability" OR "trial" OR "pilot" OR "installation"',
    "Documentación": '"documentation" OR "user manual" OR "tutorial"',
    "Portabilidad": '"portability" OR "cross-platform" OR "multi-platform" OR "mobile"',
    "Reusabilidad": '"reusability" OR "reuse" OR "reusable"',
    "Usabilidad": '"usability" OR "ease of use" OR "user experience" OR "user-friendly"',
    "Apoyo de la alta dirección": '"top management" OR "management support" OR "managerial support" OR "leadership"',
    "Formación": '"training" OR "skills" OR "competence" OR "learning curve"',
    "Soporte": '"technical support" OR "community support" OR "vendor support" OR "commercial support"',
    "Actitud hacia el cambio": '"resistance to change" OR "attitude" OR "user resistance" OR "change management"',
    "Bloqueo de proveedores": '"lock-in" OR "vendor dependence" OR "vendor independence" OR "proprietary dependence"',
    "Casos de estudio de adopción FLOSS": '"case study" OR "success story" OR "lessons learned" OR "experience report"',
    "Centralidad de la tecnología de la información":
        '"IT strategy" OR "IT governance" OR "strategic alignment" OR "digital transformation"',
    "Tiempo de adopción": '"adoption time" OR "implementation time" OR "migration time" OR "time to adopt"',
    "Coste total de propiedad": '"total cost of ownership" OR "TCO" OR "cost savings" OR "licensing costs"',
    "Seguridad de la información": '"security" OR "vulnerability" OR "privacy" OR "data protection"',
}


def terminos_de(nombre, personalizados=None):
    if personalizados and personalizados.get(nombre):
        return personalizados[nombre]
    return TERMINOS.get(nombre, f'"{nombre}"')


def _filtro(desde, hasta, terminos=None):
    partes = ["title.search:" + urllib.parse.quote(CORPUS_TITULO),
              "title_and_abstract.search:" + urllib.parse.quote(CORPUS_RESUMEN),
              "primary_topic.subfield.id:" + SUBCAMPOS]
    if terminos:
        partes.append("title_and_abstract.search:" + urllib.parse.quote(terminos))
    partes.append(f"publication_year:{int(desde)}-{int(hasta)}")
    return ",".join(partes)


def url_consulta(desde, hasta, terminos=None, por_pagina=10):
    return (f"{API}?per_page={por_pagina}&sort=cited_by_count:desc"
            f"&select=display_name,publication_year,cited_by_count,doi&filter={_filtro(desde, hasta, terminos)}")


def obtener(url, intentos=3):
    ultimo = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GUIOS-EVAL/2.1 (UNEMI)"})
            with urllib.request.urlopen(req, timeout=25) as r:
                datos = json.loads(r.read().decode("utf-8"))
            if "meta" in datos:
                return datos
            ultimo = datos.get("message") or datos.get("error")
        except Exception as e:  # red caída, límite de uso, etc.
            ultimo = str(e)
        time.sleep(2.5 * (i + 1))
    raise RuntimeError(f"OpenAlex no respondió: {ultimo}")


def consultar(factores, desde=2020, hasta=2025, personalizados=None, pausa=1.3):
    """Consulta OpenAlex en vivo. factores: lista de nombres.

    Devuelve dict con corpus, conteos {factor: c_i}, top {factor: [docs]} y consultas.
    OpenAlex limita a una consulta por segundo las búsquedas con más de cinco
    operadores, por eso se espera `pausa` segundos entre factores.
    """
    corpus = obtener(url_consulta(desde, hasta, None, 1))["meta"]["count"]
    conteos, top, consultas = {}, {}, {}
    for nombre in factores:
        time.sleep(pausa)
        t = terminos_de(nombre, personalizados)
        url = url_consulta(desde, hasta, t)
        d = obtener(url)
        conteos[nombre] = d["meta"]["count"]
        top[nombre] = [[w.get("display_name") or "", w.get("publication_year"), w.get("cited_by_count") or 0,
                        w.get("doi")] for w in d.get("results", [])]
        consultas[nombre] = url
    return {"fuente": "OpenAlex (consulta en vivo)", "desde": desde, "hasta": hasta, "corpus": corpus,
            "conteos": conteos, "top": top, "consultas": consultas}


def guardado():
    """Corrida real del 25/11/2026 incluida con el sistema para trabajar sin internet."""
    with open(GUARDADO, encoding="utf-8") as fh:
        d = json.load(fh)
    d["fuente"] = "OpenAlex (corrida guardada del " + d["fecha"] + ")"
    d["consultas"] = {k: url_consulta(d["desde"], d["hasta"], terminos_de(k)) for k in d["conteos"]}
    return d


# ------------------------------------------------------------------ tendencia
TENDENCIA = os.path.join(RAIZ, "datos", "tendencia_openalex.json")


def url_tendencia(desde, hasta, terminos=None):
    return f"{API}?group_by=publication_year&filter={_filtro(desde, hasta, terminos)}"


def _por_anio(datos):
    return {str(g["key"]): g["count"] for g in datos.get("group_by", [])}


def consultar_tendencia(factores, desde=2008, hasta=2025, personalizados=None, pausa=1.3):
    """Cuenta por año los estudios del corpus y de cada factor (una consulta por factor)."""
    corpus = _por_anio(obtener(url_tendencia(desde, hasta)))
    datos = {}
    for nombre in factores:
        time.sleep(pausa)
        datos[nombre] = _por_anio(obtener(url_tendencia(desde, hasta, terminos_de(nombre, personalizados))))
    return {"fecha": time.strftime("%d/%m/%Y"), "desde": desde, "hasta": hasta, "corpus": corpus, "factores": datos}


def tendencia_guardada():
    if not os.path.exists(TENDENCIA):
        return None
    with open(TENDENCIA, encoding="utf-8") as fh:
        return json.load(fh)


def guardar_tendencia(datos):
    with open(TENDENCIA, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=1)
