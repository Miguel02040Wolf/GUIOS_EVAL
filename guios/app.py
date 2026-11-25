"""
GUIOS EVAL - Sistema web para evaluar la adopción de software en organizaciones.
Versión nueva de GUIOS PRO FLOSS (Rea, 2022), desarrollada por el Grupo 5 de
Procesos y Calidad de Software, UNEMI, 2026.

Ejecutar:  iniciar.bat  (o: python -m guios)  y abrir http://127.0.0.1:5000
"""
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template, send_from_directory,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from guios import base_datos as db
from guios import correo as mail
from guios import exportar, ia, integridad, literatura
from guios import motor as engine

app = Flask(__name__)
app.secret_key = os.environ.get("GUIOS_SECRET", "guios-eval-unemi-2026")
app.permanent_session_lifetime = timedelta(minutes=30)
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # fotos de perfil

ESTADOS_EVAL = {"borrador": "Borrador", "en_curso": "En curso", "en_revision": "En revisión",
                "cerrada": "Cerrada", "cancelada": "Cancelada"}
DECISIONES = {"no_emitida": "No emitida", "aprobada": "Aprobada", "condicionada": "Condicionada",
              "devuelta": "Devuelta", "rechazada": "Rechazada"}
DIMENSIONES = ["Tecnológica", "Organizacional", "Económica"]


# ----------------------------------------------------------------- utilidades
def get_db():
    if "con" not in g:
        g.con = db.conectar()
    return g.con


@app.teardown_appcontext
def cerrar_db(exc):
    con = g.pop("con", None)
    if con is not None:
        con.close()


@app.before_request
def cargar_usuario():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = get_db().execute("SELECT * FROM usuarios WHERE id=? AND activo=1", (uid,)).fetchone()
        session.permanent = True


LIBRES = {"static", "salir", "login", "registro", "activar", "recuperar", "recuperar_codigo", "verificar_informe",
          "favicon", "foto_usuario"}


@app.before_request
def proteger_cuenta():
    """Cuentas pendientes de aprobación o con contraseña temporal solo ven su pantalla correspondiente."""
    if not g.user or request.endpoint in LIBRES:
        return None
    if g.user["estado"] == "pendiente_aprobacion" and request.endpoint not in ("pendiente", "perfil_foto"):
        return redirect(url_for("pendiente"))
    if g.user["estado"] == "activo" and g.user["cambiar_clave"] and request.endpoint != "cambiar_clave":
        return redirect(url_for("cambiar_clave"))
    return None


def login_requerido(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                return redirect(url_for("login", next=request.path))
            if roles and g.user["rol"] not in roles and g.user["rol"] != "admin":
                flash("Tu rol no tiene permiso para esta acción.", "error")
                return redirect(url_for("panel"))
            return fn(*a, **kw)
        return wrapper
    return deco


@app.context_processor
def globales():
    return {"ROLES": db.ROLES, "NOMBRE_ROL": dict(db.ROLES, sin_rol="Sin rol (pendiente)"),
            "ESTADOS": ESTADOS_EVAL, "DECISIONES": DECISIONES,
            "NIVELES": engine.NIVELES, "NIVELES_PS": engine.NIVELES_PS, "DIMENSIONES": DIMENSIONES}


@app.template_filter("num")
def fmt_num(v, d=2):
    return "-" if v is None else f"{v:.{d}f}".replace(".", ",")


def umbral():
    return float(db.config(get_db(), "umbral_foda", "3"))


def obtener_eval(eid):
    ev = get_db().execute("SELECT e.*, u.nombre AS lider FROM evaluaciones e JOIN usuarios u "
                          "ON u.id=e.lider_id WHERE e.id=?", (eid,)).fetchone()
    if ev is None:
        abort(404)
    return ev


def participantes(eid):
    return get_db().execute("SELECT u.* FROM participantes p JOIN usuarios u ON u.id=p.usuario_id "
                            "WHERE p.evaluacion_id=? ORDER BY u.nombre", (eid,)).fetchall()


def es_participante(eid, uid):
    return get_db().execute("SELECT 1 FROM participantes WHERE evaluacion_id=? AND usuario_id=?",
                            (eid, uid)).fetchone() is not None


def editable(ev):
    return ev["estado"] in ("borrador", "en_curso")


def puede_votar(ev):
    return editable(ev) and g.user is not None and es_participante(ev["id"], g.user["id"])


def construir_entrada(ev):
    """Arma la entrada del motor a partir del snapshot y las respuestas de todos los participantes."""
    con = get_db()
    snap = json.loads(ev["snapshot"])
    pids = [p["id"] for p in participantes(ev["id"])]
    votos, resp = {}, {}
    for v in con.execute("SELECT * FROM votos_factor WHERE evaluacion_id=?", (ev["id"],)):
        if v["usuario_id"] in pids:
            votos.setdefault(v["factor_key"], []).append(v)
    for r in con.execute("SELECT * FROM respuestas WHERE evaluacion_id=?", (ev["id"],)):
        if r["usuario_id"] in pids:
            resp.setdefault(r["sub_key"], []).append(r)
    factores = []
    for f in snap:
        vf = votos.get(f["key"], [])
        alcances = [v["alcance"] for v in vf if v["alcance"]]
        elegido = None
        if alcances:
            elegido = max(set(alcances), key=lambda a, al=alcances: (al.count(a), a == "Interno"))
        factores.append({
            "key": f["key"], "nombre": f["nombre"], "dimension": f["dimension"],
            "is_valor": f["is_valor"], "alcance": f["alcance"], "descripcion": f.get("descripcion"),
            "ie": f.get("ie"), "il": f.get("il"), "citas": f.get("citas"),
            "ids": [v["id_valor"] for v in vf if v["id_valor"] is not None],
            "alcance_elegido": elegido,
            "subfactores": [{"key": s["key"], "texto": s["texto"],
                             "valores": [r["valor"] for r in resp.get(s["key"], []) if r["valor"] is not None]}
                            for s in f["subfactores"]],
        })
    return factores


def evaluar(ev):
    entrada = construir_entrada(ev)
    res = engine.calcular(entrada, umbral())
    for f_in, f_out in zip(entrada, res["factores"]):
        f_out["key"] = f_in["key"]
        f_out["descripcion"] = f_in["descripcion"]
        for k in ("ie", "il", "citas"):
            f_out[k] = f_in.get(k)
        f_out["explicacion"] = engine.explicar(f_out, umbral())
        for s_in, s_out in zip(f_in["subfactores"], f_out["subfactores"]):
            s_out["key"] = s_in["key"]
    return res


# ------------------------------------------------------------------- sesión
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("panel"))
    error = None
    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        u = get_db().execute("SELECT * FROM usuarios WHERE correo=? AND activo=1", (correo,)).fetchone()
        if u and check_password_hash(u["clave"], request.form.get("clave", "")):
            if u["estado"] == "pendiente_correo":
                flash("Primero verifica tu correo con el código que te enviamos.", "warn")
                return redirect(url_for("activar", correo=correo))
            if u["estado"] == "rechazado":
                return render_template("login.html", correo=correo,
                                       error="Tu solicitud de cuenta fue rechazada"
                                             + (f": {u['motivo_rechazo']}" if u["motivo_rechazo"] else "."))
            session.clear()
            session["uid"] = u["id"]
            db.auditar(get_db(), u["id"], "sesion.iniciar", "Inicio de sesión")
            get_db().commit()
            return redirect(request.args.get("next") or url_for("panel"))
        error = "Correo o contraseña incorrectos."
    return render_template("login.html", error=error, correo=request.form.get("correo", ""))


@app.route("/salir")
def salir():
    if g.user:
        db.auditar(get_db(), g.user["id"], "sesion.cerrar", "Cierre de sesión")
        get_db().commit()
    session.clear()
    return redirect(url_for("login"))


# -------------------------------------------------------------------- panel
@app.route("/panel")
@login_requerido()
def panel():
    con = get_db()
    cat = con.execute("SELECT * FROM catalogos WHERE estado='publicado' ORDER BY version DESC").fetchone()
    nf = con.execute("SELECT COUNT(*) FROM factores WHERE catalogo_id=? AND activo=1", (cat["id"],)).fetchone()[0] if cat else 0
    ns = con.execute("SELECT COUNT(*) FROM subfactores s JOIN factores f ON f.id=s.factor_id "
                     "WHERE f.catalogo_id=? AND s.activo=1 AND f.activo=1", (cat["id"],)).fetchone()[0] if cat else 0
    stats = {e: con.execute("SELECT COUNT(*) FROM evaluaciones WHERE estado=?", (e,)).fetchone()[0]
             for e in ESTADOS_EVAL}
    mias = con.execute("SELECT e.* FROM evaluaciones e JOIN participantes p ON p.evaluacion_id=e.id "
                       "WHERE p.usuario_id=? AND e.estado IN ('borrador','en_curso') ORDER BY e.id DESC",
                       (g.user["id"],)).fetchall()
    progreso = []
    for ev in mias[:3]:
        r = evaluar(ev)
        total = sum(f["total_sub"] for f in r["factores"] if f["relevante"])
        hechos = sum(f["evaluados"] for f in r["factores"] if f["relevante"])
        progreso.append({"ev": ev, "relevantes": r["relevantes"], "total": total, "hechos": hechos,
                         "sin_id": r["sin_id"]})
    recientes = con.execute("SELECT a.*, u.nombre FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id "
                            "ORDER BY a.id DESC LIMIT 8").fetchall()
    cerradas = con.execute("SELECT * FROM evaluaciones WHERE estado='cerrada' ORDER BY cerrado DESC LIMIT 5").fetchall()
    return render_template("panel.html", cat=cat, nf=nf, ns=ns, stats=stats, progreso=progreso,
                           recientes=recientes, cerradas=[(c, json.loads(c["resultado"] or "{}")) for c in cerradas])


# ------------------------------------------------------- historial / lista
@app.route("/evaluaciones")
@login_requerido()
def evaluaciones():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "")
    sql = "SELECT e.*, u.nombre AS lider FROM evaluaciones e JOIN usuarios u ON u.id=e.lider_id WHERE 1=1"
    args = []
    if q:
        sql += " AND (e.codigo LIKE ? OR e.org_nombre LIKE ? OR e.sw_nombre LIKE ?)"
        args += [f"%{q}%"] * 3
    if estado:
        sql += " AND e.estado=?"
        args.append(estado)
    filas = get_db().execute(sql + " ORDER BY e.id DESC", args).fetchall()
    datos = [(e, json.loads(e["resultado"]) if e["resultado"] else None) for e in filas]
    return render_template("evaluaciones.html", filas=datos, q=q, estado=estado)


def siguiente_codigo():
    n = get_db().execute("SELECT COALESCE(MAX(id),0)+1 FROM evaluaciones").fetchone()[0]
    return f"EV-{n:04d}"


