"""Base de datos SQLite de GUIOS EVAL: esquema, datos iniciales y utilidades."""
import hashlib
import json
import os
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
DB_PATH = os.environ.get("GUIOS_DB", os.path.join(DATOS, "guios_eval.db"))

ROLES = {
    "admin": "Administrador de plataforma",
    "admin_catalogo": "Administrador de catálogo",
    "lider": "Líder de evaluación",
    "evaluador": "Evaluador (decisor)",
    "revisor": "Revisor / decisor final",
    "auditor": "Auditor / lector",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL,
  correo TEXT NOT NULL UNIQUE,
  clave TEXT NOT NULL,
  rol TEXT NOT NULL,
  activo INTEGER NOT NULL DEFAULT 1,
  creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catalogos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL,
  version INTEGER NOT NULL,
  estado TEXT NOT NULL DEFAULT 'borrador',
  nota TEXT,
  creado TEXT NOT NULL,
  publicado TEXT
);
CREATE TABLE IF NOT EXISTS factores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  catalogo_id INTEGER NOT NULL REFERENCES catalogos(id) ON DELETE CASCADE,
  nombre TEXT NOT NULL,
  dimension TEXT NOT NULL,
  is_valor INTEGER NOT NULL,
  alcance TEXT NOT NULL,
  descripcion TEXT,
  activo INTEGER NOT NULL DEFAULT 1,
  orden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subfactores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  factor_id INTEGER NOT NULL REFERENCES factores(id) ON DELETE CASCADE,
  texto TEXT NOT NULL,
  activo INTEGER NOT NULL DEFAULT 1,
  orden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS evaluaciones (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo TEXT NOT NULL UNIQUE,
  org_nombre TEXT NOT NULL,
  org_ruc TEXT, org_sector TEXT, org_correo TEXT,
  sw_nombre TEXT NOT NULL,
  sw_version TEXT, sw_tipo TEXT, sw_licencia TEXT, sw_proveedor TEXT, sw_descripcion TEXT,
  catalogo_id INTEGER NOT NULL REFERENCES catalogos(id),
  snapshot TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'borrador',
  lider_id INTEGER NOT NULL REFERENCES usuarios(id),
  revision_de INTEGER REFERENCES evaluaciones(id),
  decision TEXT NOT NULL DEFAULT 'no_emitida',
  decision_comentario TEXT,
  decision_por INTEGER REFERENCES usuarios(id),
  decision_fecha TEXT,
  resultado TEXT,
  creado TEXT NOT NULL,
  cerrado TEXT
);
CREATE TABLE IF NOT EXISTS participantes (
  evaluacion_id INTEGER NOT NULL REFERENCES evaluaciones(id) ON DELETE CASCADE,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  PRIMARY KEY (evaluacion_id, usuario_id)
);
CREATE TABLE IF NOT EXISTS votos_factor (
  evaluacion_id INTEGER NOT NULL REFERENCES evaluaciones(id) ON DELETE CASCADE,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  factor_key TEXT NOT NULL,
  id_valor INTEGER,
  alcance TEXT,
  PRIMARY KEY (evaluacion_id, usuario_id, factor_key)
);
CREATE TABLE IF NOT EXISTS respuestas (
  evaluacion_id INTEGER NOT NULL REFERENCES evaluaciones(id) ON DELETE CASCADE,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  sub_key TEXT NOT NULL,
  valor INTEGER,
  comentario TEXT,
  evidencia TEXT,
  actualizado TEXT,
  PRIMARY KEY (evaluacion_id, usuario_id, sub_key)
);
CREATE TABLE IF NOT EXISTS auditoria (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT NOT NULL,
  usuario_id INTEGER REFERENCES usuarios(id),
  evaluacion_id INTEGER,
  accion TEXT NOT NULL,
  detalle TEXT
);
CREATE TABLE IF NOT EXISTS calibraciones (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT NOT NULL,
  usuario_id INTEGER REFERENCES usuarios(id),
  catalogo_id INTEGER REFERENCES catalogos(id),
  desde INTEGER NOT NULL,
  hasta INTEGER NOT NULL,
  fuente TEXT NOT NULL,
  corpus INTEGER,
  umbrales TEXT,
  resultado TEXT NOT NULL,
  aplicada_en INTEGER REFERENCES catalogos(id)
);
CREATE TABLE IF NOT EXISTS terminos_factor (
  nombre TEXT PRIMARY KEY,
  terminos TEXT NOT NULL,
  ie INTEGER NOT NULL DEFAULT 3
);
CREATE TABLE IF NOT EXISTS codigos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  correo TEXT NOT NULL,
  tipo TEXT NOT NULL,
  codigo_hash TEXT NOT NULL,
  codigo_visible TEXT,
  creado TEXT NOT NULL,
  expira TEXT NOT NULL,
  intentos INTEGER NOT NULL DEFAULT 0,
  usado INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sellos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  folio TEXT NOT NULL UNIQUE,
  evaluacion_id INTEGER NOT NULL REFERENCES evaluaciones(id),
  fecha TEXT NOT NULL,
  usuario_id INTEGER REFERENCES usuarios(id),
  hash_datos TEXT NOT NULL,
  hash_archivo TEXT,
  resumen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS configuracion (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);
