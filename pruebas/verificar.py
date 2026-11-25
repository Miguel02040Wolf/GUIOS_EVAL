"""
Verificación completa de GUIOS EVAL en este computador.
Se ejecuta al final de instalar.bat (o con: python pruebas/verificar.py). No modifica la base de datos:
trabaja sobre una copia temporal. Muestra el resultado en pantalla y lo guarda en
pruebas/ultima_verificacion.txt.
"""
# pylint: disable=protected-access
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # carpeta del proyecto
LOG = os.path.join(BASE, "pruebas", "ultima_verificacion.txt")
lineas, fallos = [], []


def out(msg, ok=None):
    marca = "" if ok is None else ("[OK]    " if ok else "[FALLA] ")
    if ok == "aviso":
        marca = "[AVISO] "
    t = marca + msg
    print(t, flush=True)
    lineas.append(t)
    if ok is False:
        fallos.append(msg)


def paso(titulo):
    out("")
    out("== " + titulo)


paso("1. Python y bibliotecas")
out(f"Python {sys.version.split()[0]} en {sys.executable}", sys.version_info >= (3, 10))
for mod in ("flask", "openpyxl", "fpdf", "segno"):
    try:
        __import__(mod)
        out(f"Biblioteca {mod} instalada", True)
    except ImportError:
        out(f"Biblioteca {mod} NO instalada (ejecuta instalar.bat)", False)

paso("2. Pruebas automatizadas (pytest)")
try:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "pruebas"], cwd=BASE,
                       capture_output=True, text=True, timeout=300, check=False)
    ultima = (r.stdout.strip().splitlines() or ["sin salida"])[-1]
    out("pytest: " + ultima, r.returncode == 0)
    if r.returncode != 0:
        out(r.stdout[-1500:])
except Exception as e:
    out(f"No se pudo ejecutar pytest: {e}", False)

paso("3. Pantallas y exportaciones (sobre una copia de la base de datos)")
tmp = os.path.join(tempfile.mkdtemp(), "copia.db")
shutil.copy(os.path.join(BASE, "datos", "guios_eval.db"), tmp)
os.environ["GUIOS_DB"] = tmp
sys.path.insert(0, BASE)
from guios import app as guios  # noqa: E402
from guios import ia, literatura  # noqa: E402

c = guios.app.test_client()


def entrar(correo):
    c.get("/salir")
    return c.post("/login", data={"correo": correo, "clave": "guios2026"}).status_code == 302


out("Inicio de sesión del administrador", entrar("admin@guios.edu.ec"))
for ruta in ("/panel", "/evaluaciones", "/catalogo", "/literatura", "/configuracion", "/auditoria", "/comparar",
             "/evaluaciones/1/paso-4", "/evaluaciones/1/informe", "/registro", "/recuperar", "/verificar"):
    out(f"GET {ruta}", c.get(ruta).status_code == 200)
r = c.get("/evaluaciones/1/informe.pdf")
out("Informe PDF con sello de integridad (folio y QR)", r.status_code == 200 and r.data[:4] == b"%PDF" and b"GE-" in r.data)
import io as _io  # noqa: E402
v = c.post("/verificar", data={"pdf": (_io.BytesIO(r.data), "i.pdf")}, content_type="multipart/form-data")
out("Verificación del informe recién emitido", "auténtico" in v.get_data(as_text=True))
cadena = guios.db.verificar_cadena(guios.db.conectar(tmp))
out(f"Cadena de auditoría: {cadena[1]} registros encadenados", cadena[0])
pagina4 = c.get("/evaluaciones/1/paso-4").get_data(as_text=True)
out("Matriz de riesgos del piloto EV-0001", "Matriz de riesgos" in pagina4)
out("Tendencia 2008-2025 en la página de literatura", "Tendencia en la literatura" in c.get("/literatura").get_data(as_text=True))
r = c.get("/evaluaciones/1/exportar.xlsx")
out("Exportación Excel", r.status_code == 200 and r.data[:2] == b"PK")
con = guios.db.conectar(tmp)
ev = con.execute("SELECT * FROM evaluaciones WHERE codigo='EV-0001'").fetchone()
with guios.app.test_request_context():
    s = guios.engine.sensibilidad(guios.construir_entrada(ev))
out(f"Análisis de sensibilidad del piloto: {s['base']} -> B con {s['ruta_criticos_total']} subfactores, "
    f"A con {s['ruta_total']}", s["base"] == "C")