@app.route("/evaluaciones/nueva", methods=["GET", "POST"])
@login_requerido("lider")
def nueva_evaluacion():
    con = get_db()
    catalogos = con.execute("SELECT * FROM catalogos WHERE estado='publicado' ORDER BY version DESC").fetchall()
    if request.method == "POST":
        f = request.form
        if not f.get("org_nombre") or not f.get("sw_nombre") or not f.get("catalogo_id"):
            flash("Completa los campos obligatorios: organización, software y catálogo.", "error")
            return render_template("paso1.html", ev=None, catalogos=catalogos, form=f)
        cat_id = int(f["catalogo_id"])
        snap = db.snapshot_catalogo(con, cat_id)
        cur = con.execute(
            "INSERT INTO evaluaciones (codigo, org_nombre, org_ruc, org_sector, org_correo, sw_nombre, "
            "sw_version, sw_tipo, sw_licencia, sw_proveedor, sw_descripcion, catalogo_id, snapshot, "
            "lider_id, creado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (siguiente_codigo(), f["org_nombre"], f.get("org_ruc"), f.get("org_sector"), f.get("org_correo"),
             f["sw_nombre"], f.get("sw_version"), f.get("sw_tipo"), f.get("sw_licencia"),
             f.get("sw_proveedor"), f.get("sw_descripcion"), cat_id, json.dumps(snap, ensure_ascii=False),
             g.user["id"], db.ahora()))
        eid = cur.lastrowid
        con.execute("INSERT INTO participantes VALUES (?,?)", (eid, g.user["id"]))
        db.auditar(con, g.user["id"], "evaluacion.crear", f"Evaluación de {f['sw_nombre']} para {f['org_nombre']}", eid)
        con.commit()
        flash("Evaluación creada. Agrega a los decisores que participarán y continúa con el paso 2.", "ok")
        return redirect(url_for("participantes_view", eid=eid))
    return render_template("paso1.html", ev=None, catalogos=catalogos, form={})


@app.route("/evaluaciones/<int:eid>/paso-1", methods=["GET", "POST"])
@login_requerido()
def paso1(eid):
    ev = obtener_eval(eid)
    con = get_db()
    catalogos = con.execute("SELECT * FROM catalogos WHERE id=?", (ev["catalogo_id"],)).fetchall()
    if request.method == "POST":
        if not (editable(ev) and (g.user["id"] == ev["lider_id"] or g.user["rol"] == "admin")):
            abort(403)
        f = request.form
        con.execute("UPDATE evaluaciones SET org_nombre=?, org_ruc=?, org_sector=?, org_correo=?, sw_nombre=?, "
                    "sw_version=?, sw_tipo=?, sw_licencia=?, sw_proveedor=?, sw_descripcion=? WHERE id=?",
                    (f["org_nombre"], f.get("org_ruc"), f.get("org_sector"), f.get("org_correo"), f["sw_nombre"],
                     f.get("sw_version"), f.get("sw_tipo"), f.get("sw_licencia"), f.get("sw_proveedor"),
                     f.get("sw_descripcion"), eid))
        db.auditar(con, g.user["id"], "evaluacion.editar", "Datos generales actualizados", eid)
        con.commit()
        flash("Datos generales guardados.", "ok")
        return redirect(url_for("paso2", eid=eid))
    return render_template("paso1.html", ev=ev, catalogos=catalogos, form=ev)


@app.route("/evaluaciones/<int:eid>/participantes", methods=["GET", "POST"])
@login_requerido()
def participantes_view(eid):
    ev = obtener_eval(eid)
    con = get_db()
    gestiona = editable(ev) and (g.user["id"] == ev["lider_id"] or g.user["rol"] == "admin")
    if request.method == "POST":
        if not gestiona:
            abort(403)
        uid = int(request.form["usuario_id"])
        if request.form.get("accion") == "quitar":
            if uid != ev["lider_id"]:
                con.execute("DELETE FROM participantes WHERE evaluacion_id=? AND usuario_id=?", (eid, uid))
                db.auditar(con, g.user["id"], "participante.quitar", f"Usuario {uid} retirado", eid)
        else:
            con.execute("INSERT OR IGNORE INTO participantes VALUES (?,?)", (eid, uid))
            u = con.execute("SELECT nombre FROM usuarios WHERE id=?", (uid,)).fetchone()
            db.auditar(con, g.user["id"], "participante.agregar", f"{u['nombre']} agregado como decisor", eid)
        con.commit()
        return redirect(url_for("participantes_view", eid=eid))
    parts = participantes(eid)
    ids = {p["id"] for p in parts}
    candidatos = [u for u in con.execute("SELECT * FROM usuarios WHERE activo=1 AND rol IN "
                                          "('lider','evaluador','revisor') ORDER BY nombre") if u["id"] not in ids]
    avance = []
    snap = json.loads(ev["snapshot"])
    nsub = sum(len(f["subfactores"]) for f in snap)
    for p in parts:
        nv = con.execute("SELECT COUNT(*) FROM votos_factor WHERE evaluacion_id=? AND usuario_id=? AND id_valor IS NOT NULL",
                         (eid, p["id"])).fetchone()[0]
        nr = con.execute("SELECT COUNT(*) FROM respuestas WHERE evaluacion_id=? AND usuario_id=? AND valor IS NOT NULL",
                         (eid, p["id"])).fetchone()[0]
        avance.append({"u": p, "votos": nv, "resp": nr})
    return render_template("participantes.html", ev=ev, avance=avance, candidatos=candidatos,
                           gestiona=gestiona, nfac=len(snap), nsub=nsub)


@app.route("/evaluaciones/<int:eid>/paso-2")
@login_requerido()
def paso2(eid):
    ev = obtener_eval(eid)
    res = evaluar(ev)
    mios = {v["factor_key"]: v for v in get_db().execute(
        "SELECT * FROM votos_factor WHERE evaluacion_id=? AND usuario_id=?", (eid, g.user["id"]))}
    nparts = len(participantes(eid))
    return render_template("paso2.html", ev=ev, res=res, mios=mios, puede=puede_votar(ev), nparts=nparts)


@app.route("/evaluaciones/<int:eid>/paso-3")
@login_requerido()
def paso3(eid):
    ev = obtener_eval(eid)
    res = evaluar(ev)
    relevantes = [f for f in res["factores"] if f["relevante"]]
    sel = request.args.get("f") or (relevantes[0]["key"] if relevantes else None)
    actual = next((f for f in relevantes if f["key"] == sel), None)
    mias = {r["sub_key"]: r for r in get_db().execute(
        "SELECT * FROM respuestas WHERE evaluacion_id=? AND usuario_id=?", (eid, g.user["id"]))}
    total = sum(f["total_sub"] for f in relevantes)
    mis_hechas = sum(1 for f in relevantes for s in f["subfactores"]
                     if s["key"] in mias and mias[s["key"]]["valor"] is not None)
    return render_template("paso3.html", ev=ev, res=res, relevantes=relevantes, fac=actual, mias=mias,
                           puede=puede_votar(ev), total=total, mis_hechas=mis_hechas,
                           ia_activa=ia_modo() != "desactivado",
                           nparts=len(participantes(eid)))


@app.route("/evaluaciones/<int:eid>/paso-4")
@login_requerido()
def paso4(eid):
    ev = obtener_eval(eid)
    res = evaluar(ev)
    revisor = con_rol("revisor")
    sens = engine.sensibilidad(construir_entrada(ev), umbral()) if res["recomendacion"] else None
    resumen = json.loads(ev["resumen_ia"]) if ev["resumen_ia"] else None
    riesgos = engine.matriz_riesgos(res, umbral()) if res["recomendacion"] else None
    return render_template("paso4.html", ev=ev, res=res, umbral=umbral(), es_revisor=revisor, sens=sens, riesgos=riesgos,
                           resumen=resumen, ia_activa=ia_modo() != "desactivado",
                           es_lider=(g.user["id"] == ev["lider_id"] or g.user["rol"] == "admin"),
                           decisor=nombre_usuario(ev["decision_por"]))


def con_rol(*roles):
    return g.user["rol"] in roles or g.user["rol"] == "admin"


def nombre_usuario(uid):
    if not uid:
        return None
    r = get_db().execute("SELECT nombre FROM usuarios WHERE id=?", (uid,)).fetchone()
    return r["nombre"] if r else None


# ------------------------------------------------------------ API autosave
@app.post("/api/evaluaciones/<int:eid>/voto")
@login_requerido()
def api_voto(eid):
    ev = obtener_eval(eid)
    if not puede_votar(ev):
        return jsonify({"ok": False, "error": "No puedes editar esta evaluación."}), 403
    d = request.get_json(force=True)
    con = get_db()
    previo = con.execute("SELECT * FROM votos_factor WHERE evaluacion_id=? AND usuario_id=? AND factor_key=?",
                         (eid, g.user["id"], d["factor_key"])).fetchone()
    id_valor = d.get("id_valor", previo["id_valor"] if previo else None)
    alcance = d.get("alcance", previo["alcance"] if previo else None)
    con.execute("INSERT OR REPLACE INTO votos_factor VALUES (?,?,?,?,?)",
                (eid, g.user["id"], d["factor_key"], id_valor, alcance))
    if ev["estado"] == "borrador":
        con.execute("UPDATE evaluaciones SET estado='en_curso' WHERE id=?", (eid,))
    db.auditar(con, g.user["id"], "factor.importancia",
               f"{d.get('nombre', d['factor_key'])}: ID={id_valor}" + (f", alcance={alcance}" if alcance else ""), eid)
    con.commit()
    res = evaluar(obtener_eval(eid))
    f = next(x for x in res["factores"] if x["key"] == d["factor_key"])
    return jsonify({"ok": True, "ir": f["ir"], "ir_txt": engine.NIVELES.get(f["ir"], "-"),
                    "id": f["id"], "id_txt": engine.NIVELES.get(f["id"], "-"), "relevante": f["relevante"],
                    "alcance": f["alcance"], "relevantes": res["relevantes"], "sin_id": res["sin_id"],
                    "votos": len(f["ids"]), "desacuerdo": f["desacuerdo_id"]})


