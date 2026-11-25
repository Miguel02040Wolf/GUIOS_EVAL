"""
Motor de cálculo de GUIOS EVAL.

Implementa los indicadores definidos en la tesis GUIOS (capítulos 5 y 6):
  IS  Importancia sugerida (viene del catálogo: literatura + expertos)
  ID  Importancia del decisor (1 a 4)
  IR  Importancia relativa = función de la Figura 5.10 aplicada a (ID, IS)
  PS  Ponderación del subfactor (1 a 4)
  PM  Ponderación media del factor = media de las PS evaluadas
  FODA según PM y alcance (interno/externo)
  Recomendación A, B o C según la clasificación FODA y la IR

Correcciones respecto de GUIOS PRO (versión 2022):
  * Ningún valor arranca en 1: lo no evaluado es None ("sin evaluar") y no se
    confunde con "No cumple el requisito".
  * La IR se obtiene con la tabla de la Figura 5.10, no con un promedio.
  * La PM se formatea como número y no se usa como índice de una lista.
  * La lógica de recomendación no falla (antes: `a, b, c = False`) y las
    etiquetas A y C ya no están cruzadas.
  * Se admite más de un decisor: la ID se consolida por mediana y la PS por
    media, y se informa el desacuerdo entre decisores.
"""
from statistics import median

NIVELES = {1: "Irrelevante", 2: "Opcional", 3: "Importante", 4: "Fundamental"}
NIVELES_PS = {1: "No cumple el requisito", 2: "Desconozco si cumple el requisito",
              3: "Cumple parcialmente el requisito", 4: "Cumple el requisito"}

# Figura 5.10 de la tesis. Filas: importancia del decisor (ID) 1..4.
# Columnas: importancia sugerida (IS) 1..4. Valor: importancia relativa (IR).
TABLA_IR = {
    4: {1: 2, 2: 3, 3: 3, 4: 4},
    3: {1: 2, 2: 2, 3: 3, 4: 3},
    2: {1: 1, 2: 2, 3: 2, 4: 3},
    1: {1: 1, 2: 1, 3: 2, 4: 2},
}


def importancia_relativa(id_valor, is_valor):
    """IR según la Figura 5.10. Devuelve None si falta la ID."""
    if id_valor is None or is_valor is None:
        return None
    return TABLA_IR[int(id_valor)][int(is_valor)]


def es_relevante(ir):
    """Paso 2: un factor es relevante si su IR es Opcional o superior (IR > 1)."""
    return ir is not None and ir > 1


def redondeo_usual(x):
    """Redondeo de la tesis: .5 o más sube (3,5 -> 4); menos de .5 baja."""
    return int(x + 0.5)


def consenso_id(valores):
    """Consolida la ID de varios decisores con la mediana (redondeo usual)."""
    v = [int(x) for x in valores if x is not None]
    if not v:
        return None
    return redondeo_usual(median(v))


def desacuerdo(valores):
    """Hay desacuerdo cuando dos decisores difieren en 2 niveles o más."""
    v = [int(x) for x in valores if x is not None]
    return len(v) > 1 and (max(v) - min(v)) >= 2


def consenso_ps(valores):
    """Consolida la PS de un subfactor con la media de los decisores que la evaluaron."""
    v = [float(x) for x in valores if x is not None]
    if not v:
        return None
    return sum(v) / len(v)


def ponderacion_media(ps_list):
    """Paso 4: PM = media de las PS evaluadas. None si no hay ninguna."""
    v = [p for p in ps_list if p is not None]
    if not v:
        return None
    return sum(v) / len(v)


def clasificar_foda(pm, alcance, umbral=3.0):
    """Paso 5: reglas de asignación FODA de la tesis (umbral configurable, por defecto 3)."""
    if pm is None or alcance not in ("Interno", "Externo"):
        return None
    if alcance == "Interno":
        return "Fortaleza" if pm >= umbral else "Debilidad"
    return "Oportunidad" if pm >= umbral else "Amenaza"