paso("4. Literatura científica en vivo (OpenAlex)")
try:
    d = literatura.obtener(literatura.url_consulta(2020, 2025, literatura.TERMINOS["Usabilidad"], 1))
    out(f"OpenAlex responde: {d['meta']['count']} estudios 2020-2025 para Usabilidad", True)
except Exception as e:
    out(f"OpenAlex no responde ({str(e)[:80]}). Se usará la corrida guardada 2020-2025.", "aviso")

paso("5. Asistente de IA en la nube")
est = ia.estado()
out("Clave de Groq encontrada" if est["groq"] else "Sin clave de Groq (opcional; se configura con instalar.bat)",
    True if est["groq"] else "aviso")
out("Clave de Gemini encontrada" if est["gemini"] else "Sin clave de Gemini (opcional; se configura con instalar.bat)",
    True if est["gemini"] else "aviso")
claves = ia._leer_claves()
for nombre, fn in (("Groq", ia._groq), ("Gemini", ia._gemini)):
    k = "GROQ_API_KEY" if nombre == "Groq" else "GEMINI_API_KEY"
    if not claves.get(k):
        continue
    t = time.time()
    try:
        texto, modelo = fn("Responde solo con JSON.", 'Devuelve {"ok": true}', claves)
        out(f"{nombre} responde con {modelo} en {time.time() - t:.1f} s", '"ok"' in texto)
    except Exception as e:
        out(f"{nombre} no respondió: {str(e)[:150]}", False)

paso("6. IA local sin internet (Ollama)")
exe = shutil.which("ollama") or next((p for p in (
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
    r"C:\Program Files\Ollama\ollama.exe") if os.path.exists(p)), None)
out(f"Ollama instalado: {exe}" if exe else "IA local no instalada (opcional)", True if exe else "aviso")
servicio = False
modelos = []
try:
    with urllib.request.urlopen(est["ollama_url"].rstrip("/") + "/api/tags", timeout=5) as r:
        modelos = [m["name"] for m in json.loads(r.read().decode())["models"]]
    servicio = True
except Exception:
    pass
out("Servicio de Ollama activo en " + est["ollama_url"], servicio if exe else None)
if servicio:
    out("Modelos descargados: " + (", ".join(modelos) or "ninguno"))
    tiene = any(m.split(":")[0] + ":" + (m.split(":")[1] if ":" in m else "latest") == est["ollama_modelo"]
                or m == est["ollama_modelo"] for m in modelos)
    out(f"Modelo {est['ollama_modelo']} descargado", tiene)
    if tiene:
        t = time.time()
        try:
            texto, modelo = ia._ollama("Responde solo con JSON.", 'Devuelve {"ok": true}', claves)
            out(f"IA local responde con {modelo} en {time.time() - t:.1f} s", '"ok"' in texto)
        except Exception as e:
            out(f"IA local no respondió: {str(e)[:150]}", False)

paso("7. Prueba real del asistente: sugerencias para el factor Usabilidad de EV-0004")
with guios.app.test_request_context():
    ev4 = con.execute("SELECT * FROM evaluaciones WHERE codigo='EV-0004'").fetchone()
    if ev4:
        fac = next(f for f in json.loads(ev4["snapshot"]) if f["nombre"] == "Usabilidad")
        t = time.time()
        r = ia.sugerir_subfactores(ev4, fac, guios.estudios_factor("Usabilidad"), "automatico")
        if r["ok"]:
            out(f"{r['proveedor']} ({r['modelo']}) sugirió {len(r['propuestas'])} respuestas en {time.time() - t:.1f} s", True)
            for p in r["propuestas"]:
                out(f"   {p['valor']} ({p['confianza']} %): {p['justificacion'][:110]}")
        else:
            hay_ia = est["groq"] or est["gemini"] or (exe and servicio)
            if hay_ia:
                out("Ningún proveedor respondió: " + " | ".join(r.get("errores") or []), False)
            else:
                out("Sin IA configurada: el resumen y el plan los redacta el motor de reglas", "aviso")

paso("8. Correo para códigos de verificación")
from guios import correo  # noqa: E402  pylint: disable=wrong-import-position
if correo.configurado():
    ok_c, msg_c = correo.probar()
    out(msg_c, ok_c)
else:
    out("Sin correo configurado: las cuentas nuevas se crean sin verificación por correo", "aviso")

out("")
out("RESULTADO: " + ("TODO FUNCIONA" if not fallos else f"{len(fallos)} punto(s) con problemas: " + "; ".join(fallos)))
with open(LOG, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lineas))
print("\nResultado guardado en " + LOG)
