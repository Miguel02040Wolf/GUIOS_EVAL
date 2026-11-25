"""Exportación del resultado de una evaluación a Excel (.xlsx) y a PDF."""
import io
import os

from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from guios import motor as engine

BASE = os.path.dirname(os.path.abspath(__file__))
COLOR_FODA = {"Fortaleza": "DCFCE7", "Oportunidad": "DBEAFE", "Debilidad": "FEF3C7", "Amenaza": "FEE2E2"}
COLOR_REC = {"A": "DCFCE7", "B": "FEF3C7", "C": "FEE2E2"}
MARCA = "1E2A44"


def _num(v, d=2):
    return "" if v is None else round(v, d)


# ---------------------------------------------------------------- Excel
def excel(ev, res, sens=None, resumen=None, respuestas=None, riesgos=None):
    wb = Workbook()
    fino = Side(style="thin", color="CBD5E1")
    borde = Border(left=fino, right=fino, top=fino, bottom=fino)
    cab = Font(bold=True, color="FFFFFF")
    relleno_cab = PatternFill("solid", fgColor=MARCA)

    def tabla(ws, fila, encabezados, filas, anchos):
        for j, h in enumerate(encabezados, 1):
            c = ws.cell(row=fila, column=j, value=h)
            c.font, c.fill, c.border = cab, relleno_cab, borde
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for i, datos in enumerate(filas, fila + 1):
            for j, v in enumerate(datos, 1):
                c = ws.cell(row=i, column=j, value=v)
                c.border = borde
                c.alignment = Alignment(vertical="top", wrap_text=True)
        for j, a in enumerate(anchos, 1):
            ws.column_dimensions[get_column_letter(j)].width = a
        ws.freeze_panes = ws.cell(row=fila + 1, column=1)

    # Hoja 1: resumen
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = f"GUIOS EVAL · Informe {ev['codigo']}"
    ws["A1"].font = Font(bold=True, size=16, color=MARCA)
    datos = [("Organización", ev["org_nombre"]), ("Software", f"{ev['sw_nombre']} {ev['sw_version'] or ''}".strip()),
             ("Licencia", ev["sw_licencia"] or ""), ("Estado", ev["estado"]), ("Decisión", ev["decision"]),
             ("Índice de adopción (0-100)", res["puntaje"])]
    for d, v in res["dimensiones"].items():
        datos.append((f"Índice {d}", v))
    rec = res["recomendacion"]
    if rec:
        datos += [("Recomendación", f"{rec['tipo']}: {rec['titulo']}"), ("Explicación", rec["texto"])]
    for k in ("Fortaleza", "Oportunidad", "Debilidad", "Amenaza"):
        datos.append((k + "s" if k != "Oportunidad" else "Oportunidades", res["conteo"][k]))
    for i, (k, v) in enumerate(datos, 3):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        c = ws.cell(row=i, column=2, value=v)
        c.alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
        if k == "Recomendación" and rec:
            c.fill = PatternFill("solid", fgColor=COLOR_REC[rec["tipo"]])
            c.font = Font(bold=True)
        if k.startswith(("Fortaleza", "Oportunidad", "Debilidad", "Amenaza")):
            clave = k.rstrip("s").replace("Oportunidade", "Oportunidad")
            ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor=COLOR_FODA[clave])
    fila = len(datos) + 4
    if resumen and resumen.get("resumen"):
        ws.cell(row=fila, column=1, value="Resumen ejecutivo").font = Font(bold=True)
        ws.cell(row=fila, column=1).alignment = Alignment(vertical="top")
        c = ws.cell(row=fila, column=2, value=resumen["resumen"])
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[fila].height = 150
        ws.cell(row=fila + 1, column=1, value="Fuente del resumen")
        ws.cell(row=fila + 1, column=2, value=f"{resumen.get('fuente', '')} {resumen.get('modelo', '')}".strip())
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 95

    # Hoja 2: factores
    ws = wb.create_sheet("Factores")
    filas = [[f["dimension"], f["nombre"], f["is_valor"], f.get("il"), f.get("citas"), f["id"], f["ir"],
              "Sí" if f["relevante"] else "No", f["alcance"], _num(f["pm"]), f["foda"] or ""] for f in res["factores"]]
    tabla(ws, 1, ["Dimensión", "Factor", "IS", "IL", "Citas", "ID", "IR", "Relevante", "Alcance", "PM", "FODA"],
          filas, [16, 38, 6, 6, 8, 6, 6, 10, 10, 8, 14])
    for i, f in enumerate(res["factores"], 2):
        if f["foda"]:
            for j in range(1, 12):
                ws.cell(row=i, column=j).fill = PatternFill("solid", fgColor=COLOR_FODA[f["foda"]])
        elif not f["relevante"]:
            for j in range(1, 12):
                ws.cell(row=i, column=j).font = Font(color="94A3B8")

    # Hoja 3: matriz FODA
    ws = wb.create_sheet("Matriz FODA")
    cuad = {k: [f"{f['nombre']} (PM {f['pm']:.2f})" for f in res["factores"] if f["foda"] == k]
            for k in COLOR_FODA}
    ws["B1"], ws["C1"] = "Positivo (PM ≥ umbral)", "Negativo (PM < umbral)"
    ws["A2"], ws["A3"] = "Interno", "Externo"
    for celda, k in (("B2", "Fortaleza"), ("C2", "Debilidad"), ("B3", "Oportunidad"), ("C3", "Amenaza")):
        ws[celda] = k.upper() + "S\n" + "\n".join(cuad[k]) if cuad[k] else k.upper() + "S\n(ninguno)"
        ws[celda].fill = PatternFill("solid", fgColor=COLOR_FODA[k])
        ws[celda].alignment = Alignment(wrap_text=True, vertical="top")
        ws[celda].border = borde
    for c in ("A2", "A3", "B1", "C1"):
        ws[c].font, ws[c].fill = cab, relleno_cab
        ws[c].alignment = Alignment(horizontal="center", vertical="center")
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width, ws.column_dimensions["C"].width = 12, 55, 55
    ws.row_dimensions[2].height = ws.row_dimensions[3].height = 200

    # Hoja 4: subfactores
    ws = wb.create_sheet("Subfactores")
    respuestas = respuestas or {}
    filas = []
    for f in res["factores"]:
        if not f["relevante"]:
            continue
        for s in f["subfactores"]:
            r = respuestas.get(s.get("key"), {})
            nivel = engine.NIVELES_PS.get(int(s["ps"] + 0.5)) if s["ps"] else "Sin evaluar"
            filas.append([f["nombre"], s["texto"], _num(s["ps"]), nivel, s["n"],
                          "IA · " + r["origen"][3:] if (r.get("origen") or "").startswith("ia:") else "Manual",
                          r.get("comentario") or "", r.get("evidencia") or ""])
    tabla(ws, 1, ["Factor", "Subfactor", "PS", "Nivel", "Respuestas", "Origen", "Comentario", "Evidencia"],
          filas, [26, 60, 6, 30, 11, 12, 50, 35])
    colores_ps = {1: "FEE2E2", 2: "F1F5F9", 3: "FEF3C7", 4: "DCFCE7"}
    for i, x in enumerate(filas, 2):
        if x[2] != "":
            ws.cell(row=i, column=3).fill = PatternFill("solid", fgColor=colores_ps[int(x[2] + 0.5)])

    # Hoja 5: plan y sensibilidad
    if (resumen and resumen.get("plan")) or sens:
        ws = wb.create_sheet("Plan y sensibilidad")
        fila = 1
        if resumen and resumen.get("plan"):
            tabla(ws, 1, ["Factor", "Acción", "Entregable", "Plazo", "Responsable"],
                  [[p["factor"], p["accion"], p["entregable"], p["plazo"], p["responsable"]] for p in resumen["plan"]],
                  [26, 55, 45, 12, 22])
            fila = len(resumen["plan"]) + 3
        if sens:
            ws.cell(row=fila, column=1, value="Análisis de sensibilidad").font = Font(bold=True, size=12)
            lineas = [f"Recomendación actual: {sens['base']}"]
            if sens["ruta_criticos_resultado"] and sens["ruta_criticos_resultado"] != sens["base"]:
                lineas.append(f"Corrigiendo {sens['ruta_criticos_total']} subfactores de factores críticos pasa a "
                              f"{sens['ruta_criticos_resultado']}")
            if sens["ruta_resultado"] != sens["base"]:
                lineas.append(f"Corrigiendo {sens['ruta_total']} subfactores de todos los factores negativos pasa a "
                              f"{sens['ruta_resultado']}")
            for x in sens["mejoras"]:
                lineas.append(f"Mejora: {x['factor']} · {x['subfactor']} de {x['desde']:.1f} a {x['hasta']} -> {x['nueva']}")
            for x in sens["riesgos"]:
                lineas.append(f"Riesgo: {x['factor']} · {x['subfactor']} de {x['desde']:.1f} a {x['hasta']} -> {x['nueva']}")
            for i, l in enumerate(lineas, fila + 1):
                ws.cell(row=i, column=1, value=l)
    # Hoja 6: matriz de riesgos
    if riesgos and riesgos["riesgos"]:
        ws = wb.create_sheet("Matriz de riesgos")
        tabla(ws, 1, ["Riesgo (factor)", "Tipo", "PM", "IR", "Probabilidad", "Impacto", "P x I", "Nivel", "Respuesta",
                      "Acción", "Evidencia (subfactores bajo el umbral)"],
              [[r["factor"], r["foda"], round(r["pm"], 2), r["ir"], r["probabilidad"], r["impacto"], r["valor"],
                r["nivel"], r["respuesta"], r["accion"], "; ".join(r["evidencia"])] for r in riesgos["riesgos"]],
              [24, 12, 7, 6, 12, 9, 7, 9, 20, 50, 60])
        colores_n = {"Alto": "FECACA", "Medio": "FDE68A", "Bajo": "BBF7D0"}
        for i, r in enumerate(riesgos["riesgos"], 2):
            ws.cell(row=i, column=8).fill = PatternFill("solid", fgColor=colores_n[r["nivel"]])
        base = len(riesgos["riesgos"]) + 4
        ws.cell(row=base, column=1, value="Mapa de calor (probabilidad x impacto)").font = Font(bold=True, size=12)
        for j, imp in enumerate(range(1, 6), 2):
            ws.cell(row=base + 1, column=j, value=f"I={imp}").font = Font(bold=True)
        for k, prob in enumerate(range(5, 0, -1)):
            fila_m = base + 2 + k
            ws.cell(row=fila_m, column=1, value=f"P={prob}").font = Font(bold=True)
            for j, imp in enumerate(range(1, 6), 2):
                v = prob * imp
                c = ws.cell(row=fila_m, column=j, value=", ".join(riesgos["celdas"].get((prob, imp), [])) or None)
                c.fill = PatternFill("solid", fgColor="FECACA" if v >= 15 else "FDE68A" if v >= 8 else "DCFCE7")
                c.border = borde
                c.alignment = Alignment(wrap_text=True, vertical="center")
            ws.row_dimensions[fila_m].height = 30
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- PDF
class _PDF(FPDF):
    codigo = ""
    folio = ""

    def header(self):
        self.set_fill_color(30, 42, 68)
        self.rect(0, 0, 216, 16, "F")
        self.set_xy(12, 4)
        self.set_text_color(255, 255, 255)
        self.set_font("dv", "B", 13)
        self.cell(100, 8, "GUIOS EVAL")
        self.set_font("dv", "", 9)
        self.set_xy(110, 5)
        self.cell(94, 6, f"Informe de evaluación {self.codigo}", align="R")
        self.set_text_color(15, 23, 42)
        self.set_y(22)

    def footer(self):
        self.set_y(-12)
        self.set_font("dv", "", 8)
        self.set_text_color(100, 116, 139)
        pie = f"Método GUIOS (Rea Sánchez, 2022) · Página {self.page_no()}/{{nb}}"
        if self.folio:
            pie += f" · Folio {self.folio}"
        self.cell(0, 6, pie, align="C")