@app.post("/api/evaluaciones/<int:eid>/respuesta")
@login_requerido()
def api_respuesta(eid):
    ev = obtener_eval(eid)
    if not puede_votar(ev):
        return jsonify({"ok": False, "error": "No puedes editar esta evaluación."}), 403
    d = request.get_json(force=True)
    con = get_db()
    previo = con.execute("SELECT * FROM respuestas WHERE evaluacion_id=? AND usuario_id=? AND sub_key=?",
                         (eid, g.user["id"], d["sub_key"])).fetchone()
    valor = d["valor"] if "valor" in d else (previo["valor"] if previo else None)
    comentario = d["comentario"] if "comentario" in d else (previo["comentario"] if previo else None)
    evidencia = d["evidencia"] if "evidencia" in d else (previo["evidencia"] if previo else None)
    if "valor" in d:
        origen = d.get("origen") if str(d.get("origen") or "").startswith("ia:") else "manual"
    else:
        origen = previo["origen"] if previo else None
    con.execute("INSERT OR REPLACE INTO respuestas (evaluacion_id, usuario_id, sub_key, valor, comentario, evidencia, "
                "actualizado, origen) VALUES (?,?,?,?,?,?,?,?)",
                (eid, g.user["id"], d["sub_key"], valor, comentario, evidencia, db.ahora(), origen))
    if ev["estado"] == "borrador":
        con.execute("UPDATE evaluaciones SET estado='en_curso' WHERE id=?", (eid,))
    if "valor" in d:
        db.auditar(con, g.user["id"], "subfactor.respuesta",
                   f"{d.get('texto', d['sub_key'])[:70]}: {engine.NIVELES_PS.get(valor, 'sin evaluar')}"
                   + (f" (sugerencia de IA aceptada, {origen[3:]})" if origen.startswith("ia:") else ""), eid)
    con.commit()
    res = evaluar(obtener_eval(eid))
    f = next(x for x in res["factores"] if any(s["key"] == d["sub_key"] for s in x["subfactores"]))
    s = next(x for x in f["subfactores"] if x["key"] == d["sub_key"])
    return jsonify({"ok": True, "pm": f["pm"], "pm_txt": fmt_num(f["pm"]), "foda": f["foda"],
                    "evaluados": f["evaluados"], "total": f["total_sub"], "ps": s["ps"],
                    "ps_txt": fmt_num(s["ps"]), "desacuerdo": s["desacuerdo"], "n": s["n"]})


# --------------------------------------------------------- flujo de estados
@app.post("/evaluaciones/<int:eid>/enviar")
@login_requerido()
def enviar_revision(eid):
    ev = obtener_eval(eid)
    if not (editable(ev) and (g.user["id"] == ev["lider_id"] or g.user["rol"] == "admin")):
        abort(403)
    res = evaluar(ev)
    if res["sin_id"] or res["pendientes"] or not res["relevantes"]:
        flash("No se puede enviar a revisión: faltan importancias del decisor o subfactores por evaluar (RF-07).", "error")
        return redirect(url_for("paso4", eid=eid))
    con = get_db()
    con.execute("UPDATE evaluaciones SET estado='en_revision' WHERE id=?", (eid,))
    db.auditar(con, g.user["id"], "evaluacion.enviar", "Enviada a revisión", eid)
    con.commit()
    flash("Evaluación enviada a revisión.", "ok")
    return redirect(url_for("paso4", eid=eid))


@app.post("/evaluaciones/<int:eid>/decision")
@login_requerido("revisor")
def decision(eid):
    ev = obtener_eval(eid)
    if ev["estado"] != "en_revision":
        flash("Solo se decide sobre evaluaciones en revisión.", "error")
        return redirect(url_for("paso4", eid=eid))
    dec = request.form.get("decision")
    com = request.form.get("comentario", "").strip()
    if dec not in ("aprobada", "condicionada", "devuelta", "rechazada") or len(com) < 10:
        flash("Elige una decisión y escribe un comentario justificativo de al menos 10 caracteres.", "error")
        return redirect(url_for("paso4", eid=eid))
    con = get_db()
    res = evaluar(ev)
    if dec == "devuelta":
        con.execute("UPDATE evaluaciones SET estado='en_curso', decision=?, decision_comentario=?, decision_por=?, "
                    "decision_fecha=? WHERE id=?", (dec, com, g.user["id"], db.ahora(), eid))
        db.auditar(con, g.user["id"], "decision.devolver", com, eid)
        flash("Evaluación devuelta al equipo para corregir.", "ok")
    else:
        resumen = {"puntaje": res["puntaje"], "dimensiones": res["dimensiones"], "conteo": res["conteo"],
                   "recomendacion": res["recomendacion"]["tipo"] if res["recomendacion"] else None,
                   "titulo": res["recomendacion"]["titulo"] if res["recomendacion"] else None,
                   "foda": {f["nombre"]: f["foda"] for f in res["factores"]}}
        con.execute("UPDATE evaluaciones SET estado='cerrada', decision=?, decision_comentario=?, decision_por=?, "
                    "decision_fecha=?, cerrado=?, resultado=? WHERE id=?",
                    (dec, com, g.user["id"], db.ahora(), db.ahora(), json.dumps(resumen, ensure_ascii=False), eid))
        db.auditar(con, g.user["id"], "decision.emitir", f"{DECISIONES[dec]}: {com}", eid)
        flash("Decisión registrada y evaluación cerrada.", "ok")
    con.commit()
    return redirect(url_for("paso4", eid=eid))


@app.post("/evaluaciones/<int:eid>/cancelar")
@login_requerido("lider")
def cancelar(eid):
    ev = obtener_eval(eid)
    motivo = request.form.get("motivo", "").strip()
    if ev["estado"] == "cerrada" or not motivo:
        flash("Indica el motivo de la cancelación.", "error")
        return redirect(url_for("paso1", eid=eid))
    con = get_db()
    con.execute("UPDATE evaluaciones SET estado='cancelada' WHERE id=?", (eid,))
    db.auditar(con, g.user["id"], "evaluacion.cancelar", motivo, eid)
    con.commit()
    return redirect(url_for("evaluaciones"))


@app.post("/evaluaciones/<int:eid>/revision")
@login_requerido("lider")
def nueva_revision(eid):
    """RF-15: reabrir una evaluación cerrada como revisión nueva; la original no cambia."""
    ev = obtener_eval(eid)
    if ev["estado"] != "cerrada":
        abort(400)
    con = get_db()
    cols = ["org_nombre", "org_ruc", "org_sector", "org_correo", "sw_nombre", "sw_version", "sw_tipo",
            "sw_licencia", "sw_proveedor", "sw_descripcion", "catalogo_id", "snapshot"]
    cur = con.execute(f"INSERT INTO evaluaciones (codigo, {', '.join(cols)}, lider_id, revision_de, creado) "
                      f"VALUES (?, {', '.join('?' * len(cols))}, ?, ?, ?)",
                      [siguiente_codigo()] + [ev[c] for c in cols] + [g.user["id"], eid, db.ahora()])
    nid = cur.lastrowid
    for p in participantes(eid):
        con.execute("INSERT INTO participantes VALUES (?,?)", (nid, p["id"]))
    con.execute("INSERT OR IGNORE INTO participantes VALUES (?,?)", (nid, g.user["id"]))
    con.execute("INSERT INTO votos_factor SELECT ?, usuario_id, factor_key, id_valor, alcance FROM votos_factor "
                "WHERE evaluacion_id=?", (nid, eid))
    con.execute("INSERT INTO respuestas (evaluacion_id, usuario_id, sub_key, valor, comentario, evidencia, actualizado, "
                "origen) SELECT ?, usuario_id, sub_key, valor, comentario, evidencia, actualizado, origen "
                "FROM respuestas WHERE evaluacion_id=?", (nid, eid))
    con.execute("UPDATE evaluaciones SET estado='en_curso' WHERE id=?", (nid,))
    db.auditar(con, g.user["id"], "evaluacion.revision", f"Revisión nueva de {ev['codigo']}", nid)
    con.commit()
    flash(f"Se creó una revisión nueva a partir de {ev['codigo']}. La evaluación original no se modifica.", "ok")
    return redirect(url_for("paso2", eid=nid))


# ------------------------------------------------------- informe y export
@app.route("/evaluaciones/<int:eid>/informe")
@login_requerido()
def informe(eid):
    ev = obtener_eval(eid)
    res = evaluar(ev)
    db.auditar(get_db(), g.user["id"], "informe.ver", "Informe consultado", eid)
    get_db().commit()
    return render_template("informe.html", ev=ev, res=res, parts=participantes(eid), umbral=umbral(),
                           resumen=json.loads(ev["resumen_ia"]) if ev["resumen_ia"] else None,
                           decisor=nombre_usuario(ev["decision_por"]))


@app.route("/evaluaciones/<int:eid>/exportar.csv")
@login_requerido()
def exportar_csv(eid):
    ev = obtener_eval(eid)
    res = evaluar(ev)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Evaluación", ev["codigo"], "Software", ev["sw_nombre"], "Organización", ev["org_nombre"]])
    w.writerow([])
    w.writerow(["Dimensión", "Factor", "IS", "ID", "IR", "Relevante", "Alcance", "PM", "FODA"])
    for f in res["factores"]:
        w.writerow([f["dimension"], f["nombre"], f["is_valor"], f["id"] or "", f["ir"] or "",
                    "Sí" if f["relevante"] else "No", f["alcance"], fmt_num(f["pm"]), f["foda"] or ""])
    w.writerow([])
    w.writerow(["Factor", "Subfactor", "PS (consenso)", "Respuestas"])
    for f in res["factores"]:
        for s in f["subfactores"]:
            w.writerow([f["nombre"], s["texto"], fmt_num(s["ps"]), s["n"]])
    db.auditar(get_db(), g.user["id"], "informe.exportar", "Exportación CSV", eid)
    get_db().commit()
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={ev['codigo']}.csv"})


def _datos_export(ev):
    res = evaluar(ev)
    sens = engine.sensibilidad(construir_entrada(ev), umbral()) if res["recomendacion"] else None
    resumen = json.loads(ev["resumen_ia"]) if ev["resumen_ia"] else None
    return res, sens, resumen


@app.route("/evaluaciones/<int:eid>/exportar.xlsx")
@login_requerido()
def exportar_xlsx(eid):
    ev = obtener_eval(eid)
    res, sens, resumen = _datos_export(ev)
    resp = {}
    for r in get_db().execute("SELECT * FROM respuestas WHERE evaluacion_id=? ORDER BY actualizado", (eid,)):
        resp[r["sub_key"]] = dict(r)
    data = exportar.excel(ev, res, sens, resumen, resp, engine.matriz_riesgos(res, umbral()))
    db.auditar(get_db(), g.user["id"], "informe.exportar", "Exportación Excel", eid)
    get_db().commit()
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename={ev['codigo']}_GUIOS.xlsx"})


