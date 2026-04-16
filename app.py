"""
MrBogart Support Chat
---------------------
Chat de soporte al cliente con 4 opciones de solicitud.
Guarda cada solicitud en SQLite y envía confirmación por email.
"""

import json
import os
import smtplib
import sqlite3
import uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from anthropic import Anthropic
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

client = Anthropic()
DB_FILE = "solicitudes.db"
SUPPORT_EMAIL = "ayuda@mrbogart.com"

# Historial de conversaciones en memoria (clave: session id)
conversations: dict[str, list] = {}

TIPO_LABELS = {
    "accesos": "Solicitud de accesos",
    "facturas": "Solicitud de facturas",
    "asistencia_tecnica": "Asistencia técnica",
    "ampliar_espacio": "Ampliación de espacio",
    "traslado_web": "Traslado de página web",
}

SYSTEM_PROMPT = """Eres el asistente virtual de soporte de MrBogart. \
Tu misión es ayudar al cliente a tramitar su solicitud de forma clara y eficiente.

FLUJO OBLIGATORIO:
1. Saluda brevemente y pide el nombre completo y correo electrónico del cliente.
2. Cuando tengas ambos datos, preséntale el menú numerado:
   1. Solicitar accesos
   2. Solicitar facturas
   3. Asistencia técnica
   4. Ampliar espacio de correo o alojamiento
   5. Solicitar traslado de página web
3. Según la opción elegida, haz preguntas una a una para recoger la información necesaria.
4. Al finalizar, muestra un resumen claro y pide confirmación al cliente.
5. Cuando el cliente confirme, llama a guardar_solicitud.

DATOS A RECOGER POR OPCIÓN:

▸ Solicitar accesos:
  - Sistema o plataforma a la que necesita acceso
  - Usuario o nombre de cuenta (si ya existe)
  - Nivel de acceso necesario
  - Motivo de la solicitud

▸ Solicitar facturas:
  - Período o rango de fechas
  - Número de factura concreto (si lo conoce)
  - Datos fiscales o razón social (si aplica)

▸ Asistencia técnica:
  - Descripción del problema
  - Desde cuándo ocurre
  - Urgencia: alta, media o baja
  - Pasos ya intentados

▸ Ampliar espacio de correo o alojamiento:
  - Tipo: correo electrónico o alojamiento web
  - Dominio o cuenta afectada
  - Espacio actual aproximado
  - Espacio adicional necesario

▸ Solicitar traslado de página web:
  - Dominio de la página web que desea trasladar

NORMAS:
- Habla siempre en español, tono profesional y cercano.
- Haz una pregunta a la vez, no abrumes al cliente.
- Sé conciso en tus respuestas.
- Tras guardar la solicitud, despídete con un mensaje breve y cálido del estilo:
  "¡Listo! Hemos recibido tu solicitud correctamente. En breve nos pondremos en contacto contigo. ¡Hasta pronto!"

TOOLS = [
    {
        "name": "guardar_solicitud",
        "description": (
            "Guarda la solicitud en la base de datos y envía correo de confirmación "
            "al cliente y al equipo de soporte. Llama a esta función solo cuando el "
            "cliente haya confirmado que el resumen es correcto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre completo del cliente",
                },
                "email": {
                    "type": "string",
                    "description": "Correo electrónico del cliente",
                },
                "tipo": {
                    "type": "string",
                    "enum": ["accesos", "facturas", "asistencia_tecnica", "ampliar_espacio", "traslado_web"],
                    "description": "Tipo de solicitud",
                },
                "detalles": {
                    "type": "object",
                    "description": "Información específica recogida según el tipo de solicitud",
                },
                "resumen": {
                    "type": "string",
                    "description": "Resumen completo en texto para incluir en los correos",
                },
            },
            "required": ["nombre", "email", "tipo", "detalles", "resumen"],
        },
    }
]


# ── Base de datos ─────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha    DATETIME DEFAULT CURRENT_TIMESTAMP,
                nombre   TEXT NOT NULL,
                email    TEXT NOT NULL,
                tipo     TEXT NOT NULL,
                detalles TEXT NOT NULL,
                resumen  TEXT NOT NULL,
                estado   TEXT DEFAULT 'pendiente'
            )
        """)


def save_to_db(nombre: str, email: str, tipo: str, detalles: dict, resumen: str) -> int:
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute(
            "INSERT INTO solicitudes (nombre, email, tipo, detalles, resumen) VALUES (?, ?, ?, ?, ?)",
            (nombre, email, tipo, json.dumps(detalles, ensure_ascii=False), resumen),
        )
        return cur.lastrowid