def pdf(ev, res, sens=None, resumen=None, umbral=3.0, riesgos=None, sello=None):
    p = _PDF(format="Letter")
    p.codigo = ev["codigo"]
    if sello:
        p.folio = sello["folio"]
        p.set_subject(f"Informe GUIOS EVAL {ev['codigo']} - folio {sello['folio']}")
        p.set_keywords(sello["folio"])
    p.add_font("dv", "", os.path.join(BASE, "static", "fonts", "DejaVuSans.ttf"))
    p.add_font("dv", "B", os.path.join(BASE, "static", "fonts", "DejaVuSans-Bold.ttf"))
    p.alias_nb_pages()
    p.set_auto_page_break(True, 16)
    p.set_margins(14, 20, 14)
    p.add_page()
    W = p.w - 28

    def titulo(t):
        p.ln(2)
        p.set_font("dv", "B", 12)
        p.set_text_color(30, 42, 68)
        p.cell(0, 8, t, new_x="LMARGIN", new_y="NEXT")
        p.set_text_color(15, 23, 42)

    def texto(t, tam=9.5, estilo=""):
        p.set_font("dv", estilo, tam)
        p.multi_cell(W, 5, t, new_x="LMARGIN", new_y="NEXT")

    p.set_font("dv", "", 9.5)
    filas = [("Organización", ev["org_nombre"]), ("Software", f"{ev['sw_nombre']} {ev['sw_version'] or ''}"),
             ("Licencia / proveedor", f"{ev['sw_licencia'] or '-'} / {ev['sw_proveedor'] or '-'}"),
             ("Estado / decisión", f"{ev['estado']} / {ev['decision']}"),
             ("Índice de adopción", f"{res['puntaje']}/100 · " + ", ".join(f"{d} {v}" for d, v in res['dimensiones'].items()))]
    for k, v in filas:
        p.set_font("dv", "B", 9.5)
        p.cell(45, 6, k)
        p.set_font("dv", "", 9.5)
        p.multi_cell(W - 45, 6, str(v), new_x="LMARGIN", new_y="NEXT")

    rec = res["recomendacion"]
    if rec:
        colores = {"A": (220, 252, 231), "B": (254, 243, 199), "C": (254, 226, 226)}
        p.ln(2)
        p.set_fill_color(*colores[rec["tipo"]])
        p.set_font("dv", "B", 12)
        p.multi_cell(W, 8, f"Recomendación {rec['tipo']}: {rec['titulo']}", fill=True, new_x="LMARGIN", new_y="NEXT")
        p.set_font("dv", "", 9.5)
        p.multi_cell(W, 5, rec["texto"], fill=True, new_x="LMARGIN", new_y="NEXT")

    if resumen and resumen.get("resumen"):
        titulo("Resumen ejecutivo")
        texto(resumen["resumen"])
        p.set_font("dv", "", 7.5)
        p.set_text_color(100, 116, 139)
        p.cell(0, 5, f"Redactado con {resumen.get('fuente', '')} {resumen.get('modelo', '')}; la recomendación la "
                     "calcula el motor GUIOS.", new_x="LMARGIN", new_y="NEXT")
        p.set_text_color(15, 23, 42)

    titulo("Matriz FODA")
    cuad = {k: [f"{f['nombre']} ({f['pm']:.2f})" for f in res["factores"] if f["foda"] == k] for k in COLOR_FODA}
    rgb = {k: tuple(int(v[i:i + 2], 16) for i in (0, 2, 4)) for k, v in COLOR_FODA.items()}
    x0, y0 = p.get_x(), p.get_y()
    alto = max(6 + 5 * max(len(cuad[a]), len(cuad[b])) for a, b in
               (("Fortaleza", "Debilidad"), ("Oportunidad", "Amenaza"))) + 2
    for fila, (a, b) in enumerate((("Fortaleza", "Debilidad"), ("Oportunidad", "Amenaza"))):
        for col, k in enumerate((a, b)):
            x, y = x0 + col * W / 2, y0 + fila * alto
            p.set_fill_color(*rgb[k])
            p.rect(x, y, W / 2 - 1, alto - 1, "F")
            p.set_xy(x + 2, y + 1)
            p.set_font("dv", "B", 9)
            p.cell(W / 2 - 4, 5, f"{k}s ({len(cuad[k])})".replace("Oportunidads", "Oportunidades"))
            p.set_font("dv", "", 8.5)
            for i, t in enumerate(cuad[k]):
                p.set_xy(x + 2, y + 6 + i * 5)
                p.cell(W / 2 - 4, 5, "• " + t)
    p.set_xy(x0, y0 + 2 * alto + 2)

    titulo("Factores evaluados")
    cols = [("Factor", 62), ("Dimensión", 30), ("IS", 10), ("ID", 10), ("IR", 22), ("PM", 14), ("FODA", W - 148)]
    p.set_font("dv", "B", 8.5)
    p.set_fill_color(30, 42, 68)
    p.set_text_color(255, 255, 255)
    for t, a in cols:
        p.cell(a, 6, t, border=1, fill=True)
    p.ln()
    p.set_text_color(15, 23, 42)
    p.set_font("dv", "", 8.5)
    for f in res["factores"]:
        if not f["relevante"]:
            continue
        p.set_fill_color(*rgb.get(f["foda"], (255, 255, 255)))
        nombre = f["nombre"].replace("Centralidad de la tecnología de la información", "Centralidad de la TI")
        vals = [nombre[:42], f["dimension"], str(f["is_valor"]), str(f["id"]), engine.NIVELES[f["ir"]],
                f"{f['pm']:.2f}" if f["pm"] is not None else "-", f["foda"] or "Sin evaluar"]
        for (t, a), v in zip(cols, vals):
            p.cell(a, 5.5, v, border=1, fill=bool(f["foda"]))
        p.ln()

    plan = (resumen or {}).get("plan") or []
    if not plan and rec:
        plan = [{"factor": c["factor"], "accion": c["accion"], "entregable": "", "plazo": "", "responsable": ""}
                for c in rec["causas"]]
    if plan:
        titulo("Plan de acción")
        for x in plan:
            p.set_font("dv", "B", 9)
            p.multi_cell(W, 5, x["factor"], new_x="LMARGIN", new_y="NEXT")
            p.set_font("dv", "", 8.8)
            extra = " · ".join(v for v in (x.get("entregable") and "Entregable: " + x["entregable"],
                                            x.get("plazo") and "Plazo: " + x["plazo"],
                                            x.get("responsable") and "Responsable: " + x["responsable"]) if v)
            p.multi_cell(W, 4.6, x["accion"] + (". " + extra if extra else ""), new_x="LMARGIN", new_y="NEXT")
            p.ln(1)

    if sens and sens["base"] != "A":
        titulo("Análisis de sensibilidad")
        lineas = []
        if sens["ruta_criticos_resultado"] and sens["ruta_criticos_resultado"] != sens["base"]:
            lineas.append(f"Llevando a «Cumple» {sens['ruta_criticos_total']} subfactores de los factores críticos, la "
                          f"recomendación pasa de {sens['base']} a {sens['ruta_criticos_resultado']}.")
        if sens["ruta_resultado"] != sens["base"]:
            lineas.append(f"Llevando a «Cumple» {sens['ruta_total']} subfactores de todos los factores negativos, pasa a "
                          f"{sens['ruta_resultado']}.")
        for x in sens["mejoras"][:4]:
            lineas.append(f"Una sola respuesta: {x['factor']}, «{x['subfactor']}» de {x['desde']:.1f} a {x['hasta']} "
                          f"cambia la recomendación a {x['nueva']}.")
        texto("\n".join(lineas) or "Ningún cambio individual modifica la recomendación.")

    if riesgos and riesgos["riesgos"]:
        titulo("Matriz de riesgos de la adopción")
        colores_n = {"Alto": (254, 226, 226), "Medio": (254, 243, 199), "Bajo": (220, 252, 231)}
        cols = [("Riesgo (factor)", 46), ("P", 7), ("I", 7), ("Nivel", 21), ("Respuesta", 33), ("Acción", W - 114)]

        def cabe(texto, ancho):
            if p.get_string_width(texto) <= ancho - 2:
                return texto
            while texto and p.get_string_width(texto + "...") > ancho - 2:
                texto = texto[:-1]
            return texto.rstrip() + "..."
        p.set_font("dv", "B", 8.5)
        p.set_fill_color(30, 42, 68)
        p.set_text_color(255, 255, 255)
        for t, a in cols:
            p.cell(a, 6, t, border=1, fill=True)
        p.ln()
        p.set_text_color(15, 23, 42)
        p.set_font("dv", "", 8)
        for r in riesgos["riesgos"]:
            p.set_fill_color(*colores_n[r["nivel"]])
            for (t, a), v in zip(cols, [r["factor"], str(r["probabilidad"]), str(r["impacto"]),
                                        f"{r['nivel']} ({r['valor']})", r["respuesta"], r["accion"]]):
                p.cell(a, 5.5, cabe(v, a), border=1, fill=t == "Nivel")
            p.ln()
        p.set_font("dv", "", 7.5)
        p.cell(0, 5, "P = probabilidad según la ponderación media; I = impacto según la importancia relativa; "
                     "nivel = P × I (alto ≥ 15, medio ≥ 8).", new_x="LMARGIN", new_y="NEXT")

    if sello:
        if p.get_y() > p.h - 60:
            p.add_page()
        p.ln(3)
        y0 = p.get_y()
        p.set_draw_color(203, 213, 225)
        p.rect(p.l_margin, y0, W, 38)
        p.image(sello["qr"], x=p.l_margin + 3, y=y0 + 3, w=32, h=32)
        p.set_xy(p.l_margin + 40, y0 + 4)
        p.set_font("dv", "B", 10)
        p.cell(0, 5, "Sello de integridad", new_x="LMARGIN", new_y="NEXT")
        p.set_font("dv", "", 8.5)
        for linea in (f"Folio: {sello['folio']}    Emitido: {sello['fecha']}",
                      f"Huella SHA-256 de los datos: {sello['hash_datos'][:32]}",
                      f"{sello['hash_datos'][32:]}",
                      "Para comprobar que este informe es auténtico y no fue modificado, abre GUIOS EVAL →",
                      "«Verificar un informe» y sube este PDF o escribe el folio."):
            p.set_x(p.l_margin + 40)
            p.cell(0, 4.6, linea, new_x="LMARGIN", new_y="NEXT")
        p.set_y(y0 + 40)

    p.ln(2)
    p.set_font("dv", "", 7.5)
    p.set_text_color(100, 116, 139)
    p.multi_cell(W, 4, f"IR según la Figura 5.10 de la tesis; PM como media de las ponderaciones de los subfactores; "
                       f"FODA con umbral {umbral:.1f}; IS calculada con la importancia del experto y de la literatura "
                       "(Ecuaciones 5.1 y 5.2).", new_x="LMARGIN", new_y="NEXT")
    return bytes(p.output())
