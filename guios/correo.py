"""
Envío de correos de GUIOS EVAL (códigos de verificación, recuperación y avisos).

Usa una cuenta de Gmail con contraseña de aplicación, leída de claves_guios.env:
  GMAIL_USER=cuenta@gmail.com
  GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx   (16 letras; no es la contraseña normal)
Si no está configurado, las funciones devuelven False y el sistema muestra el código
al administrador para que lo entregue en persona.
"""
import smtplib
import ssl
from email.message import EmailMessage

from guios import ia

SERVIDOR, PUERTO = "smtp.gmail.com", 587


def credenciales():
    c = ia._leer_claves()  # pylint: disable=protected-access
    usuario = (c.get("GMAIL_USER") or "").strip()
    clave = (c.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    return (usuario, clave) if usuario and clave else (None, None)


def configurado():
    return credenciales()[0] is not None


def probar():
    """Inicia sesión en el servidor sin enviar nada. Devuelve (ok, mensaje)."""
    usuario, clave = credenciales()
    if not usuario:
        return False, "No hay correo configurado (GMAIL_USER y GMAIL_APP_PASSWORD en claves_guios.env)."
    try:
        with smtplib.SMTP(SERVIDOR, PUERTO, timeout=15) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(usuario, clave)
        return True, f"Correo listo: {usuario}"
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail rechazó la contraseña de aplicación. Créala de nuevo en myaccount.google.com/apppasswords."
    except Exception as e:
        return False, f"No se pudo conectar con Gmail: {str(e)[:120]}"


def enviar(destino, asunto, titulo, parrafos, codigo=None):
    """Envía un correo con formato. Devuelve (ok, mensaje)."""
    usuario, clave = credenciales()
    if not usuario:
        return False, "correo no configurado"
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = f"GUIOS EVAL <{usuario}>"
    msg["To"] = destino
    texto = "\n\n".join([titulo] + parrafos + ([f"Código: {codigo}"] if codigo else []))
    msg.set_content(texto + "\n\nGUIOS EVAL · Evaluación de adopción de software libre")
    bloque = (f'<div style="font-size:30px;letter-spacing:8px;font-weight:700;background:#EFF6FF;color:#1D4ED8;'
              f'padding:14px 18px;border-radius:10px;display:inline-block;margin:10px 0">{codigo}</div>') if codigo else ""
    html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:520px;margin:auto;color:#0F172A">'
            f'<div style="background:#1E2A44;color:#fff;padding:16px 22px;border-radius:12px 12px 0 0;font-weight:800;'
            f'font-size:18px">GUIOS <span style="background:#60A5FA;color:#16203A;font-size:11px;padding:2px 7px;'
            f'border-radius:5px">EVAL</span></div><div style="border:1px solid #E2E8F0;border-top:0;padding:20px 22px;'
            f'border-radius:0 0 12px 12px"><h2 style="margin:0 0 10px;font-size:18px">{titulo}</h2>'
            + "".join(f'<p style="margin:8px 0;line-height:1.5">{p}</p>' for p in parrafos) + bloque +
            '<p style="color:#5B6A7D;font-size:12px;margin-top:18px">Si no solicitaste esto, ignora este mensaje.</p>'
            '</div></div>')
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(SERVIDOR, PUERTO, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(usuario, clave)
            s.send_message(msg)
        return True, "enviado"
    except Exception as e:
        return False, str(e)[:150]