ACCIONES_INTERNAS = {
    "Formación": "planificar capacitaciones para el personal antes del despliegue",
    "Tiempo de adopción": "ajustar el cronograma de implantación y preparar el entorno de instalación",
    "Centralidad de la tecnología de la información": "fortalecer el área de TI que respaldará el software",
    "Apoyo de la alta dirección": "presentar el caso de negocio a la alta dirección y obtener su patrocinio",
    "Soporte": "formar o contratar personal técnico que brinde soporte al software",
    "Actitud hacia el cambio": "ejecutar un plan de gestión del cambio con los usuarios finales",
    "Coste total de propiedad": "estimar con detalle los costes de migración, formación y mantenimiento",
}
ACCIONES_EXTERNAS = {
    "Compatibilidad": "verificar formatos, integración con sistemas existentes y soporte de hardware",
    "Personalización": "evaluar el esfuerzo de adaptar el software mediante configuración o módulos",
    "Prueba": "montar un piloto controlado para instalar y probar el software",
    "Fiabilidad": "revisar el historial de errores y la estabilidad de las versiones",
    "Reusabilidad": "revisar la licencia y las bibliotecas reutilizables que ofrece el proyecto",
    "Usabilidad": "realizar pruebas de usabilidad con usuarios representativos",
    "Mantenibilidad": "comprobar la actividad del proyecto y la frecuencia de actualizaciones",
    "Portabilidad": "validar el funcionamiento en las plataformas y bases de datos requeridas",
    "Documentación": "reunir y revisar la documentación de usuario y de desarrollo disponible",
    "Casos de estudio de adopción FLOSS": "buscar organizaciones similares que ya lo hayan adoptado",
    "Bloqueo de proveedores": "confirmar que existen varios proveedores y formatos abiertos",
    "Soporte": "identificar comunidades y empresas que ofrezcan soporte externo",
}


def calcular(factores, umbral=3.0):
    """
    factores: lista de dicts con
      nombre, dimension, is_valor, alcance (Interno/Externo/Ambos),
      ids (lista de ID de cada decisor), alcance_elegido (para 'Ambos'),
      subfactores: lista de dicts {texto, valores: [PS por decisor]}
    Devuelve el detalle por factor, conteos FODA, recomendación y puntajes.
    """
    detalle = []
    for f in factores:
        ids = f.get("ids", [])
        id_c = consenso_id(ids)
        ir = importancia_relativa(id_c, f["is_valor"])
        alcance = f["alcance"] if f["alcance"] != "Ambos" else (f.get("alcance_elegido") or "Interno")
        subs = []
        for s in f["subfactores"]:
            ps = consenso_ps(s.get("valores", []))
            subs.append({"texto": s["texto"], "ps": ps,
                         "desacuerdo": desacuerdo(s.get("valores", [])),
                         "n": len([x for x in s.get("valores", []) if x is not None])})
        relevante = es_relevante(ir)
        pm = ponderacion_media([s["ps"] for s in subs]) if relevante else None
        evaluados = len([s for s in subs if s["ps"] is not None])
        completo = relevante and evaluados == len(subs)
        foda = clasificar_foda(pm, alcance, umbral) if relevante else None
        detalle.append({
            "nombre": f["nombre"], "dimension": f["dimension"], "is_valor": f["is_valor"],
            "id": id_c, "ids": ids, "desacuerdo_id": desacuerdo(ids), "ir": ir,
            "relevante": relevante, "alcance": alcance, "alcance_catalogo": f["alcance"],
            "pm": pm, "foda": foda, "subfactores": subs, "evaluados": evaluados,
            "total_sub": len(subs), "completo": completo,
        })

    conteo = {"Fortaleza": 0, "Oportunidad": 0, "Debilidad": 0, "Amenaza": 0}
    for d in detalle:
        if d["foda"]:
            conteo[d["foda"]] += 1

    recomendacion = recomendar(detalle)
    puntaje, dims = puntajes(detalle)
    pendientes = [d["nombre"] for d in detalle if d["relevante"] and not d["completo"]]
    return {"factores": detalle, "conteo": conteo, "recomendacion": recomendacion,
            "puntaje": puntaje, "dimensiones": dims, "pendientes": pendientes,
            "relevantes": len([d for d in detalle if d["relevante"]]),
            "sin_id": len([d for d in detalle if d["id"] is None])}