@app.route("/evaluaciones/<int:eid>/informe.pdf")
@login_requerido()
def informe_pdf(eid):
    ev = obtener_eval(eid)
    res, sens, resumen = _datos_export(ev)
    con = get_db()
    fecha = db.ahora()
    datos = integridad.datos_sellables(ev, res, fecha)
    folio = integridad.nuevo_folio()
    sello = {"folio": folio, "fecha": fecha, "hash_datos": integridad.huella_datos(datos),
             "qr": integridad.qr_png(f"GUIOS EVAL | {ev['codigo']} | folio {folio} | "
                                     f"verificar en {request.host_url}verificar?folio={folio}")}
    data = exportar.pdf(ev, res, sens, resumen, umbral(), engine.matriz_riesgos(res, umbral()), sello)
    con.execute("INSERT INTO sellos (folio, evaluacion_id, fecha, usuario_id, hash_datos, hash_archivo, resumen) "
                "VALUES (?,?,?,?,?,?,?)", (folio, eid, fecha, g.user["id"], sello["hash_datos"],
                                           integridad.huella_archivo(data), json.dumps(datos, ensure_ascii=False)))
    db.auditar(con, g.user["id"], "informe.exportar", f"Informe PDF con sello {folio}", eid)
    con.commit()
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={ev['codigo']}_informe.pdf"})


@app.route("/verificar", methods=["GET", "POST"])
def verificar_informe():
    """Comprueba un informe por su archivo PDF o por su folio (no requiere iniciar sesión)."""
    con = get_db()
    folio = (request.values.get("folio") or "").strip().upper()
    resultado, sello = None, None
    archivo = request.files.get("pdf") if request.method == "POST" else None
    contenido = archivo.read(20 * 1024 * 1024) if archivo and archivo.filename else b""
    if contenido:
        fila = con.execute("SELECT * FROM sellos WHERE hash_archivo=?", (integridad.huella_archivo(contenido),)).fetchone()
        if fila:
            sello = fila
            resultado = {"ok": True, "titulo": "Informe auténtico y sin modificaciones",
                         "detalle": "El archivo es idéntico, byte a byte, al que emitió GUIOS EVAL."}
        else:
            folio = integridad.folio_en_pdf(contenido) or folio
            sello = con.execute("SELECT * FROM sellos WHERE folio=?", (folio,)).fetchone() if folio else None
            resultado = {"ok": False, "titulo": "El archivo NO coincide con ningún informe emitido",
                         "detalle": ("El PDF dice tener el folio " + folio + ", pero su contenido fue modificado después "
                                     "de emitirse. Compara con los datos registrados abajo.") if sello else
                                    "No es un informe de GUIOS EVAL o fue alterado."}
    elif folio:
        sello = con.execute("SELECT * FROM sellos WHERE folio=?", (folio,)).fetchone()
        resultado = ({"ok": True, "titulo": f"Folio {folio} registrado",
                      "detalle": "Estos son los datos que tenía la evaluación al emitir el informe. Compáralos con el "
                                 "documento impreso. Para una verificación exacta, sube el PDF."} if sello else
                     {"ok": False, "titulo": "Folio no encontrado",
                      "detalle": "Ese folio no fue emitido por este sistema."})
    if request.method == "POST" or folio:
        db.auditar(con, g.user["id"] if g.user else None, "informe.verificar",
                   f"Verificación de informe: {resultado['titulo'] if resultado else 'sin datos'}")
        con.commit()
    if sello:
        sello = dict(sello, datos=json.loads(sello["resumen"]))
    return render_template("verificar.html", resultado=resultado, sello=sello, folio=folio)


# --------------------------------------------------------------- comparar
@app.route("/comparar")
@login_requerido()
def comparar():
    con = get_db()
    todas = con.execute("SELECT * FROM evaluaciones WHERE estado!='cancelada' ORDER BY id DESC").fetchall()
    sel = [int(x) for x in request.args.getlist("ev")][:4]
    columnas = []
    for eid in sel:
        ev = obtener_eval(eid)
        columnas.append({"ev": ev, "res": evaluar(ev)})
    factores = []
    if columnas:
        nombres = []
        for c in columnas:
            for f in c["res"]["factores"]:
                if f["nombre"] not in nombres:
                    nombres.append(f["nombre"])
        for n in nombres:
            factores.append((n, [next((f for f in c["res"]["factores"] if f["nombre"] == n), None) for c in columnas]))
    return render_template("comparar.html", todas=todas, sel=sel, columnas=columnas, factores=factores)


# --------------------------------------------------------------- catálogo
@app.route("/catalogo")
@login_requerido()
def catalogo():
    con = get_db()
    versiones = con.execute("SELECT c.*, (SELECT COUNT(*) FROM factores f WHERE f.catalogo_id=c.id AND f.activo=1) nf, "
                            "(SELECT COUNT(*) FROM subfactores s JOIN factores f ON f.id=s.factor_id WHERE "
                            "f.catalogo_id=c.id AND s.activo=1 AND f.activo=1) ns, (SELECT COUNT(*) FROM evaluaciones e "
                            "WHERE e.catalogo_id=c.id) ne FROM catalogos c ORDER BY version DESC").fetchall()
    cid = request.args.get("c", type=int) or (versiones[0]["id"] if versiones else None)
    cat = con.execute("SELECT * FROM catalogos WHERE id=?", (cid,)).fetchone()
    dim = request.args.get("dim", "")
    q = request.args.get("q", "").strip()
    sql = "SELECT * FROM factores WHERE catalogo_id=?"
    args = [cid]
    if dim:
        sql += " AND dimension=?"
        args.append(dim)
    if q:
        sql += " AND nombre LIKE ?"
        args.append(f"%{q}%")
    factores = []
    for f in con.execute(sql + " ORDER BY orden, id", args):
        subs = con.execute("SELECT * FROM subfactores WHERE factor_id=? ORDER BY orden, id", (f["id"],)).fetchall()
        factores.append((f, subs))
    puede = con_rol("admin_catalogo") and cat and cat["estado"] == "borrador"
    return render_template("catalogo.html", versiones=versiones, cat=cat, factores=factores, puede=puede,
                           dim=dim, q=q, gestiona=con_rol("admin_catalogo"))


def cat_editable(cid):
    cat = get_db().execute("SELECT * FROM catalogos WHERE id=?", (cid,)).fetchone()
    if not cat or cat["estado"] != "borrador":
        flash("Solo se editan catálogos en borrador. Crea una versión nueva para hacer cambios.", "error")
        return None
    return cat


def copiar_catalogo(con, base, nota, ajustes=None):
    """Crea un borrador nuevo a partir de `base`. `ajustes` cambia IS/IE/IL/citas por nombre de factor."""
    ajustes = ajustes or {}
    ver = con.execute("SELECT MAX(version) FROM catalogos").fetchone()[0] + 1
    nid = con.execute("INSERT INTO catalogos (nombre, version, estado, nota, creado) VALUES (?,?,?,?,?)",
                      (base["nombre"], ver, "borrador", nota, db.ahora())).lastrowid
    for f in con.execute("SELECT * FROM factores WHERE catalogo_id=? ORDER BY orden, id", (base["id"],)).fetchall():
        a = ajustes.get(f["nombre"], {})
        fid = con.execute("INSERT INTO factores (catalogo_id, nombre, dimension, is_valor, alcance, descripcion, "
                          "activo, orden, ie, il, citas, calibracion_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (nid, f["nombre"], f["dimension"], a.get("is_valor", f["is_valor"]), f["alcance"],
                           f["descripcion"], f["activo"], f["orden"], a.get("ie", f["ie"]), a.get("il", f["il"]),
                           a.get("citas", f["citas"]), a.get("calibracion_id", f["calibracion_id"]))).lastrowid
        con.execute("INSERT INTO subfactores (factor_id, texto, activo, orden) SELECT ?, texto, activo, orden "
                    "FROM subfactores WHERE factor_id=?", (fid, f["id"]))
    return nid, ver


@app.post("/catalogo/nueva-version")
@login_requerido("admin_catalogo")
def catalogo_nueva_version():
    con = get_db()
    base = con.execute("SELECT * FROM catalogos WHERE id=?", (request.form.get("base_id", type=int),)).fetchone()
    nid, ver = copiar_catalogo(con, base, f"Basado en la versión {base['version']}")
    db.auditar(con, g.user["id"], "catalogo.version", f"Borrador v{ver} creado desde v{base['version']}")
    con.commit()
    flash(f"Se creó la versión {ver} en borrador. Ya puedes agregar, editar o eliminar factores y subfactores.", "ok")
    return redirect(url_for("catalogo", c=nid))


@app.post("/catalogo/<int:cid>/publicar")
@login_requerido("admin_catalogo")
def catalogo_publicar(cid):
    if not cat_editable(cid):
        return redirect(url_for("catalogo", c=cid))
    con = get_db()
    con.execute("UPDATE catalogos SET estado='retirado' WHERE estado='publicado'")
    con.execute("UPDATE catalogos SET estado='publicado', publicado=? WHERE id=?", (db.ahora(), cid))
    db.auditar(con, g.user["id"], "catalogo.publicar", f"Catálogo {cid} publicado; la versión anterior se retira")
    con.commit()
    flash("Catálogo publicado. Las evaluaciones nuevas lo usarán; las existentes conservan su copia.", "ok")
    return redirect(url_for("catalogo", c=cid))


@app.post("/catalogo/<int:cid>/factor")
@login_requerido("admin_catalogo")
def factor_guardar(cid):
    if not cat_editable(cid):
        return redirect(url_for("catalogo", c=cid))
    f = request.form
    con = get_db()
    datos = (f["nombre"].strip(), f["dimension"], int(f["is_valor"]), f["alcance"], f.get("descripcion", "").strip(),
             1 if f.get("activo", "1") == "1" else 0)
    if f.get("factor_id"):
        con.execute("UPDATE factores SET nombre=?, dimension=?, is_valor=?, alcance=?, descripcion=?, activo=? "
                    "WHERE id=? AND catalogo_id=?", datos + (int(f["factor_id"]), cid))
        db.auditar(con, g.user["id"], "factor.editar", f"Factor {datos[0]} actualizado")
        flash(f"Factor «{datos[0]}» actualizado.", "ok")
    else:
        orden = con.execute("SELECT COALESCE(MAX(orden),0)+1 FROM factores WHERE catalogo_id=?", (cid,)).fetchone()[0]
        con.execute("INSERT INTO factores (catalogo_id, nombre, dimension, is_valor, alcance, descripcion, activo, orden) "
                    "VALUES (?,?,?,?,?,?,?,?)", (cid,) + datos + (orden,))
        db.auditar(con, g.user["id"], "factor.crear", f"Factor {datos[0]} creado")
        flash(f"Factor «{datos[0]}» agregado.", "ok")
    con.commit()
    return redirect(url_for("catalogo", c=cid))


@app.post("/catalogo/<int:cid>/factor/<int:fid>/eliminar")
@login_requerido("admin_catalogo")
def factor_eliminar(cid, fid):
    if not cat_editable(cid):
        return redirect(url_for("catalogo", c=cid))
    con = get_db()
    f = con.execute("SELECT nombre FROM factores WHERE id=?", (fid,)).fetchone()
    con.execute("DELETE FROM factores WHERE id=? AND catalogo_id=?", (fid, cid))
    db.auditar(con, g.user["id"], "factor.eliminar", f"Factor {f['nombre']} eliminado")
    con.commit()
    flash(f"Factor «{f['nombre']}» eliminado con sus subfactores.", "ok")
    return redirect(url_for("catalogo", c=cid))