"""


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def conectar(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def inicializar(path=None, demo=True):
    """Crea las tablas y, si la base está vacía, carga los datos iniciales."""
    con = conectar(path)
    con.executescript(SCHEMA)
    migrar(con)
    if con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        sembrar(con, demo)
    con.commit()
    return con


# Tabla 5.3 de la tesis: total de citas (TC) e importancia de la literatura (IL)
# del corpus 2008-2019. IE = 3 para los 18 factores.
TABLA_5_3 = {
    "Compatibilidad": (33, 3), "Fiabilidad": (19, 3), "Mantenibilidad": (4, 3), "Personalización": (30, 4),
    "Prueba": (4, 3), "Documentación": (20, 1), "Portabilidad": (4, 2), "Reusabilidad": (5, 2),
    "Usabilidad": (14, 2), "Apoyo de la alta dirección": (5, 4), "Formación": (27, 4), "Soporte": (43, 4),
    "Actitud hacia el cambio": (3, 1), "Bloqueo de proveedores": (3, 2),
    "Casos de estudio de adopción FLOSS": (1, 1), "Centralidad de la tecnología de la información": (2, 1),
    "Tiempo de adopción": (2, 1), "Coste total de propiedad": (24, 4),
}


def migrar(con):
    """Agrega columnas nuevas a bases creadas con versiones anteriores."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(factores)")}
    for col in ("ie", "il", "citas", "calibracion_id"):
        if col not in cols:
            con.execute(f"ALTER TABLE factores ADD COLUMN {col} INTEGER")
    con.execute("UPDATE factores SET ie=3 WHERE ie IS NULL")
    cols_u = {r["name"] for r in con.execute("PRAGMA table_info(usuarios)")}
    for col, tipo in (("foto", "TEXT"), ("estado", "TEXT NOT NULL DEFAULT 'activo'"), ("rol_solicitado", "TEXT"),
                      ("cambiar_clave", "INTEGER NOT NULL DEFAULT 0"), ("motivo_rechazo", "TEXT")):
        if col not in cols_u:
            con.execute(f"ALTER TABLE usuarios ADD COLUMN {col} {tipo}")
    cols_a = {r["name"] for r in con.execute("PRAGMA table_info(auditoria)")}
    for col in ("hash_prev", "hash"):
        if col not in cols_a:
            con.execute(f"ALTER TABLE auditoria ADD COLUMN {col} TEXT")
    encadenar_pendientes(con)
    if "origen" not in {r["name"] for r in con.execute("PRAGMA table_info(respuestas)")}:
        con.execute("ALTER TABLE respuestas ADD COLUMN origen TEXT")
    if "resumen_ia" not in {r["name"] for r in con.execute("PRAGMA table_info(evaluaciones)")}:
        con.execute("ALTER TABLE evaluaciones ADD COLUMN resumen_ia TEXT")
    for nombre, (tc, il) in TABLA_5_3.items():
        con.execute("UPDATE factores SET citas=?, il=? WHERE nombre=? AND citas IS NULL AND calibracion_id IS NULL",
                    (tc, il, nombre))
    for k, v in {"lit_desde": "2020", "lit_hasta": "2025", "ia_modo": "automatico"}.items():
        con.execute("INSERT OR IGNORE INTO configuracion VALUES (?,?)", (k, v))