def recomendar(detalle):
    """
    Paso 6. Reglas de la tesis (sección 6.2.3):
      C: hay Debilidades/Amenazas en factores con IR Importante o Fundamental.
      B: solo hay Debilidades/Amenazas en factores con IR Opcional.
      A: todos los factores evaluados son Fortalezas u Oportunidades.
    La recomendación es personalizada: nombra los factores y subfactores que la causan.
    """
    evaluados = [d for d in detalle if d["foda"]]
    if not evaluados:
        return None
    negativos = [d for d in evaluados if d["foda"] in ("Debilidad", "Amenaza")]
    criticos = [d for d in negativos if d["ir"] >= 3]
    if criticos:
        tipo, titulo = "C", "Se sugiere analizar la adopción y posponerla"
        base = criticos
    elif negativos:
        tipo, titulo = "B", "Es posible adoptar, con matices"
        base = negativos
    else:
        tipo, titulo = "A", "Adoptar el software evaluado"
        base = []

    causas = []
    for d in base:
        bajos = [s["texto"] for s in d["subfactores"] if s["ps"] is not None and s["ps"] < 3]
        sin_info = [s["texto"] for s in d["subfactores"] if s["ps"] is not None and 1.5 < s["ps"] < 2.5]
        if d["alcance"] == "Interno":
            accion = ACCIONES_INTERNAS.get(d["nombre"], "fortalecer los recursos internos asociados al factor")
        else:
            accion = ACCIONES_EXTERNAS.get(d["nombre"], "dedicar recursos de ingeniería para mejorar este aspecto del software")
        causas.append({"factor": d["nombre"], "foda": d["foda"], "ir": NIVELES[d["ir"]],
                       "pm": d["pm"], "subfactores": bajos, "dudas": sin_info, "accion": accion})

    fuertes = [d["nombre"] for d in evaluados if d["foda"] in ("Fortaleza", "Oportunidad")]
    if tipo == "A":
        texto = ("Todos los factores evaluados son fortalezas u oportunidades. La organización cumple "
                 "con los requisitos necesarios para adoptar el software.")
    elif tipo == "B":
        texto = ("Se detectaron debilidades o amenazas solo en factores de importancia relativa opcional. "
                 "Se recomienda una segunda evaluación centrada en los subfactores que no cumplen.")
    else:
        texto = ("Existen debilidades o amenazas en factores importantes o fundamentales para la organización. "
                 "Antes de adoptar, la organización debe atender las causas que se detallan.")
    return {"tipo": tipo, "titulo": titulo, "texto": texto, "causas": causas, "fortalezas": fuertes}


def puntajes(detalle):
    """
    Índice de adopción (0 a 100), complementario a la recomendación de la tesis:
    media de (PM - 1) / 3 ponderada por la IR de cada factor relevante evaluado.
    """
    def indice(items):
        num = sum(d["ir"] * (d["pm"] - 1) / 3 for d in items)
        den = sum(d["ir"] for d in items)
        return round(100 * num / den) if den else None

    evaluados = [d for d in detalle if d["pm"] is not None]
    dims = {}
    for dim in ("Tecnológica", "Organizacional", "Económica"):
        dims[dim] = indice([d for d in evaluados if d["dimension"] == dim])
    return indice(evaluados), dims


def explicar(d, umbral=3.0):
    """Texto paso a paso de cómo se obtuvo el resultado de un factor."""
    lineas = []
    if d["id"] is None:
        return ["El decisor aún no ha asignado la importancia de este factor."]
    if len(d["ids"]) > 1:
        lineas.append("ID por decisor: " + ", ".join(str(x) for x in d["ids"] if x is not None)
                      + f"; consenso (mediana) = {d['id']} ({NIVELES[d['id']]}).")
    lineas.append(f"IS = {d['is_valor']} ({NIVELES[d['is_valor']]}) e ID = {d['id']} ({NIVELES[d['id']]}); "
                  f"según la Figura 5.10, IR = {d['ir']} ({NIVELES[d['ir']]}).")
    if not d["relevante"]:
        lineas.append("Como la IR es Irrelevante, el factor se excluye del análisis (paso 2).")
        return lineas
    if d["pm"] is None:
        lineas.append("Ningún subfactor ha sido evaluado todavía.")
        return lineas
    def c(x, n=1):
        return f"{x:.{n}f}".replace(".", ",")
    vals = [c(s["ps"]) for s in d["subfactores"] if s["ps"] is not None]
    lineas.append(f"PM = media de {len(vals)} subfactores ({' + '.join(vals)}) / {len(vals)} = {c(d['pm'], 2)}.")
    signo = "≥" if d["pm"] >= umbral else "<"
    lineas.append(f"PM {signo} {c(umbral)} y alcance {d['alcance']}: el factor es {d['foda']}.")
    return lineas