# ── Correo ────────────────────────────────────────────────────────────────────

def send_emails(nombre: str, email: str, tipo: str, resumen: str, solicitud_id: int) -> None:
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    from_display = f"Soporte MrBogart <{smtp_user}>"

    tipo_label = TIPO_LABELS.get(tipo, tipo)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

    def make_msg(to: str, subject: str, body: str) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_display
        msg["To"] = to
        msg.attach(MIMEText(body, "plain", "utf-8"))
        return msg

    # Email al cliente
    cuerpo_cliente = (
        f"Hola {nombre},\n\n"
        f"Hemos recibido tu solicitud. Aquí tienes el resumen:\n\n"
        f"{resumen}\n\n"
        f"Referencia: #{solicitud_id}  ·  {fecha}\n\n"
        f"Nos pondremos en contacto contigo en breve.\n\n"
        f"Un saludo,\nEl equipo de MrBogart"
    )
    msg_cliente = make_msg(email, f"Confirmación de solicitud — {tipo_label}", cuerpo_cliente)

    # Email al soporte interno
    cuerpo_soporte = (
        f"Nueva solicitud recibida\n"
        f"{'─' * 40}\n"
        f"Referencia : #{solicitud_id}\n"
        f"Fecha      : {fecha}\n"
        f"Cliente    : {nombre}\n"
        f"Email      : {email}\n"
        f"Tipo       : {tipo_label}\n"
        f"{'─' * 40}\n\n"
        f"{resumen}"
    )
    msg_soporte = make_msg(
        SUPPORT_EMAIL,
        f"Nueva solicitud #{solicitud_id}: {tipo_label} — {nombre}",
        cuerpo_soporte,
    )

    use_ssl = smtp_port == 465
    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

    with smtp_cls(smtp_host, smtp_port) as smtp:
        if not use_ssl:
            smtp.starttls()
        smtp.login(smtp_user, smtp_pass)
        smtp.sendmail(smtp_user, [email], msg_cliente.as_string())
        smtp.sendmail(smtp_user, [SUPPORT_EMAIL], msg_soporte.as_string())


# ── Lógica del chat ───────────────────────────────────────────────────────────

def get_history() -> list:
    """Devuelve el historial de la conversación actual."""
    sid = session.get("sid")
    if not sid:
        sid = str(uuid.uuid4())
        session["sid"] = sid
    return conversations.setdefault(sid, [])


def call_claude(history: list) -> tuple[str, bool]:
    """
    Llama a Claude con el historial actual.
    Gestiona el uso de herramientas internamente.
    Devuelve (texto_respuesta, solicitud_guardada).
    """
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=history,
    )

    # Claude quiere guardar la solicitud
    if response.stop_reason == "tool_use":
        tool_block = next(b for b in response.content if b.type == "tool_use")
        args = tool_block.input

        try:
            sid = save_to_db(
                nombre=args["nombre"],
                email=args["email"],
                tipo=args["tipo"],
                detalles=args["detalles"],
                resumen=args["resumen"],
            )
            send_emails(
                nombre=args["nombre"],
                email=args["email"],
                tipo=args["tipo"],
                resumen=args["resumen"],
                solicitud_id=sid,
            )
            tool_result = f"Solicitud #{sid} guardada y correos enviados correctamente."
        except Exception as exc:
            tool_result = f"Error al procesar la solicitud: {exc}"

        # Devolvemos el resultado a Claude para que dé el mensaje de cierre
        history.append({"role": "assistant", "content": response.content})
        history.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": tool_result,
            }],
        })

        followup = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        )
        reply = next(b.text for b in followup.content if b.type == "text")
        history.append({"role": "assistant", "content": reply})
        return reply, True

    # Respuesta normal
    reply = next(b.text for b in response.content if b.type == "text")
    history.append({"role": "assistant", "content": reply})
    return reply, False


# ── Rutas ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    session.pop("sid", None)
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    """Devuelve el saludo inicial del asistente."""
    history = get_history()
    history.append({"role": "user", "content": "Hola"})
    reply, _ = call_claude(history)
    session.modified = True
    return jsonify({"reply": reply})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "Mensaje vacío"}), 400

    history = get_history()
    history.append({"role": "user", "content": text})
    reply, saved = call_claude(history)
    session.modified = True
    return jsonify({"reply": reply, "saved": saved})


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