@app.post("/catalogo/<int:cid>/subfactor")
@login_requerido("admin_catalogo")
def subfactor_guardar(cid):
    if not cat_editable(cid):
        return redirect(url_for("catalogo", c=cid))
    f = request.form
    con = get_db()
    texto = f["texto"].strip()
    if not texto:
        return redirect(url_for("catalogo", c=cid))
    if f.get("sub_id"):
        con.execute("UPDATE subfactores SET texto=? WHERE id=?", (texto, int(f["sub_id"])))
        db.auditar(con, g.user["id"], "subfactor.editar", texto[:80])
    else:
        fid = int(f["factor_id"])
        orden = con.execute("SELECT COALESCE(MAX(orden),0)+1 FROM subfactores WHERE factor_id=?", (fid,)).fetchone()[0]
        con.execute("INSERT INTO subfactores (factor_id, texto, orden) VALUES (?,?,?)", (fid, texto, orden))
        db.auditar(con, g.user["id"], "subfactor.crear", texto[:80])
    con.commit()
    flash("Subfactor guardado.", "ok")
    return redirect(url_for("catalogo", c=cid) + f"#f{f.get('factor_id', '')}")


@app.post("/catalogo/<int:cid>/subfactor/<int:sid>/eliminar")
@login_requerido("admin_catalogo")
def subfactor_eliminar(cid, sid):
    if not cat_editable(cid):
        return redirect(url_for("catalogo", c=cid))
    con = get_db()
    s = con.execute("SELECT * FROM subfactores WHERE id=?", (sid,)).fetchone()
    con.execute("DELETE FROM subfactores WHERE id=?", (sid,))
    db.auditar(con, g.user["id"], "subfactor.eliminar", s["texto"][:80])
    con.commit()
    flash("Subfactor eliminado.", "ok")
    return redirect(url_for("catalogo", c=cid) + f"#f{s['factor_id']}")


# ---------------------------------------------------------- configuración
# ------------------------------------------------- calibración bibliográfica
def catalogo_publicado(con):
    return con.execute("SELECT * FROM catalogos WHERE estado='publicado' ORDER BY version DESC").fetchone()


def terminos_personalizados(con):
    return {r["nombre"]: r for r in con.execute("SELECT * FROM terminos_factor")}


def cargar_calibracion(row):
    return dict(row, filas=json.loads(row["resultado"]), umbrales=json.loads(row["umbrales"] or "[0,0,0]"))


def datos_tendencia(nombres):
    """Tendencia 2008-2025 por factor: participación anual en el corpus y comparación 2008-2019 vs 2020-2025."""
    t = literatura.tendencia_guardada()
    if not t:
        return None
    filas = []
    for n in nombres:
        if n not in t["factores"]:
            continue
        r = engine.tendencia(t["factores"][n], t["corpus"], t["desde"], t["hasta"])
        maximo = max([x["pct"] for x in r["serie"]] + [1])
        ancho = len(r["serie"]) - 1 or 1
        r["puntos"] = " ".join(f"{i * 240 / ancho:.1f},{56 - x['pct'] / maximo * 50:.1f}" for i, x in enumerate(r["serie"]))
        r["corte_x"] = (2020 - t["desde"]) * 240 / ancho
        r["nombre"] = n
        filas.append(r)
    orden = {"Sube": 0, "Estable": 1, "Baja": 2}
    filas.sort(key=lambda r: (orden[r["etiqueta"]], -r["pct_reciente"]))
    return {"fecha": t["fecha"], "desde": t["desde"], "hasta": t["hasta"], "filas": filas,
            "corpus_total": sum(int(v) for v in t["corpus"].values())}


@app.post("/literatura/tendencia")
@login_requerido("admin_catalogo")
def literatura_tendencia():
    con = get_db()
    cat = catalogo_publicado(con)
    nombres = [r["nombre"] for r in con.execute("SELECT nombre FROM factores WHERE catalogo_id=? AND activo=1 "
                                                "ORDER BY orden, id", (cat["id"],))]
    try:
        datos = literatura.consultar_tendencia(nombres, 2008, 2025,
                                               {k: v["terminos"] for k, v in terminos_personalizados(con).items()})
    except RuntimeError as e:
        flash(f"No se pudo actualizar la tendencia: {e}. Se mantiene la corrida guardada.", "error")
        return redirect(url_for("literatura_view") + "#tendencia")
    literatura.guardar_tendencia(datos)
    db.auditar(con, g.user["id"], "literatura.tendencia", f"Tendencia 2008-2025 actualizada ({len(nombres)} factores)")
    con.commit()
    flash("Tendencia actualizada con OpenAlex.", "ok")
    return redirect(url_for("literatura_view") + "#tendencia")


@app.route("/literatura")
@login_requerido()
def literatura_view():
    con = get_db()
    cat = catalogo_publicado(con)
    pers = terminos_personalizados(con)
    factores = []
    for f in con.execute("SELECT f.*, (SELECT COUNT(*) FROM subfactores s WHERE s.factor_id=f.id AND s.activo=1) n "
                         "FROM factores f WHERE f.catalogo_id=? AND f.activo=1 ORDER BY orden, id", (cat["id"],)):
        p = pers.get(f["nombre"])
        factores.append({"nombre": f["nombre"], "dimension": f["dimension"], "n": f["n"],
                         "terminos": p["terminos"] if p else literatura.terminos_de(f["nombre"]),
                         "ie": p["ie"] if p else (f["ie"] or 3), "is_actual": f["is_valor"]})
    corridas = con.execute("SELECT c.*, u.nombre usuario, k.version cat_version, a.version apl_version "
                           "FROM calibraciones c LEFT JOIN usuarios u ON u.id=c.usuario_id "
                           "LEFT JOIN catalogos k ON k.id=c.catalogo_id LEFT JOIN catalogos a ON a.id=c.aplicada_en "
                           "ORDER BY c.id DESC").fetchall()
    sel = request.args.get("c", type=int) or (corridas[0]["id"] if corridas else None)
    actual = None
    if sel:
        r = con.execute("SELECT c.*, k.version cat_version, a.version apl_version FROM calibraciones c "
                        "LEFT JOIN catalogos k ON k.id=c.catalogo_id LEFT JOIN catalogos a ON a.id=c.aplicada_en "
                        "WHERE c.id=?", (sel,)).fetchone()
        actual = cargar_calibracion(r) if r else None
    return render_template("literatura.html", cat=cat, factores=factores, corridas=corridas, actual=actual,
                           tendencia=datos_tendencia([f["nombre"] for f in factores]),
                           desde=db.config(con, "lit_desde", "2020"), hasta=db.config(con, "lit_hasta", "2025"),
                           gestiona=con_rol("admin_catalogo"), corpus_titulo=literatura.CORPUS_TITULO,
                           corpus_resumen=literatura.CORPUS_RESUMEN, subcampos=literatura.SUBCAMPOS)


@app.post("/literatura/terminos")
@login_requerido("admin_catalogo")
def literatura_terminos():
    con = get_db()
    f = request.form
    for nombre in f.getlist("nombre"):
        t = f.get(f"t::{nombre}", "").strip()
        ie = f.get(f"ie::{nombre}", type=int) or 3
        if t:
            con.execute("INSERT INTO terminos_factor (nombre, terminos, ie) VALUES (?,?,?) ON CONFLICT(nombre) "
                        "DO UPDATE SET terminos=excluded.terminos, ie=excluded.ie", (nombre, t, max(1, min(4, ie))))
    desde, hasta = f.get("desde", type=int), f.get("hasta", type=int)
    if desde and hasta and 1990 <= desde <= hasta <= 2100:
        con.execute("UPDATE configuracion SET valor=? WHERE clave='lit_desde'", (str(desde),))
        con.execute("UPDATE configuracion SET valor=? WHERE clave='lit_hasta'", (str(hasta),))
    db.auditar(con, g.user["id"], "literatura.terminos", f"Términos de búsqueda e IE actualizados; ventana {desde}-{hasta}")
    con.commit()
    flash("Términos de búsqueda, importancia del experto y ventana de años guardados.", "ok")
    return redirect(url_for("literatura_view"))


@app.post("/literatura/ejecutar")
@login_requerido("admin_catalogo")
def literatura_ejecutar():
    con = get_db()
    cat = catalogo_publicado(con)
    pers = terminos_personalizados(con)
    desde, hasta = int(db.config(con, "lit_desde", "2020")), int(db.config(con, "lit_hasta", "2025"))
    factores = con.execute("SELECT f.*, (SELECT COUNT(*) FROM subfactores s WHERE s.factor_id=f.id AND s.activo=1) n "
                           "FROM factores f WHERE f.catalogo_id=? AND f.activo=1 ORDER BY orden, id",
                           (cat["id"],)).fetchall()
    nombres = [f["nombre"] for f in factores]
    modo = request.form.get("modo", "vivo")
    try:
        if modo == "guardado":
            res = literatura.guardado()
            desde, hasta = res["desde"], res["hasta"]
        else:
            res = literatura.consultar(nombres, desde, hasta, {k: v["terminos"] for k, v in pers.items()})
    except Exception as e:
        flash(f"No se pudo consultar OpenAlex ({e}). Revisa la conexión a internet o usa la corrida guardada.", "error")
        return redirect(url_for("literatura_view"))
    entrada = []
    for f in factores:
        p = pers.get(f["nombre"])
        entrada.append({"nombre": f["nombre"], "dimension": f["dimension"], "n": f["n"],
                        "citas": res["conteos"].get(f["nombre"], 0), "ie": p["ie"] if p else (f["ie"] or 3),
                        "is_anterior": f["is_valor"], "il_anterior": f["il"], "citas_anterior": f["citas"],
                        "terminos": p["terminos"] if p else literatura.terminos_de(f["nombre"]),
                        "top": res["top"].get(f["nombre"], []), "consulta": res["consultas"].get(f["nombre"])})
    filas, umbrales = engine.calibrar(entrada)
    cid = con.execute("INSERT INTO calibraciones (fecha, usuario_id, catalogo_id, desde, hasta, fuente, corpus, "
                      "umbrales, resultado) VALUES (?,?,?,?,?,?,?,?,?)",
                      (db.ahora(), g.user["id"], cat["id"], desde, hasta, res["fuente"], res["corpus"],
                       json.dumps(umbrales), json.dumps(filas, ensure_ascii=False))).lastrowid
    cambios = sum(1 for x in filas if x["is_nueva"] != x["is_anterior"])
    db.auditar(con, g.user["id"], "literatura.calibrar",
               f"Calibración #{cid} {desde}-{hasta}: corpus {res['corpus']} estudios, {cambios} factores cambian de IS")
    con.commit()
    flash(f"Calibración #{cid} terminada: {res['corpus']} estudios {desde}-{hasta}. "
          f"{cambios} factores cambian su importancia sugerida.", "ok")
    return redirect(url_for("literatura_view", c=cid))