# ----------------------------------------------------------------------------
# Importancia de la literatura (IL) e importancia sugerida (IS)
# Tesis, Sección 5.2.3, Ecuaciones 5.1 y 5.2 y Tabla 5.3.
#   r_i = c_i / n_i        (citas del factor / número de subfactores)
#   IL  = cuartil que ocupa r_i entre todas las r de los factores (1..4)
#   IS  = función de la Figura 5.10 aplicada a (IE, IL)
# En la tesis este cálculo se hizo a mano con el corpus 2008-2019. GUIOS EVAL lo
# automatiza para cualquier ventana de años (por defecto 2020-2025).
# ----------------------------------------------------------------------------
def percentil(valores, p):
    """Percentil con interpolación lineal (mismo criterio que una hoja de cálculo
    con PERCENTIL.INC o numpy.percentile por defecto)."""
    v = sorted(valores)
    if not v:
        return 0.0
    pos = (len(v) - 1) * p
    i = int(pos)
    frac = pos - i
    if i + 1 < len(v):
        return v[i] + (v[i + 1] - v[i]) * frac
    return float(v[i])


def umbrales_cuartiles(rs):
    """Devuelve (rq1, rq2, rq3): valores máximos de los tres primeros cuartiles."""
    return percentil(rs, 0.25), percentil(rs, 0.50), percentil(rs, 0.75)


def nivel_cuartil(r, umbrales):
    """Ecuación 5.2 de la tesis."""
    q1, q2, q3 = umbrales
    if r <= q1:
        return 1
    if r <= q2:
        return 2
    if r <= q3:
        return 3
    return 4


def importancia_sugerida(ie, il):
    """IS a partir de la importancia del experto y la de la literatura (Figura 5.10)."""
    return TABLA_IR[int(ie)][int(il)]


def calibrar(factores):
    """Calcula IL e IS para una lista de factores.

    Cada factor es un dict con: nombre, n (subfactores), citas, ie (por defecto 3).
    Devuelve (filas, umbrales). Cada fila agrega r, il e is_nueva.
    """
    filas = []
    for f in factores:
        n = max(int(f.get("n") or 0), 1)
        citas = int(f.get("citas") or 0)
        filas.append(dict(f, n=n, citas=citas, ie=int(f.get("ie") or 3), r=citas / n))
    umbrales = umbrales_cuartiles([x["r"] for x in filas])
    for x in filas:
        x["il"] = nivel_cuartil(x["r"], umbrales)
        x["is_nueva"] = importancia_sugerida(x["ie"], x["il"])
    return filas, umbrales


# ----------------------------------------------------------------------------
# Análisis de sensibilidad: ¿qué respuesta, si cambiara, cambia la recomendación?
# ----------------------------------------------------------------------------
ORDEN_REC = {"C": 0, "B": 1, "A": 2}


