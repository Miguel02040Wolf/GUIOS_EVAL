"""Pruebas de GUIOS EVAL: cálculos de la tesis y flujo completo. Ejecutar: python -m pytest -q pruebas"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GUIOS_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")

from guios import motor as engine  # noqa: E402


# ---------------- Figura 5.10 y reglas de la tesis
def test_tabla_ir_completa():
    esperado = {(4, 1): 2, (4, 2): 3, (4, 3): 3, (4, 4): 4, (3, 1): 2, (3, 2): 2, (3, 3): 3, (3, 4): 3,
                (2, 1): 1, (2, 2): 2, (2, 3): 2, (2, 4): 3, (1, 1): 1, (1, 2): 1, (1, 3): 2, (1, 4): 2}
    for (id_, is_), ir in esperado.items():
        assert engine.importancia_relativa(id_, is_) == ir


def test_ejemplo_personalizacion_tesis():
    # Tesis, sección 5.2: IE = 3 e IL = 4 dan IS = 3 (Importante)
    assert engine.importancia_relativa(3, 4) == 3


def test_relevancia():
    assert not engine.es_relevante(1)
    assert engine.es_relevante(2) and engine.es_relevante(4)
    assert not engine.es_relevante(None)


def test_foda_reglas():
    assert engine.clasificar_foda(3.0, "Interno") == "Fortaleza"
    assert engine.clasificar_foda(2.9, "Interno") == "Debilidad"
    assert engine.clasificar_foda(3.5, "Externo") == "Oportunidad"
    assert engine.clasificar_foda(1.0, "Externo") == "Amenaza"


def test_sin_evaluar_no_es_uno():
    # Error de GUIOS PRO: todo arrancaba en 1. Ahora lo no evaluado es None.
    assert engine.ponderacion_media([None, None]) is None
    assert engine.ponderacion_media([4, None, 2]) == 3.0


def test_consenso_varios_decisores():
    assert engine.consenso_id([4, 3, 2]) == 3
    assert engine.consenso_id([4, 3]) == 4          # mediana 3,5 -> redondeo usual 4
    assert engine.desacuerdo([4, 2])
    assert not engine.desacuerdo([4, 3])
    assert engine.consenso_ps([4, 3]) == 3.5


def _factor(nombre, is_v, alcance, ids, valores, dim="Tecnológica"):
    return {"nombre": nombre, "dimension": dim, "is_valor": is_v, "alcance": alcance, "ids": ids,
            "subfactores": [{"texto": f"s{i}", "valores": v} for i, v in enumerate(valores)]}


def test_recomendacion_a_b_c():
    a = engine.calcular([_factor("Compatibilidad", 3, "Externo", [4], [[4], [4]]),
                         _factor("Formación", 3, "Interno", [3], [[3], [4]], "Organizacional")])
    assert a["recomendacion"]["tipo"] == "A"
    b = engine.calcular([_factor("Compatibilidad", 3, "Externo", [4], [[4], [4]]),
                         _factor("Reusabilidad", 2, "Externo", [2], [[1], [2]])])
    assert b["recomendacion"]["tipo"] == "B"
    c = engine.calcular([_factor("Soporte", 3, "Interno", [4], [[1], [2]], "Organizacional")])
    assert c["recomendacion"]["tipo"] == "C"
    assert c["recomendacion"]["causas"][0]["factor"] == "Soporte"


def test_irrelevante_se_excluye():
    r = engine.calcular([_factor("Prueba", 1, "Externo", [1], [[1]])])
    f = r["factores"][0]
    assert f["ir"] == 1 and not f["relevante"] and f["foda"] is None
    assert r["recomendacion"] is None


# ---------------- flujo completo con el servidor
def test_flujo_completo():
    from guios import app as guios
    c = guios.app.test_client()
    assert c.post("/login", data={"correo": "lider@guios.edu.ec", "clave": "guios2026"}).status_code == 302
    r = c.post("/evaluaciones/nueva", data={"org_nombre": "Org prueba", "sw_nombre": "LibreOffice", "catalogo_id": 1})
    assert r.status_code == 302
    con = guios.db.conectar()
    ev = con.execute("SELECT * FROM evaluaciones ORDER BY id DESC").fetchone()
    snap = json.loads(ev["snapshot"])
    assert len(snap) == 18 and sum(len(f["subfactores"]) for f in snap) == 61
    eid = ev["id"]
    for f in snap:
        c.post(f"/api/evaluaciones/{eid}/voto", json={"factor_key": f["key"], "id_valor": 3})
        for s in f["subfactores"]:
            c.post(f"/api/evaluaciones/{eid}/respuesta", json={"sub_key": s["key"], "valor": 4})
    assert c.post(f"/evaluaciones/{eid}/enviar").status_code == 302
    c.get("/salir")
    c.post("/login", data={"correo": "revisor@guios.edu.ec", "clave": "guios2026"})
    c.post(f"/evaluaciones/{eid}/decision", data={"decision": "aprobada", "comentario": "Cumple todos los requisitos."})
    ev = con.execute("SELECT * FROM evaluaciones WHERE id=?", (eid,)).fetchone()
    assert ev["estado"] == "cerrada" and json.loads(ev["resultado"])["recomendacion"] == "A"
    assert c.get(f"/evaluaciones/{eid}/informe").status_code == 200
    # una evaluación cerrada ya no acepta cambios
    r = c.post(f"/api/evaluaciones/{eid}/voto", json={"factor_key": snap[0]["key"], "id_valor": 1})
    assert r.status_code == 403


def test_catalogo_crud_y_revision():
    from guios import app as guios
    c = guios.app.test_client()
    c.post("/login", data={"correo": "catalogo@guios.edu.ec", "clave": "guios2026"})
    c.post("/catalogo/nueva-version", data={"base_id": 1})
    con = guios.db.conectar()
    v2 = con.execute("SELECT id FROM catalogos WHERE estado='borrador' ORDER BY id DESC").fetchone()["id"]
    c.post(f"/catalogo/{v2}/factor", data={"nombre": "Seguridad", "dimension": "Tecnológica", "is_valor": 3,
                                          "alcance": "Externo", "descripcion": "x", "activo": "1"})
    fid = con.execute("SELECT id FROM factores WHERE catalogo_id=? AND nombre='Seguridad'", (v2,)).fetchone()["id"]
    c.post(f"/catalogo/{v2}/subfactor", data={"factor_id": fid, "texto": "Cifra los datos"})
    assert con.execute("SELECT COUNT(*) FROM subfactores WHERE factor_id=?", (fid,)).fetchone()[0] == 1
    # el catálogo publicado (v1) no se puede editar
    c.post("/catalogo/1/factor", data={"nombre": "X", "dimension": "Tecnológica", "is_valor": 1, "alcance": "Interno"})
    assert con.execute("SELECT COUNT(*) FROM factores WHERE catalogo_id=1 AND nombre='X'").fetchone()[0] == 0
    c.post(f"/catalogo/{v2}/publicar")
    assert con.execute("SELECT estado FROM catalogos WHERE id=1").fetchone()[0] == "retirado"
    # RF-15: reabrir la evaluación cerrada del test anterior como revisión nueva
    c.get("/salir")
    c.post("/login", data={"correo": "lider@guios.edu.ec", "clave": "guios2026"})
    cerrada = con.execute("SELECT id FROM evaluaciones WHERE estado='cerrada'").fetchone()["id"]
    c.post(f"/evaluaciones/{cerrada}/revision")
    nueva = con.execute("SELECT * FROM evaluaciones WHERE revision_de=?", (cerrada,)).fetchone()
    assert nueva["estado"] == "en_curso"
    assert con.execute("SELECT estado FROM evaluaciones WHERE id=?", (cerrada,)).fetchone()[0] == "cerrada"


# ---------------- Importancia de la literatura (Ecuaciones 5.1 y 5.2, Tabla 5.3)
TABLA_5_3 = [  # nombre, n subfactores, total de citas, IL esperada, IS esperada
    ("Compatibilidad", 8, 33, 3, 3), ("Fiabilidad", 5, 19, 3, 3), ("Mantenibilidad", 1, 4, 3, 3),
    ("Personalización", 6, 30, 4, 3), ("Prueba", 1, 4, 3, 3), ("Documentación", 11, 20, 1, 2),
    ("Portabilidad", 2, 4, 2, 2), ("Reusabilidad", 2, 5, 2, 2), ("Usabilidad", 4, 14, 2, 2),
    ("Apoyo de la alta dirección", 1, 5, 4, 3), ("Formación", 4, 27, 4, 3), ("Soporte", 6, 43, 4, 3),
    ("Actitud hacia el cambio", 2, 3, 1, 2), ("Bloqueo de proveedores", 1, 3, 2, 2),
    ("Casos de estudio de adopción FLOSS", 1, 1, 1, 2), ("Centralidad de la TI", 2, 2, 1, 2),
    ("Tiempo de adopción", 2, 2, 1, 2), ("Coste total de propiedad", 2, 24, 4, 3),
]


def test_reproduce_tabla_5_3():
    filas, _ = engine.calibrar([{"nombre": n, "n": ns, "citas": tc, "ie": 3} for n, ns, tc, _, _ in TABLA_5_3])
    for f, (_, _, _, il, is_) in zip(filas, TABLA_5_3):
        assert (f["il"], f["is_nueva"]) == (il, is_), f["nombre"]


def test_percentil_y_cuartiles():
    assert engine.percentil([1, 2, 3, 4, 5], 0.5) == 3
    assert engine.nivel_cuartil(0, (1, 2, 3)) == 1 and engine.nivel_cuartil(9, (1, 2, 3)) == 4
    assert engine.importancia_sugerida(3, 4) == 3 and engine.importancia_sugerida(3, 1) == 2


def test_calibracion_guardada_y_aplicar():
    from guios import app as modulo
    from guios import base_datos as db
    db.inicializar(os.environ["GUIOS_DB"])
    c = modulo.app.test_client()
    c.post("/login", data={"correo": "catalogo@guios.edu.ec", "clave": "guios2026"})
    r = c.post("/literatura/ejecutar", data={"modo": "guardado"}, follow_redirects=True)
    assert r.status_code == 200 and "Calibración #".encode() in r.data
    con = db.conectar(os.environ["GUIOS_DB"])
    cal = con.execute("SELECT * FROM calibraciones ORDER BY id DESC").fetchone()
    filas = {x["nombre"]: x for x in json.loads(cal["resultado"])}
    assert cal["corpus"] == 336 and filas["Usabilidad"]["citas"] == 36
    assert filas["Usabilidad"]["il"] == 3 and filas["Usabilidad"]["is_nueva"] == 3
    c.post(f"/literatura/{cal['id']}/aplicar", data={"publicar": "1"})
    pub = con.execute("SELECT * FROM catalogos WHERE estado='publicado'").fetchone()
    u = con.execute("SELECT * FROM factores WHERE catalogo_id=? AND nombre='Usabilidad'", (pub["id"],)).fetchone()
    assert u["is_valor"] == 3 and u["il"] == 3 and u["citas"] == 36 and u["calibracion_id"] == cal["id"]


# ---------------- Mejoras: sensibilidad, IA (sin red), coherencia y exportación
def _entrada_simple(valores):
    return [{"nombre": f"F{i}", "dimension": "Tecnológica", "is_valor": 3, "alcance": "Externo", "ids": [4],
             "subfactores": [{"texto": f"s{i}{j}", "valores": [v]} for j, v in enumerate(vs)]}
            for i, vs in enumerate(valores)]


def test_sensibilidad_detecta_cambio_unico():
    # F0 con PM 2,5 (Amenaza importante) -> C; subir una respuesta a 4 lo deja en 3,5 -> A
    s = engine.sensibilidad(_entrada_simple([[2, 3], [4, 4]]))
    assert s["base"] == "C" and s["mejoras"] and s["mejoras"][0]["nueva"] == "A"
    assert s["ruta_resultado"] == "A" and s["ruta_total"] == 1


def test_coherencia_resumen():
    from guios import ia
    assert ia.coherencia("Se emite la recomendación tipo C porque...", "C")
    assert not ia.coherencia("La recomendación B indica adoptar con matices.", "C")
    assert not ia.coherencia("Se puede adoptar sin reservas.", "C")


def test_ia_filtra_fuentes_inventadas(monkeypatch):
    from guios import ia
    ev = {"org_nombre": "UNEMI", "org_sector": "", "sw_nombre": "LibreOffice", "sw_version": "", "sw_tipo": "",
          "sw_licencia": "", "sw_proveedor": "", "sw_descripcion": ""}
    factor = {"nombre": "Usabilidad", "dimension": "Tecnológica", "alcance": "Externo",
              "subfactores": [{"key": "s1", "texto": "Es fácil de usar"}]}
    estudios = [["Estudio real", 2022, 10, "https://doi.org/10.1/real"]]
    falsa = {"propuestas": [{"key": "s1", "valor": 4, "confianza": 90, "justificacion": "ok",
                             "fuentes": ["10.1/real", "10.9/inventado"]}, {"key": "zz", "valor": 3}]}
    monkeypatch.setattr(ia, "preguntar", lambda *a, **k: (falsa, "groq", "modelo", []))
    r = ia.sugerir_subfactores(ev, factor, estudios)
    assert r["ok"] and len(r["propuestas"]) == 1
    assert r["propuestas"][0]["fuentes"] == ["https://doi.org/10.1/real"]


def test_exportar_excel_y_pdf_y_resumen_sin_ia():
    from guios import app as guios
    c = guios.app.test_client()
    c.post("/login", data={"correo": "admin@guios.edu.ec", "clave": "guios2026"})
    c.post("/configuracion/ia", data={"ia_modo": "desactivado"})
    con = guios.db.conectar()
    eid = con.execute("SELECT id FROM evaluaciones WHERE estado='cerrada'").fetchone()["id"]
    x = c.get(f"/evaluaciones/{eid}/exportar.xlsx")
    assert x.status_code == 200 and x.data[:2] == b"PK"
    p = c.get(f"/evaluaciones/{eid}/informe.pdf")
    assert p.status_code == 200 and p.data[:4] == b"%PDF"
    c.post(f"/evaluaciones/{eid}/ia/resumen")
    dato = json.loads(con.execute("SELECT resumen_ia FROM evaluaciones WHERE id=?", (eid,)).fetchone()[0])
    assert dato["fuente"].startswith("Motor de reglas") and "tipo A" in dato["resumen"] and dato["coherente"]


def test_perfil_propio_editable_por_cualquier_rol():
    from guios import app as guios
    c = guios.app.test_client()
    c.get("/salir")
    c.post("/login", data={"correo": "evaluador@guios.edu.ec", "clave": "guios2026"})
    r = c.post("/configuracion", data={"accion": "perfil", "nombre": "María León Prueba",
                                       "correo": "maria.leon@guios.edu.ec", "actual": "guios2026"})
    assert r.status_code == 302
    con = guios.db.conectar()
    u = con.execute("SELECT * FROM usuarios WHERE correo='maria.leon@guios.edu.ec'").fetchone()
    assert u and u["nombre"] == "María León Prueba" and u["rol"] == "evaluador"
    # sin contraseña no cambia, y un evaluador no puede tocar los ajustes institucionales
    c.post("/configuracion", data={"accion": "perfil", "nombre": "X", "correo": "x@x.ec", "actual": "mala"})
    assert con.execute("SELECT COUNT(*) FROM usuarios WHERE correo='x@x.ec'").fetchone()[0] == 0
    assert c.post("/configuracion", data={"accion": "ajustes", "umbral_foda": "2", "organizacion": "X"}).status_code == 403
    c.post("/configuracion", data={"accion": "clave", "actual": "guios2026", "nueva": "nueva2026"})
    c.get("/salir")
    assert c.post("/login", data={"correo": "maria.leon@guios.edu.ec", "clave": "nueva2026"}).status_code == 302


def test_alta_usuario_exige_rol_y_clave_y_foto_de_perfil():
    import io as _io
    from guios import app as guios
    c = guios.app.test_client()
    c.get("/salir")
    c.post("/login", data={"correo": "admin@guios.edu.ec", "clave": "guios2026"})
    con = guios.db.conectar()
    # sin rol elegido no se crea
    c.post("/configuracion", data={"accion": "usuario", "nombre": "Nuevo Uno", "correo": "nuevo1@x.ec", "clave": "abcdef"})
    assert con.execute("SELECT COUNT(*) FROM usuarios WHERE correo='nuevo1@x.ec'").fetchone()[0] == 0
    # sin contraseña inicial tampoco
    c.post("/configuracion", data={"accion": "usuario", "nombre": "Nuevo Uno", "correo": "nuevo1@x.ec", "rol": "evaluador"})
    assert con.execute("SELECT COUNT(*) FROM usuarios WHERE correo='nuevo1@x.ec'").fetchone()[0] == 0
    c.post("/configuracion", data={"accion": "usuario", "nombre": "Nuevo Uno", "correo": "nuevo1@x.ec",
                                   "rol": "evaluador", "clave": "abcdef"})
    assert con.execute("SELECT rol FROM usuarios WHERE correo='nuevo1@x.ec'").fetchone()[0] == "evaluador"
    # el administrador no puede quitarse su propio rol
    yo = con.execute("SELECT id FROM usuarios WHERE correo='admin@guios.edu.ec'").fetchone()[0]
    c.post("/configuracion", data={"accion": "usuario", "usuario_id": yo, "nombre": "Administrador GUIOS",
                                   "correo": "admin@guios.edu.ec", "rol": "lider", "activo": "1"})
    assert con.execute("SELECT rol FROM usuarios WHERE id=?", (yo,)).fetchone()[0] == "admin"
    # foto de perfil: acepta PNG, rechaza otros archivos
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    c.post("/perfil/foto", data={"foto": (_io.BytesIO(png), "yo.png")}, content_type="multipart/form-data")
    assert con.execute("SELECT foto FROM usuarios WHERE id=?", (yo,)).fetchone()[0] == f"usuario_{yo}.png"
    assert c.get(f"/foto/{yo}").status_code == 200
    c.post("/perfil/foto", data={"foto": (_io.BytesIO(b"MZ ejecutable"), "virus.png")}, content_type="multipart/form-data")
    assert con.execute("SELECT foto FROM usuarios WHERE id=?", (yo,)).fetchone()[0] == f"usuario_{yo}.png"
    # probar conexión no cambia el modo guardado
    c.post("/configuracion/ia", data={"ia_modo": "nube", "guardar": "1"})
    c.post("/configuracion/ia", data={"ia_modo": "local", "probar": "1"})
    assert con.execute("SELECT valor FROM configuracion WHERE clave='ia_modo'").fetchone()[0] == "nube"


def _codigo(con, correo, tipo):
    return con.execute("SELECT codigo_visible FROM codigos WHERE correo=? AND tipo=? AND usado=0 ORDER BY id DESC",
                       (correo, tipo)).fetchone()[0]


def test_registro_con_codigo_y_aprobacion_con_cambio_de_rol(monkeypatch):
    from guios import app as guios
    monkeypatch.setattr(guios.mail, "enviar", lambda *a, **k: (False, "sin correo"))
    monkeypatch.setattr(guios.mail, "configurado", lambda: True)
    c = guios.app.test_client()
    c.get("/salir")
    con = guios.db.conectar()
    datos = {"nombre": "Ana Registro", "correo": "ana@x.ec", "clave": "segura2026", "clave2": "segura2026",
             "rol": "admin_catalogo"}
    assert c.post("/registro", data=dict(datos, rol="admin")).status_code == 200   # no se puede pedir admin
    assert con.execute("SELECT COUNT(*) FROM usuarios WHERE correo='ana@x.ec'").fetchone()[0] == 0
    assert c.post("/registro", data=datos).status_code == 302
    u = con.execute("SELECT * FROM usuarios WHERE correo='ana@x.ec'").fetchone()
    assert u["estado"] == "pendiente_correo" and u["rol"] == "sin_rol" and u["rol_solicitado"] == "admin_catalogo"
    # sin verificar el correo no entra
    r = c.post("/login", data={"correo": "ana@x.ec", "clave": "segura2026"})
    assert "/activar" in r.headers["Location"]
    # código incorrecto, luego correcto
    codigo = _codigo(con, "ana@x.ec", "verificacion")
    assert codigo and len(codigo) == 6
    malo = "000000" if codigo != "000000" else "111111"
    c.post("/activar", data={"correo": "ana@x.ec", "codigo": malo})
    assert con.execute("SELECT estado FROM usuarios WHERE correo='ana@x.ec'").fetchone()[0] == "pendiente_correo"
    c.post("/activar", data={"correo": "ana@x.ec", "codigo": codigo})
    assert con.execute("SELECT estado FROM usuarios WHERE correo='ana@x.ec'").fetchone()[0] == "pendiente_aprobacion"
    # inicia sesión pero solo ve la pantalla de espera
    c.post("/login", data={"correo": "ana@x.ec", "clave": "segura2026"})
    assert "/pendiente" in c.get("/evaluaciones").headers["Location"]
    assert c.get("/pendiente").status_code == 200
    c.get("/salir")
    # el admin la ve en solicitudes y la aprueba con OTRO rol
    c.post("/login", data={"correo": "admin@guios.edu.ec", "clave": "guios2026"})
    assert b"Ana Registro" in c.get("/configuracion").data
    c.post("/configuracion", data={"accion": "solicitud", "usuario_id": u["id"], "decision": "aprobar", "rol": "evaluador"})
    u = con.execute("SELECT * FROM usuarios WHERE correo='ana@x.ec'").fetchone()
    assert u["estado"] == "activo" and u["rol"] == "evaluador"
    c.get("/salir")
    c.post("/login", data={"correo": "ana@x.ec", "clave": "segura2026"})
    assert c.get("/evaluaciones").status_code == 200


def test_rechazo_y_limite_de_codigos(monkeypatch):
    from guios import app as guios
    monkeypatch.setattr(guios.mail, "enviar", lambda *a, **k: (False, "sin correo"))
    monkeypatch.setattr(guios.mail, "configurado", lambda: True)
    c = guios.app.test_client()
    c.get("/salir")
    con = guios.db.conectar()
    c.post("/registro", data={"nombre": "Beto Rechazo", "correo": "beto@x.ec", "clave": "segura2026",
                              "clave2": "segura2026", "rol": "lider"})
    for _ in range(3):
        c.post("/activar", data={"correo": "beto@x.ec", "accion": "reenviar"})
    # 1 de registro + 2 reenvíos permitidos; el tercero se bloquea
    assert con.execute("SELECT COUNT(*) FROM codigos WHERE correo='beto@x.ec'").fetchone()[0] == 3
    c.post("/activar", data={"correo": "beto@x.ec", "codigo": _codigo(con, "beto@x.ec", "verificacion")})
    uid = con.execute("SELECT id FROM usuarios WHERE correo='beto@x.ec'").fetchone()[0]
    c.post("/login", data={"correo": "admin@guios.edu.ec", "clave": "guios2026"})
    c.post("/configuracion", data={"accion": "solicitud", "usuario_id": uid, "decision": "rechazar",
                                   "motivo": "No pertenece a la institución"})
    c.get("/salir")
    r = c.post("/login", data={"correo": "beto@x.ec", "clave": "segura2026"})
    assert r.status_code == 200 and "No pertenece a la institución" in r.get_data(as_text=True)


def test_clave_temporal_y_recuperacion(monkeypatch):
    from guios import app as guios
    monkeypatch.setattr(guios.mail, "enviar", lambda *a, **k: (False, "sin correo"))
    monkeypatch.setattr(guios.mail, "configurado", lambda: True)
    c = guios.app.test_client()
    c.get("/salir")
    con = guios.db.conectar()
    c.post("/login", data={"correo": "admin@guios.edu.ec", "clave": "guios2026"})
    c.post("/configuracion", data={"accion": "usuario", "nombre": "Carla Temporal", "correo": "carla@x.ec",
                                   "rol": "revisor", "clave": "temp123"})
    c.get("/salir")
    c.post("/login", data={"correo": "carla@x.ec", "clave": "temp123"})
    assert "/cambiar-clave" in c.get("/panel").headers["Location"]
    c.post("/cambiar-clave", data={"actual": "temp123", "clave": "temp123", "clave2": "temp123"})  # igual: no
    assert con.execute("SELECT cambiar_clave FROM usuarios WHERE correo='carla@x.ec'").fetchone()[0] == 1
    c.post("/cambiar-clave", data={"actual": "temp123", "clave": "propia2026", "clave2": "propia2026"})
    assert con.execute("SELECT cambiar_clave FROM usuarios WHERE correo='carla@x.ec'").fetchone()[0] == 0
    assert c.get("/panel").status_code == 200
    c.get("/salir")
    # olvidó la contraseña
    c.post("/recuperar", data={"correo": "carla@x.ec"})
    codigo = _codigo(con, "carla@x.ec", "recuperacion")
    c.post("/recuperar/codigo", data={"correo": "carla@x.ec", "codigo": codigo, "clave": "otra2026x", "clave2": "otra2026x"})
    assert c.post("/login", data={"correo": "carla@x.ec", "clave": "otra2026x"}).status_code == 302
    # un correo inexistente no revela nada ni crea códigos
    c.get("/salir")
    assert c.post("/recuperar", data={"correo": "nadie@x.ec"}).status_code == 200
    assert con.execute("SELECT COUNT(*) FROM codigos WHERE correo='nadie@x.ec'").fetchone()[0] == 0


def test_sello_de_integridad_y_verificacion():
    import io as _io
    from guios import app as guios
    c = guios.app.test_client()
    c.get("/salir")
    c.post("/login", data={"correo": "admin@guios.edu.ec", "clave": "guios2026"})
    con = guios.db.conectar()
    eid = con.execute("SELECT id FROM evaluaciones WHERE estado='cerrada'").fetchone()["id"]
    pdf = c.get(f"/evaluaciones/{eid}/informe.pdf").data
    s = con.execute("SELECT * FROM sellos WHERE evaluacion_id=? ORDER BY id DESC", (eid,)).fetchone()
    assert s["folio"].startswith("GE-") and s["folio"].encode() in pdf
    c.get("/salir")   # la verificación es pública
    ok = c.post("/verificar", data={"pdf": (_io.BytesIO(pdf), "i.pdf")}, content_type="multipart/form-data")
    assert "auténtico" in ok.get_data(as_text=True)
    alterado = pdf[:-40] + b"%% editado " + pdf[-40:]
    assert alterado != pdf
    r = c.post("/verificar", data={"pdf": (_io.BytesIO(alterado), "i.pdf")}, content_type="multipart/form-data")
    texto = r.get_data(as_text=True)
    assert "NO coincide" in texto and s["folio"] in texto
    assert "registrado" in c.get(f"/verificar?folio={s['folio']}").get_data(as_text=True)
    assert "no encontrado" in c.get("/verificar?folio=GE-0000000000").get_data(as_text=True)


def test_auditoria_encadenada_detecta_alteracion():
    from guios import app as guios
    con = guios.db.conectar()
    integra, total, _ = guios.db.verificar_cadena(con)
    assert integra and total > 5
    fila = con.execute("SELECT id, detalle FROM auditoria ORDER BY id LIMIT 1 OFFSET 2").fetchone()
    con.execute("UPDATE auditoria SET detalle='alterado' WHERE id=?", (fila["id"],))
    integra, _, roto = guios.db.verificar_cadena(con)
    assert not integra and roto == fila["id"]
    con.execute("UPDATE auditoria SET detalle=? WHERE id=?", (fila["detalle"], fila["id"]))
    con.commit()
    assert guios.db.verificar_cadena(con)[0]


def test_matriz_de_riesgos_y_tendencia():
    res = engine.calcular([_factor("Soporte", 4, "Externo", [4], [[1], [2]]),
                           _factor("Formación", 3, "Interno", [3], [[2], [3]], "Organizacional"),
                           _factor("Usabilidad", 3, "Externo", [4], [[4], [4]])])
    m = engine.matriz_riesgos(res, 3.0)
    assert [r["factor"] for r in m["riesgos"]] == ["Soporte", "Formación"]
    soporte = m["riesgos"][0]
    assert soporte["probabilidad"] == 4 and soporte["respuesta"] == "Transferir" and soporte["nivel"] in ("Alto", "Medio")
    assert sum(m["conteo"].values()) == 2
    t = engine.tendencia({"2018": 1, "2019": 1, "2020": 4, "2021": 4}, {"2018": 50, "2019": 50, "2020": 50, "2021": 50},
                         2018, 2021)
    assert t["etiqueta"] == "Sube" and t["pendiente"] > 0 and t["pct_anterior"] == 2.0 and t["pct_reciente"] == 8.0


def test_paginas_nuevas_cargan():
    from guios import app as guios
    c = guios.app.test_client()
    c.get("/salir")
    for url in ("/login", "/registro", "/recuperar", "/verificar", "/activar?correo=a@b.ec"):
        assert c.get(url).status_code == 200, url
    c.post("/login", data={"correo": "admin@guios.edu.ec", "clave": "guios2026"})
    c.post("/evaluaciones/nueva", data={"org_nombre": "Org riesgos", "sw_nombre": "GIMP", "catalogo_id": 1})
    con = guios.db.conectar()
    ev = con.execute("SELECT * FROM evaluaciones ORDER BY id DESC").fetchone()
    for f in json.loads(ev["snapshot"]):
        c.post(f"/api/evaluaciones/{ev['id']}/voto", json={"factor_key": f["key"], "id_valor": 4})
        for s in f["subfactores"]:
            c.post(f"/api/evaluaciones/{ev['id']}/respuesta", json={"sub_key": s["key"], "valor": 2})
    pagina = c.get(f"/evaluaciones/{ev['id']}/paso-4").get_data(as_text=True)
    assert "Matriz de riesgos" in pagina and "Alto" in pagina
    assert c.get(f"/evaluaciones/{ev['id']}/exportar.xlsx").status_code == 200
    assert "Tendencia en la literatura" in c.get("/literatura").get_data(as_text=True)
    assert "Cadena de auditoría íntegra" in c.get("/auditoria").get_data(as_text=True)


def test_sin_correo_configurado_no_pide_verificacion(monkeypatch):
    from guios import app as guios
    monkeypatch.setattr(guios.mail, "configurado", lambda: False)
    c = guios.app.test_client()
    c.get("/salir")
    con = guios.db.conectar()
    r = c.post("/registro", data={"nombre": "Eva Sin Correo", "correo": "eva@x.ec", "clave": "segura2026",
                                  "clave2": "segura2026", "rol": "evaluador"})
    assert "/login" in r.headers["Location"]
    u = con.execute("SELECT * FROM usuarios WHERE correo='eva@x.ec'").fetchone()
    assert u["estado"] == "pendiente_aprobacion" and u["rol"] == "sin_rol"
    assert con.execute("SELECT COUNT(*) FROM codigos WHERE correo='eva@x.ec'").fetchone()[0] == 0
    # recuperar contraseña indica acudir al administrador
    assert "administrador" in c.get("/recuperar").get_data(as_text=True)
    # el administrador asigna una contraseña temporal y la persona debe cambiarla
    c.post("/login", data={"correo": "admin@guios.edu.ec", "clave": "guios2026"})
    c.post("/configuracion", data={"accion": "solicitud", "usuario_id": u["id"], "decision": "aprobar", "rol": "evaluador"})
    c.post("/configuracion", data={"accion": "usuario", "usuario_id": u["id"], "nombre": "Eva Sin Correo",
                                   "correo": "eva@x.ec", "rol": "evaluador", "activo": "1", "clave": "temp99"})
    c.get("/salir")
    c.post("/login", data={"correo": "eva@x.ec", "clave": "temp99"})
    assert "/cambiar-clave" in c.get("/panel").headers["Location"]