@app.post("/literatura/<int:cid>/aplicar")
@login_requerido("admin_catalogo")
def literatura_aplicar(cid):
    con = get_db()
    cal = con.execute("SELECT * FROM calibraciones WHERE id=?", (cid,)).fetchone()
    if not cal or cal["aplicada_en"]:
        flash("Esa calibración no existe o ya se aplicó.", "error")
        return redirect(url_for("literatura_view", c=cid))
    base = catalogo_publicado(con)
    filas = json.loads(cal["resultado"])
    ajustes = {x["nombre"]: {"is_valor": x["is_nueva"], "ie": x["ie"], "il": x["il"], "citas": x["citas"],
                             "calibracion_id": cid} for x in filas}
    nid, ver = copiar_catalogo(con, base, f"IS recalculada con la literatura {cal['desde']}-{cal['hasta']} "
                                          f"(calibración #{cid}, {cal['corpus']} estudios en OpenAlex)", ajustes)
    con.execute("UPDATE calibraciones SET aplicada_en=? WHERE id=?", (nid, cid))
    publicar = request.form.get("publicar") == "1"
    if publicar:
        con.execute("UPDATE catalogos SET estado='retirado' WHERE estado='publicado'")
        con.execute("UPDATE catalogos SET estado='publicado', publicado=? WHERE id=?", (db.ahora(), nid))
    db.auditar(con, g.user["id"], "literatura.aplicar",
               f"Calibración #{cid} aplicada en el catálogo v{ver}" + (" (publicado)" if publicar else " (borrador)"))
    con.commit()
    flash(f"Se creó el catálogo v{ver} con la importancia sugerida recalculada"
          + (" y quedó publicado. Las evaluaciones nuevas lo usarán." if publicar else ". Revísalo y publícalo."), "ok")
    return redirect(url_for("catalogo", c=nid))


@app.route("/literatura/<int:cid>/exportar.csv")
@login_requerido()
def literatura_csv(cid):
    cal = get_db().execute("SELECT * FROM calibraciones WHERE id=?", (cid,)).fetchone()
    if not cal:
        abort(404)
    filas = json.loads(cal["resultado"])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Factor", "Dimensión", "Subfactores (n)", f"Estudios {cal['desde']}-{cal['hasta']} (c)", "r = c/n",
                "IL", "IE", "IS nueva", "IS anterior", "Términos de búsqueda", "Consulta OpenAlex"])
    for x in filas:
        w.writerow([x["nombre"], x["dimension"], x["n"], x["citas"], f"{x['r']:.2f}".replace(".", ","), x["il"],
                    x["ie"], x["is_nueva"], x["is_anterior"], x["terminos"], x.get("consulta") or ""])
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=calibracion_{cid}.csv"})


# ------------------------------------------------------------ asistente de IA
def ia_modo():
    return db.config(get_db(), "ia_modo", "automatico")


def estudios_factor(nombre):
    """Estudios 2020-2025 de la última calibración para un factor (evidencia que la IA puede citar)."""
    r = get_db().execute("SELECT resultado FROM calibraciones ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return []
    for x in json.loads(r["resultado"]):
        if x["nombre"] == nombre:
            return x.get("top") or []
    return []


@app.post("/api/evaluaciones/<int:eid>/ia/subfactores")
@login_requerido()
def api_ia_subfactores(eid):
    ev = obtener_eval(eid)
    if not puede_votar(ev):
        return jsonify({"ok": False, "error": "No puedes editar esta evaluación."}), 403
    if ia_modo() == "desactivado":
        return jsonify({"ok": False, "error": "El asistente de IA está desactivado en Configuración."})
    key = (request.get_json(force=True) or {}).get("factor_key")
    snap = json.loads(ev["snapshot"])
    factor = next((f for f in snap if f["key"] == key), None)
    if not factor:
        return jsonify({"ok": False, "error": "Factor no encontrado."}), 404
    r = ia.sugerir_subfactores(ev, factor, estudios_factor(factor["nombre"]), ia_modo())
    con = get_db()
    if r["ok"]:
        db.auditar(con, g.user["id"], "ia.sugerencia",
                   f"{r['proveedor']} ({r['modelo']}) sugirió {len(r['propuestas'])} respuestas para {factor['nombre']}", eid)
        con.commit()
        return jsonify(r)
    return jsonify({"ok": False, "error": "Ningún proveedor de IA respondió. " + " | ".join(r.get("errores") or [])
                    + " Puedes seguir respondiendo manualmente."})


@app.post("/evaluaciones/<int:eid>/ia/resumen")
@login_requerido()
def ia_resumen(eid):
    ev = obtener_eval(eid)
    res = evaluar(ev)
    if not res["recomendacion"]:
        flash("Primero evalúa los subfactores para tener una recomendación.", "error")
        return redirect(url_for("paso4", eid=eid))
    r = ia.sugerir_resumen(ev, res, ia_modo()) if ia_modo() != "desactivado" else {"ok": False, "errores": []}
    if r["ok"] and not r["coherente"]:
        r = ia.sugerir_resumen(ev, res, ia_modo())  # segundo intento si contradice la recomendación
    con = get_db()
    if r["ok"]:
        dato = {"resumen": r["resumen"], "plan": r["plan"], "coherente": r["coherente"], "fuente": r["proveedor"],
                "modelo": r["modelo"], "fecha": db.ahora(), "tipo": res["recomendacion"]["tipo"], "editado": False}
        flash(f"Resumen ejecutivo y plan de acción generados con {r['proveedor']}. Revísalos antes de usarlos.", "ok")
    else:
        # Respaldo sin IA: el motor de reglas redacta el resumen y el plan a partir de las causas.
        rec = res["recomendacion"]
        dato = {"resumen": f"{rec['titulo']} (recomendación tipo {rec['tipo']}). {rec['texto']} "
                           f"El índice de adopción es {res['puntaje']}/100.",
                "plan": [{"factor": c["factor"], "accion": c["accion"][:1].upper() + c["accion"][1:],
                          "entregable": "Informe de cumplimiento de los subfactores: " + "; ".join(c["subfactores"][:3]),
                          "plazo": "4 semanas", "responsable": "Dirección de TIC"} for c in rec["causas"]],
                "coherente": True, "fuente": "Motor de reglas GUIOS (sin IA)", "modelo": "", "fecha": db.ahora(),
                "tipo": rec["tipo"], "editado": False}
        flash("No respondió ningún proveedor de IA; el resumen se generó con el motor de reglas.", "warn")
    con.execute("UPDATE evaluaciones SET resumen_ia=? WHERE id=?", (json.dumps(dato, ensure_ascii=False), eid))
    db.auditar(con, g.user["id"], "ia.resumen", f"Resumen ejecutivo generado con {dato['fuente']}", eid)
    con.commit()
    return redirect(url_for("paso4", eid=eid) + "#resumen")


@app.post("/evaluaciones/<int:eid>/resumen/guardar")
@login_requerido()
def resumen_guardar(eid):
    ev = obtener_eval(eid)
    con = get_db()
    dato = json.loads(ev["resumen_ia"]) if ev["resumen_ia"] else {"plan": [], "fuente": "Redactado por el usuario"}
    texto = request.form.get("resumen", "").strip()
    tipo = (evaluar(ev)["recomendacion"] or {}).get("tipo", "C")
    if request.form.get("eliminar"):
        con.execute("UPDATE evaluaciones SET resumen_ia=NULL WHERE id=?", (eid,))
        flash("Resumen eliminado.", "ok")
    else:
        dato.update({"resumen": texto, "coherente": ia.coherencia(texto, tipo), "editado": True,
                     "fecha": db.ahora(), "tipo": tipo})
        con.execute("UPDATE evaluaciones SET resumen_ia=? WHERE id=?", (json.dumps(dato, ensure_ascii=False), eid))
        flash("Resumen guardado." if dato["coherente"] else
              "Resumen guardado, pero menciona una recomendación distinta de la calculada. Revísalo.",
              "ok" if dato["coherente"] else "warn")
    db.auditar(con, g.user["id"], "resumen.editar", "Resumen ejecutivo editado o eliminado", eid)
    con.commit()
    return redirect(url_for("paso4", eid=eid) + "#resumen")


@app.post("/configuracion/ia")
@login_requerido("admin")
def configuracion_ia():
    con = get_db()
    modo = request.form.get("ia_modo", "automatico")
    if modo not in ("automatico", "nube", "local", "desactivado"):
        modo = "automatico"
    if not request.form.get("probar"):
        con.execute("INSERT OR REPLACE INTO configuracion VALUES ('ia_modo', ?)", (modo,))
        db.auditar(con, g.user["id"], "ia.config", f"Modo del asistente de IA: {modo}")
        con.commit()
    if request.form.get("probar"):
        r = ia.probar(modo)
        if r["ok"]:
            flash(f"Prueba correcta: responde {r['proveedor']} ({r['modelo']}). El modo solo cambia al pulsar Guardar.",
                  "ok")
        else:
            flash("Ningún proveedor respondió. " + " | ".join(r["errores"] or ["No hay claves ni IA local configuradas."]),
                  "error")
    else:
        flash("Modo del asistente de IA guardado.", "ok")
    return redirect(url_for("configuracion") + "#ia")


@app.route("/api/literatura/probar")
@login_requerido()
def api_literatura_probar():
    t = request.args.get("t", "").strip()
    con = get_db()
    desde, hasta = int(db.config(con, "lit_desde", "2020")), int(db.config(con, "lit_hasta", "2025"))
    try:
        d = literatura.obtener(literatura.url_consulta(desde, hasta, t, 3))
        return jsonify({"ok": True, "conteo": d["meta"]["count"],
                        "top": [[w.get("display_name"), w.get("publication_year"), w.get("doi")] for w in d["results"]]})
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo consultar OpenAlex: {e}"})


def guardar_usuario(con, f):
    """Alta o edición de usuarios por el administrador, con validaciones para evitar errores."""
    rol = f.get("rol", "")
    nombre, correo = f.get("nombre", "").strip(), f.get("correo", "").strip().lower()
    if rol not in db.ROLES:
        flash("Selecciona un rol para el usuario.", "error")
        return
    if len(nombre) < 3 or "@" not in correo:
        flash("Escribe el nombre completo y un correo válido.", "error")
        return
    uid = f.get("usuario_id", type=int)
    if uid:
        if uid == g.user["id"] and (rol != "admin" or not f.get("activo")):
            flash("No puedes quitarte el rol de administrador ni desactivarte a ti mismo.", "error")
            return
        con.execute("UPDATE usuarios SET nombre=?, correo=?, rol=?, activo=?, "
                    "estado=CASE WHEN estado='rechazado' THEN 'activo' ELSE estado END WHERE id=?",
                    (nombre, correo, rol, 1 if f.get("activo") else 0, uid))
        if f.get("clave"):
            con.execute("UPDATE usuarios SET clave=?, cambiar_clave=? WHERE id=?",
                        (generate_password_hash(f["clave"]), 0 if uid == g.user["id"] else 1, uid))
        db.auditar(con, g.user["id"], "usuario.editar", f"{correo} ({db.ROLES[rol]})")
        flash(f"Usuario {nombre} actualizado.", "ok")
        return
    clave = f.get("clave", "")
    if len(clave) < 6:
        flash("Escribe una contraseña inicial de al menos 6 caracteres para el usuario nuevo.", "error")
        return
    if con.execute("SELECT 1 FROM usuarios WHERE correo=?", (correo,)).fetchone():
        flash("Ya existe un usuario con ese correo.", "error")
        return
    con.execute("INSERT INTO usuarios (nombre, correo, clave, rol, creado, cambiar_clave) VALUES (?,?,?,?,?,1)",
                (nombre, correo, generate_password_hash(clave), rol, db.ahora()))
    db.auditar(con, g.user["id"], "usuario.crear", f"{correo} ({db.ROLES[rol]})")
    flash(f"Usuario {nombre} creado como {db.ROLES[rol]}.", "ok")


FOTOS = os.path.join(os.path.dirname(db.DB_PATH), "fotos")
FIRMAS = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"RIFF": "webp"}