def sensibilidad(factores, umbral=3.0, limite=8):
    """Simula, una por una, cada respuesta posible de cada subfactor evaluado de los
    factores relevantes y reporta las que cambian la recomendación por sí solas.

    Devuelve {base, mejoras, riesgos, cercanos}:
      mejoras: cambios que llevan a una recomendación mejor (C->B, C->A, B->A).
      riesgos: cambios que la empeoran.
      cercanos: factores relevantes cuyo PM está a menos de 0,5 del umbral.
    """
    import copy
    base = calcular(factores, umbral)
    rec = base["recomendacion"]
    if not rec:
        return None
    tipo0 = rec["tipo"]
    mejoras, riesgos = [], []
    for i, f_out in enumerate(base["factores"]):
        if not f_out["relevante"]:
            continue
        for j, s_out in enumerate(f_out["subfactores"]):
            if s_out["ps"] is None:
                continue
            for v in (1, 2, 3, 4):
                if abs(v - s_out["ps"]) < 0.01:
                    continue
                prueba = copy.deepcopy(factores)
                prueba[i]["subfactores"][j]["valores"] = [v]
                r = calcular(prueba, umbral)["recomendacion"]
                if r and r["tipo"] != tipo0:
                    item = {"factor": f_out["nombre"], "subfactor": s_out["texto"], "desde": s_out["ps"],
                            "hasta": v, "nueva": r["tipo"], "salto": abs(v - s_out["ps"])}
                    (mejoras if ORDEN_REC[r["tipo"]] > ORDEN_REC[tipo0] else riesgos).append(item)
    mejoras.sort(key=lambda x: (-ORDEN_REC[x["nueva"]], x["salto"]))
    riesgos.sort(key=lambda x: (ORDEN_REC[x["nueva"]], x["salto"]))
    # una sola entrada por subfactor (el cambio mínimo)
    def unico(lista):
        vistos, out = set(), []
        for x in lista:
            k = (x["factor"], x["subfactor"])
            if k not in vistos:
                vistos.add(k)
                out.append(x)
        return out[:limite]
    cercanos = []
    for f in base["factores"]:
        if f["relevante"] and f["pm"] is not None and abs(f["pm"] - umbral) < 0.5:
            evaluados = [s for s in f["subfactores"] if s["ps"] is not None]
            puntos = round((umbral - f["pm"]) * len(evaluados), 2)
            cercanos.append({"factor": f["nombre"], "pm": f["pm"], "foda": f["foda"], "ir": f["ir"],
                             "puntos": puntos})
    # Ruta mínima: para cada factor negativo, los subfactores más bajos que habría que
    # llevar a "Cumple" para que su PM alcance el umbral; luego se verifica el efecto conjunto.
    ruta, prueba, prueba_crit = [], copy.deepcopy(factores), copy.deepcopy(factores)
    for i, f in enumerate(base["factores"]):
        if f["foda"] not in ("Debilidad", "Amenaza"):
            continue
        idx = sorted([j for j, s in enumerate(f["subfactores"]) if s["ps"] is not None],
                     key=lambda j, f=f: f["subfactores"][j]["ps"])
        vals = {j: f["subfactores"][j]["ps"] for j in idx}
        elegidos = []
        for j in idx:
            if sum(vals.values()) / len(vals) >= umbral:
                break
            vals[j] = 4
            elegidos.append(f["subfactores"][j]["texto"])
            prueba[i]["subfactores"][j]["valores"] = [4]
            if f["ir"] >= 3:
                prueba_crit[i]["subfactores"][j]["valores"] = [4]
        ruta.append({"factor": f["nombre"], "foda": f["foda"], "critico": f["ir"] >= 3, "pm": f["pm"],
                     "subfactores": elegidos})
    final = calcular(prueba, umbral)["recomendacion"] if ruta else None
    return {"base": tipo0, "mejoras": unico(mejoras), "riesgos": unico(riesgos), "cercanos": cercanos,
            "ruta": ruta, "ruta_resultado": final["tipo"] if final else tipo0,
            "ruta_total": sum(len(r["subfactores"]) for r in ruta),
            "ruta_criticos_total": sum(len(r["subfactores"]) for r in ruta if r["critico"]),
            "ruta_criticos_resultado": (calcular(prueba_crit, umbral)["recomendacion"]["tipo"]
                                        if any(r["critico"] for r in ruta) else None)}