def sembrar(con, demo=True):
    usuarios = [
        ("Administrador GUIOS", "admin@guios.edu.ec", "admin"),
        ("Ana Cedeño", "catalogo@guios.edu.ec", "admin_catalogo"),
        ("Carlos Vera", "lider@guios.edu.ec", "lider"),
        ("María León", "evaluador@guios.edu.ec", "evaluador"),
        ("José Ramírez", "evaluador2@guios.edu.ec", "evaluador"),
        ("Lucía Torres", "revisor@guios.edu.ec", "revisor"),
        ("Pedro Salas", "auditor@guios.edu.ec", "auditor"),
    ]
    for nombre, correo, rol in usuarios:
        con.execute("INSERT INTO usuarios (nombre, correo, clave, rol, creado) VALUES (?,?,?,?,?)",
                    (nombre, correo, generate_password_hash("guios2026"), rol, ahora()))
    for k, v in {"umbral_foda": "3", "organizacion": "Universidad Estatal de Milagro",
                 "sesion_minutos": "30"}.items():
        con.execute("INSERT INTO configuracion VALUES (?,?)", (k, v))

    with open(os.path.join(DATOS, "catalogo_tesis.json"), encoding="utf-8") as fh:
        datos = json.load(fh)
    cur = con.execute("INSERT INTO catalogos (nombre, version, estado, nota, creado, publicado) "
                      "VALUES (?,?,?,?,?,?)",
                      ("Catálogo FLOSS", 1, "publicado",
                       "18 factores y 61 subfactores de la tesis GUIOS (Tablas 5.1, 5.3 y 5.4)",
                       ahora(), ahora()))
    cat_id = cur.lastrowid
    for i, f in enumerate(datos):
        fid = con.execute("INSERT INTO factores (catalogo_id, nombre, dimension, is_valor, alcance, "
                          "descripcion, orden) VALUES (?,?,?,?,?,?,?)",
                          (cat_id, f["nombre"], f["dimension"], f["is"], f["alcance"],
                           f["descripcion"], i)).lastrowid
        for j, s in enumerate(f["subfactores"]):
            con.execute("INSERT INTO subfactores (factor_id, texto, orden) VALUES (?,?,?)", (fid, s, j))
    con.execute("INSERT INTO auditoria (fecha, usuario_id, accion, detalle) VALUES (?,?,?,?)",
                (ahora(), 1, "catalogo.publicar", "Catálogo FLOSS v1 publicado con los datos de la tesis"))
    migrar(con)


def config(con, clave, defecto=None):
    r = con.execute("SELECT valor FROM configuracion WHERE clave=?", (clave,)).fetchone()
    return r["valor"] if r else defecto


def snapshot_catalogo(con, catalogo_id):
    """Copia congelada del catálogo para una evaluación (RF-03)."""
    factores = []
    for f in con.execute("SELECT * FROM factores WHERE catalogo_id=? AND activo=1 ORDER BY orden, id",
                         (catalogo_id,)):
        subs = [{"key": f"s{s['id']}", "texto": s["texto"]} for s in
                con.execute("SELECT * FROM subfactores WHERE factor_id=? AND activo=1 ORDER BY orden, id",
                            (f["id"],))]
        factores.append({"key": f"f{f['id']}", "nombre": f["nombre"], "dimension": f["dimension"],
                         "is_valor": f["is_valor"], "alcance": f["alcance"],
                         "ie": f["ie"], "il": f["il"], "citas": f["citas"],
                         "descripcion": f["descripcion"], "subfactores": subs})
    return factores


def huella(prev, fecha, usuario_id, evaluacion_id, accion, detalle):
    """Huella SHA-256 de un registro de auditoría encadenada con la del registro anterior."""
    texto = "|".join(str(x if x is not None else "") for x in (prev, fecha, usuario_id, evaluacion_id, accion, detalle))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def ultimo_hash(con):
    r = con.execute("SELECT hash FROM auditoria WHERE hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    return r["hash"] if r else "GENESIS"


def encadenar_pendientes(con):
    """Calcula la huella de los registros que aún no la tienen (bases anteriores a la versión 2.2)."""
    prev = ultimo_hash(con)
    for r in con.execute("SELECT * FROM auditoria WHERE hash IS NULL ORDER BY id").fetchall():
        h = huella(prev, r["fecha"], r["usuario_id"], r["evaluacion_id"], r["accion"], r["detalle"])
        con.execute("UPDATE auditoria SET hash_prev=?, hash=? WHERE id=?", (prev, h, r["id"]))
        prev = h


def verificar_cadena(con):
    """Recorre la auditoría y devuelve (íntegra, total, id_del_primer_registro_alterado)."""
    prev, total = "GENESIS", 0
    for r in con.execute("SELECT * FROM auditoria ORDER BY id"):
        total += 1
        esperado = huella(prev, r["fecha"], r["usuario_id"], r["evaluacion_id"], r["accion"], r["detalle"])
        if r["hash_prev"] != prev or r["hash"] != esperado:
            return False, total, r["id"]
        prev = r["hash"]
    return True, total, None


def auditar(con, usuario_id, accion, detalle="", evaluacion_id=None):
    fecha = ahora()
    prev = ultimo_hash(con)
    h = huella(prev, fecha, usuario_id, evaluacion_id, accion, detalle)
    con.execute("INSERT INTO auditoria (fecha, usuario_id, evaluacion_id, accion, detalle, hash_prev, hash) "
                "VALUES (?,?,?,?,?,?,?)", (fecha, usuario_id, evaluacion_id, accion, detalle, prev, h))