@app.post("/perfil/foto")
@login_requerido()
def perfil_foto():
    con = get_db()
    if request.form.get("quitar"):
        con.execute("UPDATE usuarios SET foto=NULL WHERE id=?", (g.user["id"],))
        con.commit()
        flash("Foto de perfil eliminada.", "ok")
        return redirect(url_for("configuracion"))
    archivo = request.files.get("foto")
    datos = archivo.read(2 * 1024 * 1024 + 1) if archivo else b""
    ext = next((e for firma, e in FIRMAS.items() if datos.startswith(firma)), None)
    if not datos or len(datos) > 2 * 1024 * 1024 or not ext or (ext == "webp" and datos[8:12] != b"WEBP"):
        flash("Sube una imagen PNG, JPG o WEBP de hasta 2 MB.", "error")
        return redirect(url_for("configuracion"))
    os.makedirs(FOTOS, exist_ok=True)
    nombre = f"usuario_{g.user['id']}.{ext}"
    for viejo in os.listdir(FOTOS):
        if viejo.startswith(f"usuario_{g.user['id']}."):
            os.remove(os.path.join(FOTOS, viejo))
    with open(os.path.join(FOTOS, nombre), "wb") as fh:
        fh.write(datos)
    con.execute("UPDATE usuarios SET foto=? WHERE id=?", (nombre, g.user["id"]))
    db.auditar(con, g.user["id"], "usuario.foto", "Foto de perfil actualizada")
    con.commit()
    flash("Foto de perfil actualizada.", "ok")
    return redirect(url_for("configuracion"))


@app.route("/foto/<int:uid>")
@login_requerido()
def foto_usuario(uid):
    u = get_db().execute("SELECT foto FROM usuarios WHERE id=?", (uid,)).fetchone()
    if not u or not u["foto"] or not os.path.exists(os.path.join(FOTOS, u["foto"])):
        abort(404)
    return send_from_directory(FOTOS, u["foto"], max_age=0)


# ------------------------------------------------------------------ cuentas
MINUTOS_CODIGO, MAX_CODIGOS, MAX_INTENTOS = 15, 3, 5
ROLES_SOLICITABLES = {k: v for k, v in db.ROLES.items() if k != "admin"}


def _hash_codigo(codigo):
    return hashlib.sha256(("guios|" + codigo).encode()).hexdigest()


def emitir_codigo(con, correo_dest, tipo, nombre=""):
    """Genera y envía un código de 6 dígitos. Devuelve (ok, mensaje). Limita a 3 códigos cada 15 minutos."""
    desde = (datetime.now() - timedelta(minutes=MINUTOS_CODIGO)).isoformat(timespec="seconds")
    n = con.execute("SELECT COUNT(*) FROM codigos WHERE correo=? AND tipo=? AND creado>=?",
                    (correo_dest, tipo, desde)).fetchone()[0]
    if n >= MAX_CODIGOS:
        return False, f"Ya se enviaron {MAX_CODIGOS} códigos en los últimos {MINUTOS_CODIGO} minutos. Espera un momento."
    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    ahora_dt = datetime.now()
    asunto, titulo, texto = {
        "verificacion": ("Tu código para activar GUIOS EVAL", f"Hola {nombre}, verifica tu correo",
                         "Escribe este código en GUIOS EVAL para verificar tu correo. Vence en 15 minutos."),
        "recuperacion": ("Código para recuperar tu contraseña de GUIOS EVAL", "Recupera tu contraseña",
                         "Escribe este código en GUIOS EVAL para crear una contraseña nueva. Vence en 15 minutos."),
    }[tipo]
    ok, _ = mail.enviar(correo_dest, asunto, titulo, [texto], codigo)
    con.execute("UPDATE codigos SET usado=1 WHERE correo=? AND tipo=? AND usado=0", (correo_dest, tipo))
    con.execute("INSERT INTO codigos (correo, tipo, codigo_hash, codigo_visible, creado, expira) VALUES (?,?,?,?,?,?)",
                (correo_dest, tipo, _hash_codigo(codigo), None if ok else codigo,
                 ahora_dt.isoformat(timespec="seconds"),
                 (ahora_dt + timedelta(minutes=MINUTOS_CODIGO)).isoformat(timespec="seconds")))
    if ok:
        return True, f"Enviamos un código a {correo_dest}. Revisa también la carpeta de spam."
    return True, ("No hay correo configurado en este equipo: pide el código al administrador "
                  "(lo ve en Configuración → Solicitudes).")


def comprobar_codigo(con, correo_dest, tipo, codigo):
    r = con.execute("SELECT * FROM codigos WHERE correo=? AND tipo=? AND usado=0 ORDER BY id DESC LIMIT 1",
                    (correo_dest, tipo)).fetchone()
    if not r or r["expira"] < datetime.now().isoformat(timespec="seconds"):
        return False, "El código venció o no existe. Pide uno nuevo."
    if r["intentos"] >= MAX_INTENTOS:
        return False, "Demasiados intentos con este código. Pide uno nuevo."
    con.execute("UPDATE codigos SET intentos=intentos+1 WHERE id=?", (r["id"],))
    if not hmac.compare_digest(r["codigo_hash"], _hash_codigo((codigo or "").strip())):
        con.commit()
        return False, f"Código incorrecto. Te quedan {MAX_INTENTOS - r['intentos'] - 1} intentos."
    con.execute("UPDATE codigos SET usado=1 WHERE id=?", (r["id"],))
    return True, ""


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if g.user:
        return redirect(url_for("panel"))
    f = request.form
    if request.method == "POST":
        con = get_db()
        nombre, correo_n = f.get("nombre", "").strip(), f.get("correo", "").strip().lower()
        error = None
        if len(nombre) < 3 or "@" not in correo_n:
            error = "Escribe tu nombre completo y un correo válido."
        elif len(f.get("clave", "")) < 8 or f.get("clave") != f.get("clave2"):
            error = "La contraseña debe tener al menos 8 caracteres y ambas deben coincidir."
        elif f.get("rol") not in ROLES_SOLICITABLES:
            error = "Selecciona el rol que solicitas."
        existente = con.execute("SELECT * FROM usuarios WHERE correo=?", (correo_n,)).fetchone()
        if not error and existente and existente["estado"] != "pendiente_correo":
            error = "Ese correo ya está registrado. Inicia sesión o recupera tu contraseña."
        if error:
            flash(error, "error")
            return render_template("registro.html", f=f, roles=ROLES_SOLICITABLES, con_correo=mail.configurado())
        if existente:
            con.execute("UPDATE usuarios SET nombre=?, clave=?, rol_solicitado=? WHERE id=?",
                        (nombre, generate_password_hash(f["clave"]), f["rol"], existente["id"]))
            uid = existente["id"]
        else:
            uid = con.execute("INSERT INTO usuarios (nombre, correo, clave, rol, creado, estado, rol_solicitado) "
                              "VALUES (?,?,?,?,?,?,?)", (nombre, correo_n, generate_password_hash(f["clave"]), "sin_rol",
                                                         db.ahora(), "pendiente_correo", f["rol"])).lastrowid
        db.auditar(con, uid, "cuenta.registro", f"Registro de {correo_n}; solicita {db.ROLES[f['rol']]}")
        if not mail.configurado():
            # Sin correo configurado no hay verificación: la cuenta pasa directo a la aprobación del administrador
            con.execute("UPDATE usuarios SET estado='pendiente_aprobacion' WHERE id=?", (uid,))
            con.commit()
            flash("Cuenta creada. El administrador debe aprobarla y asignarte el rol; puedes iniciar sesión "
                  "para ver el estado.", "ok")
            return redirect(url_for("login"))
        ok, msg = emitir_codigo(con, correo_n, "verificacion", nombre.split()[0])
        con.commit()
        flash(msg, "ok" if ok else "error")
        return redirect(url_for("activar", correo=correo_n))
    return render_template("registro.html", f={}, roles=ROLES_SOLICITABLES, con_correo=mail.configurado())


@app.route("/activar", methods=["GET", "POST"])
def activar():
    correo_n = (request.values.get("correo") or "").strip().lower()
    if request.method == "POST":
        con = get_db()
        u = con.execute("SELECT * FROM usuarios WHERE correo=?", (correo_n,)).fetchone()
        if not u or u["estado"] != "pendiente_correo":
            flash("Esa cuenta no está esperando verificación. Inicia sesión.", "warn")
            return redirect(url_for("login"))
        if request.form.get("accion") == "reenviar":
            ok, msg = emitir_codigo(con, correo_n, "verificacion", u["nombre"].split()[0])
            con.commit()
            flash(msg, "ok" if ok else "error")
            return redirect(url_for("activar", correo=correo_n))
        ok, msg = comprobar_codigo(con, correo_n, "verificacion", request.form.get("codigo"))
        if not ok:
            con.commit()
            flash(msg, "error")
            return redirect(url_for("activar", correo=correo_n))
        con.execute("UPDATE usuarios SET estado='pendiente_aprobacion' WHERE id=?", (u["id"],))
        db.auditar(con, u["id"], "cuenta.verificada", f"Correo {correo_n} verificado; espera aprobación")
        con.commit()
        flash("Correo verificado. Tu cuenta espera la aprobación del administrador; puedes iniciar sesión para ver el estado.",
              "ok")
        return redirect(url_for("login"))
    return render_template("activar.html", correo=correo_n)