# ----------------------------------------------------------------------------
# Tendencia de la literatura por año
# ----------------------------------------------------------------------------
def tendencia(conteos, corpus, desde, hasta, corte=2020):
    """Participación anual de un factor en el corpus (porcentaje de estudios que lo mencionan),
    pendiente de la recta de mínimos cuadrados (puntos porcentuales por año) y comparación
    entre el período de la tesis (desde..corte-1) y el reciente (corte..hasta)."""
    anios = list(range(desde, hasta + 1))
    serie = []
    for a in anios:
        tot = int(corpus.get(str(a), 0) or 0)
        n = int(conteos.get(str(a), 0) or 0)
        serie.append({"anio": a, "n": n, "total": tot, "pct": (100.0 * n / tot) if tot else 0.0})
    xs = [s["anio"] for s in serie]
    ys = [s["pct"] for s in serie]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    pendiente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0

    def periodo(a, b):
        n = sum(s["n"] for s in serie if a <= s["anio"] <= b)
        t = sum(s["total"] for s in serie if a <= s["anio"] <= b)
        return n, (100.0 * n / t) if t else 0.0
    n_ant, pct_ant = periodo(desde, corte - 1)
    n_rec, pct_rec = periodo(corte, hasta)
    if pct_rec >= pct_ant * 1.25 and pct_rec - pct_ant >= 1:
        etiqueta = "Sube"
    elif pct_rec <= pct_ant * 0.75 and pct_ant - pct_rec >= 1:
        etiqueta = "Baja"
    else:
        etiqueta = "Estable"
    return {"serie": serie, "pendiente": pendiente, "n_anterior": n_ant, "pct_anterior": pct_ant,
            "n_reciente": n_rec, "pct_reciente": pct_rec, "etiqueta": etiqueta}


# ----------------------------------------------------------------------------
# Matriz de riesgos de la adopción (probabilidad x impacto, escala 1 a 5)
# ----------------------------------------------------------------------------
IMPACTO_POR_IR = {4: 5, 3: 4, 2: 2, 1: 1}


def probabilidad_por_pm(pm, umbral=3.0):
    """Cuanto más baja la ponderación media, más probable que el riesgo se materialice."""
    if pm is None:
        return 3
    return max(1, min(5, round(1 + (umbral - pm) / (umbral - 1) * 4)))


def nivel_riesgo(valor):
    if valor >= 15:
        return "Alto"
    if valor >= 8:
        return "Medio"
    return "Bajo"


def matriz_riesgos(resultado, umbral=3.0):
    """Convierte cada Debilidad o Amenaza en un riesgo de la adopción con su respuesta."""
    riesgos = []
    causas = {c["factor"]: c for c in (resultado.get("recomendacion") or {}).get("causas", [])}
    for f in resultado["factores"]:
        if f["foda"] not in ("Debilidad", "Amenaza"):
            continue
        p = probabilidad_por_pm(f["pm"], umbral)
        i = IMPACTO_POR_IR.get(f["ir"], 2)
        v = p * i
        nivel = nivel_riesgo(v)
        interno = f["foda"] == "Debilidad"
        if nivel == "Bajo":
            respuesta = "Aceptar y monitorear"
        elif interno:
            respuesta = "Mitigar"
        else:
            respuesta = "Transferir" if f["nombre"] in ("Soporte", "Mantenibilidad", "Fiabilidad") else "Mitigar"
        bajos = [s["texto"] for s in f["subfactores"] if s["ps"] is not None and s["ps"] < umbral]
        c = causas.get(f["nombre"])
        if c:
            accion = c["accion"]
        elif interno:
            accion = ACCIONES_INTERNAS.get(f["nombre"], "fortalecer los recursos internos asociados al factor")
        else:
            accion = ACCIONES_EXTERNAS.get(f["nombre"], "dedicar recursos de ingeniería para mejorar este aspecto")
        riesgos.append({"factor": f["nombre"], "foda": f["foda"], "pm": f["pm"], "ir": f["ir"],
                        "probabilidad": p, "impacto": i, "valor": v, "nivel": nivel, "respuesta": respuesta,
                        "accion": accion[:1].upper() + accion[1:], "evidencia": bajos[:3],
                        "descripcion": f"{'Debilidad interna' if interno else 'Amenaza externa'} en "
                                       f"{f['nombre'].lower()}: PM {f['pm']:.2f} bajo el umbral {umbral:.1f}"})
    riesgos.sort(key=lambda r: (-r["valor"], r["factor"]))
    celdas = {}
    for r in riesgos:
        celdas.setdefault((r["probabilidad"], r["impacto"]), []).append(r["factor"])
    return {"riesgos": riesgos, "celdas": celdas,
            "conteo": {n: sum(1 for r in riesgos if r["nivel"] == n) for n in ("Alto", "Medio", "Bajo")}}
