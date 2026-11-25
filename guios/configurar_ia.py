"""
Asistente para configurar la IA de GUIOS EVAL. Lo ejecuta instalar.bat
(o: python -m guios.configurar_ia).

Opciones:
  1. Ya tengo mis claves de Groq y/o Gemini  -> las pide una por una y las valida.
  2. Quiero crear mis claves gratis           -> abre la página oficial de cada servicio y luego las pide.
  3. No quiero usar claves                    -> se usa la IA local (Ollama) o el motor de reglas.

Las claves se guardan en claves_guios.env, dentro de la carpeta del sistema (junto a LEEME.txt).
Ese archivo está en .gitignore y NO debe subirse a GitHub. Nunca se muestran completas en pantalla.
Si existe un archivo de una versión anterior junto a la carpeta, se traslada adentro.

Código de salida: 10 si se debe instalar la IA local, 0 si no.
"""
import getpass
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import webbrowser

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVO = os.path.join(RAIZ, "claves_guios.env")
ANTERIOR = os.path.join(os.path.dirname(RAIZ), "claves_guios.env")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GUIOS-EVAL/2.1"}

SERVICIOS = [
    {"clave": "GROQ_API_KEY", "corto": "Groq", "nombre": "Groq (recomendado: rápido y gratis)",
     "pagina": "https://console.groq.com/keys",
     "pasos": "Inicia sesión con Google o tu correo, pulsa «Create API Key», ponle un nombre y copia la clave "
              "(empieza con gsk_). Solo se muestra una vez."},
    {"clave": "GEMINI_API_KEY", "corto": "Gemini", "nombre": "Gemini de Google AI Studio (respaldo)",
     "pagina": "https://aistudio.google.com/apikey",
     "pasos": "Inicia sesión con tu cuenta de Google, pulsa «Create API key» (o «Crear clave de API») y copia la clave."},
]
INSTALAR_LOCAL, NO_INSTALAR = 10, 0


def leer():
    datos = {}
    if not os.path.exists(ARCHIVO) and os.path.exists(ANTERIOR):
        shutil.copyfile(ANTERIOR, ARCHIVO)
        print(f"  Se trasladaron las claves de {ANTERIOR} a la carpeta del sistema.")
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, encoding="utf-8") as fh:
            for linea in fh:
                if "=" in linea and not linea.strip().startswith("#"):
                    k, v = linea.split("=", 1)
                    datos[k.strip()] = v.strip()
    return datos


def guardar(datos):
    with open(ARCHIVO, "w", encoding="utf-8") as fh:
        fh.write("# Claves de GUIOS EVAL (IA y correo). NO subir a GitHub ni compartir.\n")
        for k, v in datos.items():
            if v:
                fh.write(f"{k}={v}\n")


def oculta(v):
    return v[:4] + "…" + v[-4:] if len(v) > 10 else "****"


def validar(clave, valor):
    """Comprueba la clave contra el servicio (sin gastar cuota de generación).
    Devuelve (True|False|None, mensaje). None = no se pudo comprobar (sin internet)."""
    if clave == "GROQ_API_KEY":
        req = urllib.request.Request("https://api.groq.com/openai/v1/models",
                                     headers=dict(UA, Authorization="Bearer " + valor))
    else:
        req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models",
                                     headers=dict(UA, **{"x-goog-api-key": valor}))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            json.loads(r.read().decode("utf-8"))
        return True, "clave válida"
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return False, "la clave no es válida (revisa que la copiaste completa)"
        return None, f"el servicio respondió {e.code}; se guarda igual"
    except Exception:
        return None, "no hay conexión para comprobarla; se guarda igual"


def preguntar(texto, opciones):
    while True:
        r = input(texto).strip().upper()
        if r in opciones:
            return r
        print("   Escribe " + " o ".join(opciones) + ".")


def pedir_clave(servicio, datos):
    print(f"\n   {servicio['nombre']}")
    print("   Pega la clave y pulsa Enter (no se verá al pegarla; clic derecho o Ctrl+V).")
    print("   Deja vacío y pulsa Enter para omitir este servicio.")
    while True:
        valor = getpass.getpass("   Clave: ").strip().strip('"').strip("'")
        if not valor:
            print("   Omitida.")
            return
        ok, msg = validar(servicio["clave"], valor)
        if ok is False:
            print(f"   ✗ {msg}.")
            if preguntar("   ¿Intentar de nuevo? (S/N): ", ("S", "N")) == "N":
                return
            continue
        datos[servicio["clave"]] = valor
        print(f"   ✓ {oculta(valor)}: {msg}.")
        return