@app.route("/pendiente")
@login_requerido()
def pendiente():
    if g.user["estado"] != "pendiente_aprobacion":
        return redirect(url_for("panel"))
    return render_template("pendiente.html")


@app.route("/cambiar-clave", methods=["GET", "POST"])
@login_requerido()
def cambiar_clave():
    if request.method == "POST":
        con = get_db()
        f = request.form
        if not check_password_hash(g.user["clave"], f.get("actual", "")):
            flash("La contraseña temporal no es correcta.", "error")
        elif len(f.get("clave", "")) < 8 or f.get("clave") != f.get("clave2"):
            flash("La contraseña nueva debe tener al menos 8 caracteres y ambas deben coincidir.", "error")
        elif f.get("clave") == f.get("actual"):
            flash("La contraseña nueva debe ser distinta de la temporal.", "error")
        else:
            con.execute("UPDATE usuarios SET clave=?, cambiar_clave=0 WHERE id=?",
                        (generate_password_hash(f["clave"]), g.user["id"]))
            db.auditar(con, g.user["id"], "usuario.clave", "Cambio de la contraseña temporal")
            con.commit()
            flash("Contraseña creada. ¡Bienvenido a GUIOS EVAL!", "ok")
            return redirect(url_for("panel"))
    return render_template("cambiar_clave.html")


@app.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if not mail.configurado():
        return render_template("recuperar.html", paso=0)
    if request.method == "POST":
        con = get_db()
        correo_n = request.form.get("correo", "").strip().lower()
        u = con.execute("SELECT * FROM usuarios WHERE correo=? AND activo=1 AND estado IN "
                        "('activo','pendiente_aprobacion')", (correo_n,)).fetchone()
        if u:
            ok, msg = emitir_codigo(con, correo_n, "recuperacion", u["nombre"].split()[0])
            db.auditar(con, u["id"], "cuenta.recuperar", "Código de recuperación solicitado")
            con.commit()
            if not ok:
                flash(msg, "error")
                return redirect(url_for("recuperar"))
        return render_template("recuperar.html", paso=2, correo=correo_n)
    return render_template("recuperar.html", paso=1, correo=request.args.get("correo", ""))


@app.post("/recuperar/codigo")
def recuperar_codigo():
    con = get_db()
    f = request.form
    correo_n = f.get("correo", "").strip().lower()
    if len(f.get("clave", "")) < 8 or f.get("clave") != f.get("clave2"):
        flash("La contraseña debe tener al menos 8 caracteres y ambas deben coincidir.", "error")
        return render_template("recuperar.html", paso=2, correo=correo_n)
    ok, msg = comprobar_codigo(con, correo_n, "recuperacion", f.get("codigo"))
    u = con.execute("SELECT * FROM usuarios WHERE correo=?", (correo_n,)).fetchone()
    if not ok or not u:
        con.commit()
        flash(msg or "No se pudo validar el código.", "error")
        return render_template("recuperar.html", paso=2, correo=correo_n)
    con.execute("UPDATE usuarios SET clave=?, cambiar_clave=0 WHERE id=?", (generate_password_hash(f["clave"]), u["id"]))
    db.auditar(con, u["id"], "usuario.clave", "Contraseña restablecida con código de recuperación")
    con.commit()
    flash("Contraseña actualizada. Ya puedes iniciar sesión.", "ok")
    return redirect(url_for("login"))


def resolver_solicitud(con, f):
    uid = f.get("usuario_id", type=int)
    u = con.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
    if not u or u["estado"] not in ("pendiente_aprobacion", "pendiente_correo"):
        flash("Esa solicitud ya no está pendiente.", "warn")
        return
    if f.get("decision") == "aprobar":
        rol = f.get("rol")
        if rol not in db.ROLES:
            flash("Elige el rol que tendrá el usuario antes de aprobar.", "error")
            return
        con.execute("UPDATE usuarios SET estado='activo', rol=? WHERE id=?", (rol, uid))
        cambio = "" if rol == u["rol_solicitado"] else f" (había solicitado {db.ROLES.get(u['rol_solicitado'], '-')})"
        db.auditar(con, g.user["id"], "cuenta.aprobar", f"{u['correo']} aprobado como {db.ROLES[rol]}{cambio}")
        mail.enviar(u["correo"], "Tu cuenta de GUIOS EVAL fue aprobada", f"Hola {u['nombre'].split()[0]}, ya puedes entrar",
                      [f"El administrador aprobó tu cuenta con el rol <b>{db.ROLES[rol]}</b>.",
                       "Inicia sesión en GUIOS EVAL con tu correo y tu contraseña."])
        flash(f"{u['nombre']} aprobado como {db.ROLES[rol]}.", "ok")
    else:
        motivo = f.get("motivo", "").strip()[:200]
        con.execute("UPDATE usuarios SET estado='rechazado', motivo_rechazo=? WHERE id=?", (motivo, uid))
        db.auditar(con, g.user["id"], "cuenta.rechazar", f"{u['correo']} rechazado: {motivo or 'sin motivo'}")
        mail.enviar(u["correo"], "Tu solicitud de cuenta en GUIOS EVAL", "Solicitud no aprobada",
                      ["El administrador no aprobó tu solicitud de cuenta." + (f" Motivo: {motivo}" if motivo else "")])
        flash(f"Solicitud de {u['nombre']} rechazada.", "ok")


@app.post("/configuracion/correo")
@login_requerido("admin")
def configuracion_correo():
    ok, msg = mail.probar()
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("configuracion") + "#solicitudes")

@app.route("/configuracion", methods=["GET", "POST"])
@login_requerido()
def configuracion():
    con = get_db()
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion in ("ajustes", "usuario", "solicitud") and not con_rol():
            abort(403)
        if accion == "ajustes":
            for k in ("umbral_foda", "organizacion"):
                con.execute("INSERT OR REPLACE INTO configuracion VALUES (?,?)", (k, request.form[k]))
            db.auditar(con, g.user["id"], "config.umbrales",
                       f"Umbral FODA = {request.form['umbral_foda']}")
            flash("Ajustes institucionales guardados.", "ok")
        elif accion == "usuario":
            guardar_usuario(con, request.form)
        elif accion == "solicitud" and con_rol():
            resolver_solicitud(con, request.form)
        elif accion == "solicitud":
            abort(403)
        elif accion == "perfil":
            nombre = request.form.get("nombre", "").strip()
            correo = request.form.get("correo", "").strip().lower()
            otro = con.execute("SELECT id FROM usuarios WHERE correo=? AND id<>?", (correo, g.user["id"])).fetchone()
            if len(nombre) < 3 or "@" not in correo:
                flash("Escribe un nombre de al menos 3 letras y un correo válido.", "error")
            elif otro:
                flash("Ese correo ya lo usa otro usuario.", "error")
            elif not check_password_hash(g.user["clave"], request.form.get("actual", "")):
                flash("Para guardar los cambios escribe tu contraseña actual.", "error")
            else:
                con.execute("UPDATE usuarios SET nombre=?, correo=? WHERE id=?", (nombre, correo, g.user["id"]))
                db.auditar(con, g.user["id"], "usuario.perfil",
                           f"Perfil actualizado: {g.user['nombre']} -> {nombre}, {g.user['correo']} -> {correo}")
                flash("Perfil actualizado. Si cambiaste el correo, úsalo la próxima vez que inicies sesión.", "ok")
        elif accion == "clave":
            if check_password_hash(g.user["clave"], request.form["actual"]) and len(request.form["nueva"]) >= 6:
                con.execute("UPDATE usuarios SET clave=? WHERE id=?",
                            (generate_password_hash(request.form["nueva"]), g.user["id"]))
                db.auditar(con, g.user["id"], "usuario.clave", "Cambio de contraseña")
                flash("Contraseña actualizada.", "ok")
            else:
                flash("La contraseña actual no coincide o la nueva tiene menos de 6 caracteres.", "error")
        con.commit()
        return redirect(url_for("configuracion"))
    usuarios = con.execute("SELECT * FROM usuarios WHERE estado IN ('activo','rechazado') "
                           "ORDER BY estado, rol, nombre").fetchall()
    solicitudes = con.execute(
        "SELECT u.*, (SELECT codigo_visible FROM codigos c WHERE c.correo=u.correo AND c.usado=0 "
        "ORDER BY c.id DESC LIMIT 1) AS codigo_visible FROM usuarios u "
        "WHERE estado IN ('pendiente_aprobacion','pendiente_correo') ORDER BY estado DESC, creado").fetchall()
    recuperaciones = con.execute(
        "SELECT correo, codigo_visible, expira FROM codigos WHERE tipo='recuperacion' AND usado=0 "
        "AND codigo_visible IS NOT NULL AND expira>=? ORDER BY id DESC",
        (datetime.now().isoformat(timespec="seconds"),)).fetchall()
    return render_template("configuracion.html", usuarios=usuarios, es_admin=con_rol(),
                           umbral=db.config(con, "umbral_foda", "3"), org=db.config(con, "organizacion", ""),
                           ia_modo=db.config(con, "ia_modo", "automatico"), ia_estado=ia.estado(),
                           solicitudes=solicitudes, recuperaciones=recuperaciones, correo_ok=mail.configurado())


# --------------------------------------------------------------- auditoría
@app.route("/auditoria")
@login_requerido("auditor", "revisor", "lider")
def auditoria():
    q = request.args.get("q", "").strip()
    sql = ("SELECT a.*, u.nombre, e.codigo FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id "
           "LEFT JOIN evaluaciones e ON e.id=a.evaluacion_id")
    args = []
    if q:
        sql += " WHERE a.accion LIKE ? OR a.detalle LIKE ? OR u.nombre LIKE ? OR e.codigo LIKE ?"
        args = [f"%{q}%"] * 4
    filas = get_db().execute(sql + " ORDER BY a.id DESC LIMIT 300", args).fetchall()
    integra, total, roto = db.verificar_cadena(get_db())
    sellos = get_db().execute("SELECT s.*, e.codigo, u.nombre FROM sellos s JOIN evaluaciones e ON e.id=s.evaluacion_id "
                              "LEFT JOIN usuarios u ON u.id=s.usuario_id ORDER BY s.id DESC LIMIT 20").fetchall()
    return render_template("auditoria.html", filas=filas, q=q, integra=integra, total=total, roto=roto, sellos=sellos)


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="favicon.svg"))


@app.errorhandler(403)
def prohibido(e):
    return render_template("error.html", codigo=403, mensaje="No tienes permiso para realizar esta acción."), 403


@app.errorhandler(404)
def no_encontrado(e):
    return render_template("error.html", codigo=404, mensaje="La página que buscas no existe."), 404


db.inicializar()

if __name__ == "__main__":
    print("\n  GUIOS EVAL listo. Abre en tu navegador:  http://127.0.0.1:5000\n"
          "  Usuario de prueba: lider@guios.edu.ec  /  contraseña: guios2026\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