def configurar_ia():
    print("\n------------------------------------------------------------")
    print("  Configuración de la IA de GUIOS EVAL")
    print("------------------------------------------------------------")
    datos = leer()
    if datos.get("GROQ_API_KEY") or datos.get("GEMINI_API_KEY"):
        print("  Ya hay claves guardadas: "
              + ", ".join(f"{s['corto']} {oculta(datos[s['clave']])}"
                          for s in SERVICIOS if datos.get(s["clave"])))
        if preguntar("  ¿Quieres cambiarlas? (S/N): ", ("S", "N")) == "N":
            return INSTALAR_LOCAL if preguntar(
                "  ¿Instalar también la IA local sin internet como respaldo (unos 2 GB)? (S/N): ",
                ("S", "N")) == "S" else NO_INSTALAR

    print("\n  ¿Cómo quieres usar la inteligencia artificial?")
    print("   1. Ya tengo mis claves de Groq y/o Gemini")
    print("   2. No tengo claves, pero quiero crearlas gratis ahora")
    print("   3. No quiero usar claves: usar solo la IA local sin internet")
    op = preguntar("  Elige 1, 2 o 3: ", ("1", "2", "3"))

    if op == "3":
        print("\n  Se usará la IA local (Ollama). Si tu PC no puede, el sistema funciona igual sin IA.")
        return INSTALAR_LOCAL

    for s in SERVICIOS:
        if op == "2":
            print(f"\n  {s['nombre']}")
            print(f"   Página oficial: {s['pagina']}")
            print(f"   {s['pasos']}")
            if preguntar("   ¿Abrir la página ahora en el navegador? (S/N): ", ("S", "N")) == "S":
                webbrowser.open(s["pagina"])
            input("   Cuando tengas la clave copiada, pulsa Enter para continuar...")
        pedir_clave(s, datos)

    guardar(datos)
    activos = [s["corto"] for s in SERVICIOS if datos.get(s["clave"])]
    if activos:
        print(f"\n  ✓ Claves guardadas en {ARCHIVO}")
        print("    Al subir el proyecto a GitHub, NO incluyas ese archivo.")
    else:
        print("\n  No se guardó ninguna clave: se usará la IA local o el motor de reglas.")
        return INSTALAR_LOCAL
    return INSTALAR_LOCAL if preguntar(
        "\n  ¿Instalar también la IA local sin internet como respaldo (unos 2 GB)? (S/N): ", ("S", "N")) == "S" \
        else NO_INSTALAR


def configurar_correo():
    """Paso opcional: cuenta de Gmail que envía los códigos de verificación y recuperación."""
    datos = leer()
    print("\n------------------------------------------------------------")
    print("  Correo para enviar códigos (opcional)")
    print("------------------------------------------------------------")
    if datos.get("GMAIL_USER") and datos.get("GMAIL_APP_PASSWORD"):
        print(f"  Ya está configurado: {datos['GMAIL_USER']}")
        if preguntar("  ¿Quieres cambiarlo? (S/N): ", ("S", "N")) == "N":
            return
    print("  Con un correo de Gmail, el sistema envía un código de 6 dígitos para verificar")
    print("  las cuentas nuevas y para recuperar contraseñas. Usa TU propio Gmail.")
    print("  Sin correo, el sistema funciona igual: las cuentas se crean sin verificar el correo")
    print("  (solo con la aprobación del administrador) y las contraseñas olvidadas las")
    print("  restablece el administrador.")
    if preguntar("  ¿Configurar tu Gmail para enviar los códigos? (S/N): ", ("S", "N")) == "N":
        print("  Listo: el sistema funcionará sin verificación por correo.")
        return
    print("\n  Gmail no acepta tu contraseña normal; necesita una «contraseña de aplicación»:")
    print("   1. Activa la verificación en dos pasos: https://myaccount.google.com/signinoptions/two-step-verification")
    print("   2. Entra a https://myaccount.google.com/apppasswords")
    print("   3. En «Nombre de la app» escribe GUIOS EVAL y pulsa Crear.")
    print("   4. Copia las 16 letras que aparecen (los espacios no importan).")
    if preguntar("   ¿Abrir la página de contraseñas de aplicación ahora? (S/N): ", ("S", "N")) == "S":
        webbrowser.open("https://myaccount.google.com/apppasswords")
    for _ in range(3):
        usuario = input("\n   Tu cuenta de Gmail (ejemplo: nombre@gmail.com): ").strip()
        clave = getpass.getpass("   Contraseña de aplicación (16 letras, no se ve al escribir): ").replace(" ", "").strip()
        if "@" in usuario and len(clave) == 16:
            break
        print("   El correo debe tener @ y la contraseña de aplicación 16 letras. Inténtalo de nuevo.")
    else:
        print("   No se guardó el correo: el sistema funcionará sin verificación. Puedes repetirlo con instalar.bat.")
        return
    datos["GMAIL_USER"], datos["GMAIL_APP_PASSWORD"] = usuario, clave
    guardar(datos)
    from guios import correo  # pylint: disable=import-outside-toplevel
    ok, msg = correo.probar()
    print(("   ✓ " if ok else "   ✗ ") + msg)
    if not ok:
        print("   Revisa el correo y la contraseña de aplicación y vuelve a ejecutar instalar.bat.")
        print("   Mientras tanto, el sistema funciona sin verificación por correo.")
        datos.pop("GMAIL_USER", None)
        datos.pop("GMAIL_APP_PASSWORD", None)
        guardar(datos)


def principal():
    if not sys.stdin or not sys.stdin.isatty():
        return NO_INSTALAR
    resultado = configurar_ia()
    configurar_correo()
    return resultado


if __name__ == "__main__":
    try:
        sys.exit(principal())
    except (KeyboardInterrupt, EOFError):
        print("\n  Configuración cancelada; puedes repetirla ejecutando instalar.bat.")
        sys.exit(NO_INSTALAR)
