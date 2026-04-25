"""
╔══════════════════════════════════════════════════════════════════╗
║       CTadvanced  —  License Server  v3.0  —  CASTTWEAKS®       ║
║   Backend Flask para Render.com                                   ║
║                                                                   ║
║   BASE DE DATOS: Google Sheets (persistente, gratuito)           ║
║                                                                   ║
║   Variables de entorno requeridas en Render:                     ║
║     OWNER_SECRET    → mismo valor que en el cliente              ║
║     OWNER_API_KEY   → clave secreta para rutas de owner          ║
║     GSHEET_ID       → ID de tu Google Sheet                      ║
║     GSHEET_CREDS    → JSON completo de la cuenta de servicio     ║
║     MAIL_USER       → cuenta Gmail remitente                     ║
║     MAIL_PASS       → contraseña de aplicación de Google         ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os, json, hmac, hashlib, base64, time, threading
from datetime import date, datetime, timedelta
from functools import wraps
from collections import defaultdict
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Configuración ────────────────────────────────────────────────
OWNER_SECRET  = os.environ.get("OWNER_SECRET",  "CASTTWEAKS_SECRET_2024_DONT_SHARE")
OWNER_API_KEY = os.environ.get("OWNER_API_KEY", "CHANGE_THIS_IN_RENDER_ENV")
GSHEET_ID     = os.environ.get("GSHEET_ID",     "")
GSHEET_CREDS  = os.environ.get("GSHEET_CREDS",  "")

LICENSE_TYPES = ["Basic", "Pro", "Lifetime"]

_rate_limit: dict = defaultdict(list)
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX    = 10

# ── Caché en memoria para reducir llamadas a Sheets ─────────────
_db_cache      = None
_cache_ts      = 0.0
_cache_lock    = threading.Lock()
CACHE_TTL      = 10   # segundos — recarga si han pasado más de 10s


# ══════════════════════════════════════════════════════════════════
#  GOOGLE SHEETS — capa de persistencia
# ══════════════════════════════════════════════════════════════════

def _get_sheets_client():
    """Devuelve un cliente gspread autenticado, o None si no hay credenciales."""
    if not GSHEET_ID or not GSHEET_CREDS:
        return None, None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds_dict = json.loads(GSHEET_CREDS)
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sh     = client.open_by_key(GSHEET_ID)
        return client, sh
    except Exception as e:
        print(f"[SHEETS] Error conectando: {e}", flush=True)
        return None, None


def _get_or_create_sheet(sh, name: str):
    """Obtiene una hoja por nombre, la crea si no existe."""
    try:
        return sh.worksheet(name)
    except Exception:
        ws = sh.add_worksheet(title=name, rows=2000, cols=2)
        # Cabecera mínima: clave | valor JSON
        ws.append_row(["key", "value"])
        return ws


def _load_db() -> dict:
    """Carga la BD desde Google Sheets. Usa caché en memoria para peticiones frecuentes."""
    global _db_cache, _cache_ts

    with _cache_lock:
        now = time.time()
        if _db_cache is not None and (now - _cache_ts) < CACHE_TTL:
            return json.loads(json.dumps(_db_cache))   # copia profunda

    empty = {
        "licenses":       {},
        "hwid_blacklist": {},
        "failed_log":     [],
        "discount_codes": {},
        "settings": {
            "maintenance":     False,
            "maintenance_msg": "El servicio está en mantenimiento. Vuelve pronto.",
        },
    }

    _, sh = _get_sheets_client()
    if sh is None:
        # Sin Sheets → fallback a fichero local (dev)
        try:
            with open("licenses.json", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return empty

    try:
        ws      = _get_or_create_sheet(sh, "db")
        records = ws.get_all_values()          # [[key, value], ...]
        db      = json.loads(json.dumps(empty))

        for row in records[1:]:               # saltar cabecera
            if len(row) >= 2 and row[0] and row[1]:
                section = row[0]
                try:
                    db[section] = json.loads(row[1])
                except Exception:
                    pass

        with _cache_lock:
            _db_cache = json.loads(json.dumps(db))
            _cache_ts = time.time()

        return db

    except Exception as e:
        print(f"[SHEETS] Error leyendo: {e}", flush=True)
        return empty


def _save_db(db: dict):
    """Guarda la BD completa en Google Sheets (una fila por sección)."""
    global _db_cache, _cache_ts

    # Actualizar caché inmediatamente
    with _cache_lock:
        _db_cache = json.loads(json.dumps(db))
        _cache_ts = time.time()

    _, sh = _get_sheets_client()
    if sh is None:
        # Fallback local
        try:
            with open("licenses.json", "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return

    try:
        ws = _get_or_create_sheet(sh, "db")

        # Construir mapa sección → valor
        sections = ["licenses", "hwid_blacklist", "failed_log", "discount_codes", "settings"]
        new_rows = [["key", "value"]]
        for s in sections:
            new_rows.append([s, json.dumps(db.get(s, {}), ensure_ascii=False)])

        # Limpiar hoja y reescribir (simple y fiable)
        ws.clear()
        ws.update("A1", new_rows)

    except Exception as e:
        print(f"[SHEETS] Error guardando: {e}", flush=True)
        # Guardar en fichero local como backup de emergencia
        try:
            with open("licenses_backup.json", "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def _ensure_keys(db: dict) -> dict:
    db.setdefault("licenses",       {})
    db.setdefault("hwid_blacklist", {})
    db.setdefault("failed_log",     [])
    db.setdefault("discount_codes", {})
    db.setdefault("settings", {
        "maintenance":     False,
        "maintenance_msg": "El servicio está en mantenimiento. Vuelve pronto.",
    })
    return db


# ══════════════════════════════════════════════════════════════════
#  CRIPTOGRAFÍA
# ══════════════════════════════════════════════════════════════════

def _sign(payload: str) -> str:
    return hmac.new(
        OWNER_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def generate_license(username: str, days: int, hwid: str = "") -> str:
    exp     = (date.today() + timedelta(days=days)).isoformat()
    payload = f"{username}|{exp}|{hwid}"
    sig     = _sign(payload)
    raw     = f"{payload}||{sig}"
    key     = base64.b64encode(raw.encode()).decode().rstrip("=")
    return "-".join(key[i:i+8] for i in range(0, len(key), 8))


def decode_key(key: str):
    try:
        raw = key.replace("-", "").replace(" ", "")
        pad = 4 - len(raw) % 4
        if pad != 4:
            raw += "=" * pad
        decoded      = base64.b64decode(raw).decode()
        payload, sig = decoded.rsplit("||", 1)
        parts        = payload.split("|")
        username, exp_str, hwid = parts[0], parts[1], parts[2]
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        return {"username": username, "expires": exp_str, "hwid": hwid}
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  HELPERS DE SEGURIDAD
# ══════════════════════════════════════════════════════════════════

def _get_ip() -> str:
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _rate_limit[ip] = [t for t in _rate_limit[ip] if now - t < RATE_LIMIT_WINDOW]
    _rate_limit[ip].append(now)
    return len(_rate_limit[ip]) > RATE_LIMIT_MAX


def _log_failed(db: dict, ip: str, key_fragment: str, reason: str):
    db["failed_log"].append({
        "ts":           datetime.utcnow().isoformat(),
        "ip":           ip,
        "key_fragment": key_fragment[:20] if key_fragment else "",
        "reason":       reason,
    })
    if len(db["failed_log"]) > 500:
        db["failed_log"] = db["failed_log"][-500:]


# ══════════════════════════════════════════════════════════════════
#  DECORADORES
# ══════════════════════════════════════════════════════════════════

def require_owner(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-Owner-Key", "")
        if not hmac.compare_digest(api_key, OWNER_API_KEY):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════
#  EMAIL
# ══════════════════════════════════════════════════════════════════

def _send_license_email(to_email, username, key, plan_name, expires, is_free=False):
    """Envía la clave al comprador con el instalador adjunto en ZIP. Falla silenciosamente si no hay credenciales."""
    import smtplib, ssl, zipfile, io
    from email.mime.multipart import MIMEMultipart
    from email.mime.text      import MIMEText
    from email.mime.base      import MIMEBase
    from email                import encoders

    mail_user = os.environ.get("MAIL_USER", "")
    mail_pass = os.environ.get("MAIL_PASS", "")
    if not mail_user or not mail_pass:
        return

    mail_from = os.environ.get("MAIL_FROM", mail_user)
    duracion  = "&#8734; Lifetime" if expires and int(expires[:4]) > 2090 else expires
    year      = datetime.utcnow().year

    plan_color = {"Basic": "#7c3aed", "Pro": "#9b30ff", "Lifetime": "#e040fb"}.get(plan_name, "#9b30ff")
    plan_icon  = {"Basic": "&#9889;", "Pro": "&#128640;", "Lifetime": "&#9854;"}.get(plan_name, "&#127918;")

    html_body = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#07000f;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#07000f;padding:48px 16px;">
<tr><td align="center">

<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;border-radius:24px;overflow:hidden;box-shadow:0 0 80px rgba(155,48,255,0.3);">

  <!-- HEADER -->
  <tr>
    <td style="background:linear-gradient(135deg,#5b10c6 0%,#9b30ff 50%,#e040fb 100%);padding:44px 48px 36px;text-align:center;">
      <p style="margin:0;font-size:11px;letter-spacing:6px;color:rgba(255,255,255,0.65);text-transform:uppercase;font-weight:600;">Bienvenido a</p>
      <p style="margin:10px 0 0;font-size:38px;font-weight:900;letter-spacing:7px;color:#ffffff;text-transform:uppercase;text-shadow:0 0 40px rgba(255,255,255,0.35);">CASTTWEAKS&#174;</p>
      <p style="margin:12px 0 0;font-size:12px;color:rgba(255,255,255,0.75);letter-spacing:3px;text-transform:uppercase;font-weight:500;">Optimizacion Premium para tu PC</p>
      <div style="margin:24px auto 0;width:60px;height:2px;background:rgba(255,255,255,0.3);border-radius:2px;"></div>
    </td>
  </tr>

  <!-- BADGE DE PLAN -->
  <tr>
    <td style="background:#0f0022;padding:28px 48px 0;text-align:center;">
      <span style="display:inline-block;background:{plan_color}22;border:1px solid {plan_color}99;border-radius:50px;padding:10px 28px;font-size:13px;font-weight:700;color:{plan_color};letter-spacing:2px;text-transform:uppercase;">
        {plan_icon} &nbsp; Licencia {plan_name}
      </span>
    </td>
  </tr>

  <!-- SALUDO -->
  <tr>
    <td style="background:#0f0022;padding:28px 48px 0;">
      <p style="margin:0 0 10px;font-size:24px;font-weight:700;color:#f5edff;">Hola, {username} &#128075;</p>
      <p style="margin:0;font-size:15px;color:#a08cc0;line-height:1.8;">
        {'&#161;Gracias por tu confianza!' if not is_free else '&#161;Aqui tienes tu acceso gratuito!'}&nbsp;
        Tu licencia <strong style="color:#e040fb;">{plan_name}</strong> ya esta activa.<br>
        Encontraras tu clave abajo y el instalador adjunto en un archivo <strong style="color:#fff;">ZIP</strong>.
      </p>
    </td>
  </tr>

  <!-- CLAVE DE LICENCIA -->
  <tr>
    <td style="background:#0f0022;padding:24px 48px 0;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {plan_color}77;border-radius:16px;overflow:hidden;background:{plan_color}11;">
        <tr>
          <td style="padding:14px 24px 6px;">
            <p style="margin:0;font-size:10px;letter-spacing:3px;text-transform:uppercase;color:{plan_color};font-weight:700;">&#128273; &nbsp; Tu clave de licencia</p>
          </td>
        </tr>
        <tr>
          <td style="padding:4px 24px 18px;">
            <p style="margin:0;font-size:14px;font-family:'Courier New',Courier,monospace;color:#e040fb;word-break:break-all;font-weight:700;letter-spacing:1.5px;line-height:1.8;">{key}</p>
          </td>
        </tr>
        <tr>
          <td style="background:{plan_color}18;padding:10px 24px;border-top:1px solid {plan_color}33;">
            <p style="margin:0;font-size:11px;color:#8a6aaa;">&#128161; Guarda esta clave en un lugar seguro, la necesitaras para activar el programa.</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- DETALLES -->
  <tr>
    <td style="background:#0f0022;padding:20px 48px 0;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #1e0040;border-radius:14px;overflow:hidden;">
        <tr style="background:#160030;">
          <td colspan="2" style="padding:12px 20px;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#7a5a9a;font-weight:600;border-bottom:1px solid #1e0040;">Detalles de tu licencia</td>
        </tr>
        <tr>
          <td style="padding:14px 20px;font-size:13px;color:#8a6aaa;border-bottom:1px solid #160030;">&#128230; Plan</td>
          <td style="padding:14px 20px;font-size:13px;color:#f0e8ff;text-align:right;font-weight:600;border-bottom:1px solid #160030;">{plan_name}</td>
        </tr>
        <tr>
          <td style="padding:14px 20px;font-size:13px;color:#8a6aaa;">&#128197; Valido hasta</td>
          <td style="padding:14px 20px;font-size:13px;color:#e040fb;text-align:right;font-weight:700;">{duracion}</td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- INSTRUCCIONES -->
  <tr>
    <td style="background:#0f0022;padding:20px 48px 0;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #1e0040;border-radius:14px;overflow:hidden;">
        <tr style="background:#160030;">
          <td style="padding:12px 20px;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#7a5a9a;font-weight:600;border-bottom:1px solid #1e0040;">
            &#128187; &nbsp; Como instalar CastTweaks&#174;
          </td>
        </tr>
        <tr>
          <td style="padding:20px;">
            <table cellpadding="0" cellspacing="0" width="100%">
              <tr>
                <td width="30" style="vertical-align:top;padding-top:2px;">
                  <span style="display:inline-block;width:24px;height:24px;background:{plan_color};border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:#fff;">1</span>
                </td>
                <td style="padding-left:12px;font-size:13px;color:#a08cc0;line-height:1.7;padding-bottom:14px;">
                  Descarga el archivo <strong style="color:#fff;">CastTweaks.zip</strong> adjunto a este correo y descomprimelo.
                </td>
              </tr>
              <tr>
                <td width="30" style="vertical-align:top;padding-top:2px;">
                  <span style="display:inline-block;width:24px;height:24px;background:{plan_color};border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:#fff;">2</span>
                </td>
                <td style="padding-left:12px;font-size:13px;color:#a08cc0;line-height:1.7;padding-bottom:14px;">
                  Haz clic derecho en <strong style="color:#fff;">CastTweaks.exe</strong> y selecciona <strong style="color:#fff;">Ejecutar como administrador</strong>.
                </td>
              </tr>
              <tr>
                <td width="30" style="vertical-align:top;padding-top:2px;">
                  <span style="display:inline-block;width:24px;height:24px;background:{plan_color};border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:#fff;">3</span>
                </td>
                <td style="padding-left:12px;font-size:13px;color:#a08cc0;line-height:1.7;">
                  Introduce la clave de licencia cuando el programa te la pida.
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- SOPORTE -->
  <tr>
    <td style="background:#0f0022;padding:28px 48px 36px;">
      <p style="margin:0 0 20px;font-size:13px;color:#8a6aaa;line-height:1.8;">
        &#191;Algun problema con la activacion? Estamos aqui para ayudarte.
      </p>
      <table cellpadding="0" cellspacing="0">
        <tr>
          <td style="background:linear-gradient(135deg,#7c3aed,#e040fb);border-radius:12px;padding:14px 32px;">
            <a href="mailto:casttweaks@gmail.com" style="color:#ffffff;text-decoration:none;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;">
              &#9993; &nbsp; Contactar soporte
            </a>
          </td>
        </tr>
      </table>
      <p style="margin:28px 0 0;font-size:14px;color:#9980bb;line-height:1.8;">
        Un saludo,<br>
        <strong style="color:#e040fb;font-size:15px;">El equipo de CastTweaks&#174;</strong>
      </p>
    </td>
  </tr>

  <!-- FOOTER -->
  <tr>
    <td style="background:#080015;padding:20px 48px;border-top:1px solid #1e0040;text-align:center;">
      <p style="margin:0;font-size:11px;color:#3d2560;letter-spacing:1px;">&#169; {year} CastTweaks&#174; &middot; Todos los derechos reservados</p>
      <p style="margin:6px 0 0;font-size:11px;color:#3d2560;">casttweaks@gmail.com</p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    # ── Construir mensaje ────────────────────────────────────────────────
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"[CastTweaks] Tu licencia {plan_name} + Instalador"
    msg["From"]    = f"CastTweaks(r) <{mail_from}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # Adjuntar CastTweaks.exe comprimido en ZIP (Gmail bloquea .exe directo)
    exe_name  = "CastTweaks.exe"
    zip_name  = "CastTweaks.zip"
    exe_path  = os.path.join(os.path.dirname(os.path.abspath(__file__)), exe_name)

    if os.path.isfile(exe_path):
        try:
            # Crear ZIP en memoria
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(exe_path, exe_name)
            zip_buffer.seek(0)

            part = MIMEBase("application", "zip")
            part.set_payload(zip_buffer.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{zip_name}"')
            msg.attach(part)
            print(f"[MAIL] ZIP adjuntado correctamente ({zip_name})", flush=True)
        except Exception as e:
            print(f"[MAIL] Error creando ZIP: {e}", flush=True)
    else:
        print(f"[MAIL] AVISO: No se encontro {exe_name} en {exe_path}", flush=True)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as srv:
            srv.login(mail_user, mail_pass)
            srv.sendmail(mail_from, to_email, msg.as_string())
        print(f"[MAIL] Correo enviado a {to_email}", flush=True)
    except Exception as e:
        print(f"[MAIL ERROR] {e}", flush=True)


# ══════════════════════════════════════════════════════════════════
#  RUTAS PÚBLICAS
# ══════════════════════════════════════════════════════════════════

@app.route("/api/health", methods=["GET"])
def health():
    db = _ensure_keys(_load_db())
    return jsonify({
        "status":      "ok",
        "ts":          datetime.utcnow().isoformat(),
        "maintenance": db["settings"].get("maintenance", False),
        "storage":     "google_sheets" if GSHEET_ID else "local_file",
    })


@app.route("/api/verify", methods=["POST"])
def verify():
    """Body: { key, hwid }"""
    ip   = _get_ip()
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    hwid = (data.get("hwid") or "").strip()

    if _is_rate_limited(ip):
        return jsonify({"valid": False, "error": "Demasiados intentos. Espera un momento."}), 429

    db = _ensure_keys(_load_db())

    if db["settings"].get("maintenance"):
        msg = db["settings"].get("maintenance_msg", "Servicio en mantenimiento.")
        return jsonify({"valid": False, "error": f"🔧 {msg}"})

    if not key:
        return jsonify({"valid": False, "error": "Clave vacía."}), 400

    if hwid:
        bl_entry = db["hwid_blacklist"].get(hwid.upper())
        if bl_entry:
            reason = bl_entry.get("reason", "PC bloqueado.")
            _log_failed(db, ip, key, f"HWID bloqueado: {reason}")
            _save_db(db)
            return jsonify({"valid": False, "error": f"Este ordenador ha sido bloqueado: {reason}"})

    decoded = decode_key(key)
    if not decoded:
        _log_failed(db, ip, key, "Firma inválida")
        _save_db(db)
        return jsonify({"valid": False, "error": "Firma inválida. Clave incorrecta o modificada."})

    entry = db["licenses"].get(key)
    if entry is None:
        _log_failed(db, ip, key, "Clave no registrada")
        _save_db(db)
        return jsonify({"valid": False, "error": "Clave no registrada. Contacta al owner."})

    if entry.get("revoked"):
        reason = entry.get("revoke_reason", "Sin motivo.")
        _log_failed(db, ip, key, f"Revocada: {reason}")
        _save_db(db)
        return jsonify({"valid": False, "error": f"Licencia revocada: {reason}"})

    try:
        exp_date  = date.fromisoformat(decoded["expires"])
        days_left = (exp_date - date.today()).days
        if days_left < 0:
            _log_failed(db, ip, key, "Expirada")
            _save_db(db)
            return jsonify({"valid": False, "error": f"Licencia expirada el {decoded['expires']}."})
    except Exception:
        return jsonify({"valid": False, "error": "Fecha de expiración inválida."})

    max_devices   = entry.get("max_devices", 1)
    bound_devices = entry.get("bound_devices", [])
    hwid_in_key   = decoded.get("hwid", "")

    if hwid:
        if hwid_in_key:
            if hwid_in_key.upper() != hwid.upper():
                _log_failed(db, ip, key, "HWID fijo no coincide")
                _save_db(db)
                return jsonify({"valid": False, "error": "Esta clave está registrada en otro ordenador."})
        else:
            hwid_up  = hwid.upper()
            bound_up = [h.upper() for h in bound_devices]
            if hwid_up not in bound_up:
                if len(bound_devices) >= max_devices:
                    _log_failed(db, ip, key, f"Límite {max_devices} dispositivos")
                    _save_db(db)
                    return jsonify({
                        "valid": False,
                        "error": (
                            f"Esta clave ya está activada en {max_devices} dispositivo(s). "
                            "Contacta al owner para cambiar de PC."
                        )
                    })
                bound_devices.append(hwid)
                entry["bound_devices"] = bound_devices
                if not entry.get("first_use"):
                    entry["first_use"] = datetime.utcnow().isoformat()

    entry["last_seen"] = datetime.utcnow().isoformat()
    entry["last_ip"]   = ip
    entry["uses"]      = entry.get("uses", 0) + 1
    _save_db(db)

    return jsonify({
        "valid":        True,
        "username":     decoded["username"],
        "expires":      decoded["expires"],
        "days_left":    days_left,
        "license_type": entry.get("license_type", "Basic"),
        "max_devices":  max_devices,
    })


# ══════════════════════════════════════════════════════════════════
#  RUTAS OWNER — LICENCIAS
# ══════════════════════════════════════════════════════════════════

@app.route("/api/issue", methods=["POST"])
@require_owner
def issue():
    data         = request.get_json(silent=True) or {}
    username     = (data.get("username") or "").strip()
    days         = int(data.get("days", 30))
    hwid         = (data.get("hwid") or "").strip()
    note         = (data.get("note") or "").strip()
    license_type = (data.get("license_type") or "Basic").strip()
    max_devices  = int(data.get("max_devices", 1))

    if not username:
        return jsonify({"error": "username requerido"}), 400
    if days <= 0:
        return jsonify({"error": "days debe ser > 0"}), 400
    if license_type not in LICENSE_TYPES:
        license_type = "Basic"
    max_devices = max(1, min(max_devices, 10))

    key = generate_license(username, days, hwid)
    exp = (date.today() + timedelta(days=days)).isoformat()

    db = _ensure_keys(_load_db())
    db["licenses"][key] = {
        "username":      username,
        "expires":       exp,
        "note":          note,
        "license_type":  license_type,
        "max_devices":   max_devices,
        "bound_devices": [hwid] if hwid else [],
        "issued_at":     datetime.utcnow().isoformat(),
        "revoked":       False,
        "revoke_reason": "",
        "uses":          0,
        "last_seen":     "",
        "last_ip":       "",
        "first_use":     "",
    }
    _save_db(db)
    return jsonify({"key": key, "username": username, "expires": exp, "license_type": license_type})


@app.route("/api/revoke", methods=["POST"])
@require_owner
def revoke():
    data   = request.get_json(silent=True) or {}
    key    = (data.get("key") or "").strip()
    reason = (data.get("reason") or "Revocada por el owner.").strip()
    db     = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    db["licenses"][key]["revoked"]       = True
    db["licenses"][key]["revoke_reason"] = reason
    db["licenses"][key]["revoked_at"]    = datetime.utcnow().isoformat()
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/unrevoke", methods=["POST"])
@require_owner
def unrevoke():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    db   = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    db["licenses"][key]["revoked"]       = False
    db["licenses"][key]["revoke_reason"] = ""
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/licenses", methods=["GET"])
@require_owner
def list_licenses():
    db = _ensure_keys(_load_db())
    return jsonify({"licenses": db["licenses"]})


@app.route("/api/delete", methods=["POST"])
@require_owner
def delete_license():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    db   = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    del db["licenses"][key]
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/reset_hwid", methods=["POST"])
@require_owner
def reset_hwid():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    db   = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    db["licenses"][key]["bound_devices"] = []
    db["licenses"][key]["first_use"]     = ""
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/edit_note", methods=["POST"])
@require_owner
def edit_note():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    note = (data.get("note") or "").strip()
    db   = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    db["licenses"][key]["note"] = note
    _save_db(db)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
#  RUTAS OWNER — BLACKLIST HWIDs
# ══════════════════════════════════════════════════════════════════

@app.route("/api/blacklist_hwid", methods=["POST"])
@require_owner
def blacklist_hwid():
    data   = request.get_json(silent=True) or {}
    hwid   = (data.get("hwid") or "").strip().upper()
    reason = (data.get("reason") or "Bloqueado por el owner.").strip()
    if not hwid:
        return jsonify({"error": "hwid requerido"}), 400
    db = _ensure_keys(_load_db())
    db["hwid_blacklist"][hwid] = {"reason": reason, "added_at": datetime.utcnow().isoformat()}
    _save_db(db)
    return jsonify({"ok": True, "hwid": hwid})


@app.route("/api/unblacklist_hwid", methods=["POST"])
@require_owner
def unblacklist_hwid():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip().upper()
    db   = _ensure_keys(_load_db())
    db["hwid_blacklist"].pop(hwid, None)
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/hwid_blacklist", methods=["GET"])
@require_owner
def get_hwid_blacklist():
    db = _ensure_keys(_load_db())
    return jsonify({"blacklist": db["hwid_blacklist"]})


# ══════════════════════════════════════════════════════════════════
#  RUTAS OWNER — LOG Y CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════

@app.route("/api/failed_log", methods=["GET"])
@require_owner
def get_failed_log():
    db = _ensure_keys(_load_db())
    return jsonify({"log": list(reversed(db["failed_log"]))})


@app.route("/api/clear_failed_log", methods=["POST"])
@require_owner
def clear_failed_log():
    db = _ensure_keys(_load_db())
    db["failed_log"] = []
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/maintenance", methods=["POST"])
@require_owner
def set_maintenance():
    data    = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    msg     = (data.get("message") or "El servicio está en mantenimiento. Vuelve pronto.").strip()
    db      = _ensure_keys(_load_db())
    db["settings"]["maintenance"]     = enabled
    db["settings"]["maintenance_msg"] = msg
    _save_db(db)
    return jsonify({"ok": True, "maintenance": enabled})


@app.route("/api/settings", methods=["GET"])
@require_owner
def get_settings():
    db = _ensure_keys(_load_db())
    return jsonify({"settings": db["settings"]})


# ══════════════════════════════════════════════════════════════════
#  RUTAS OWNER — CÓDIGOS DE DESCUENTO
# ══════════════════════════════════════════════════════════════════

@app.route("/api/discount_codes", methods=["GET"])
@require_owner
def list_discount_codes():
    db = _ensure_keys(_load_db())
    return jsonify({"codes": db["discount_codes"]})


@app.route("/api/discount_codes/create", methods=["POST"])
@require_owner
def create_discount_code():
    data        = request.get_json(silent=True) or {}
    code        = (data.get("code") or "").strip().upper()
    discount    = float(data.get("discount", 0))
    max_uses    = int(data.get("max_uses", 0))
    expires_at  = (data.get("expires_at") or "").strip()
    plans       = data.get("plans") or []
    description = (data.get("description") or "").strip()

    if not code:
        return jsonify({"error": "El código no puede estar vacío."}), 400
    if not (0 < discount <= 100):
        return jsonify({"error": "El descuento debe estar entre 1 y 100."}), 400

    db = _ensure_keys(_load_db())
    if code in db["discount_codes"]:
        return jsonify({"error": f"El código '{code}' ya existe."}), 400

    db["discount_codes"][code] = {
        "discount":    discount,
        "max_uses":    max_uses,
        "uses":        0,
        "expires_at":  expires_at,
        "plans":       [p.lower() for p in plans],
        "description": description,
        "active":      True,
        "created_at":  datetime.utcnow().isoformat(),
    }
    _save_db(db)
    return jsonify({"ok": True, "code": code})


@app.route("/api/discount_codes/delete", methods=["POST"])
@require_owner
def delete_discount_code():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    db   = _ensure_keys(_load_db())
    if code not in db["discount_codes"]:
        return jsonify({"error": "Código no encontrado."}), 404
    del db["discount_codes"][code]
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/discount_codes/toggle", methods=["POST"])
@require_owner
def toggle_discount_code():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    db   = _ensure_keys(_load_db())
    if code not in db["discount_codes"]:
        return jsonify({"error": "Código no encontrado."}), 404
    db["discount_codes"][code]["active"] = not db["discount_codes"][code].get("active", True)
    _save_db(db)
    return jsonify({"ok": True, "active": db["discount_codes"][code]["active"]})


@app.route("/api/discount_codes/validate", methods=["POST"])
def validate_discount_code():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    plan = (data.get("plan") or "").strip().lower()

    if not code:
        return jsonify({"valid": False, "message": "Código vacío."}), 400

    db    = _ensure_keys(_load_db())
    entry = db["discount_codes"].get(code)

    if not entry:
        return jsonify({"valid": False, "message": "Código no válido."})
    if not entry.get("active", True):
        return jsonify({"valid": False, "message": "Este código está desactivado."})
    if entry["max_uses"] > 0 and entry["uses"] >= entry["max_uses"]:
        return jsonify({"valid": False, "message": "Este código ha alcanzado el límite de usos."})
    if entry.get("expires_at"):
        try:
            if date.fromisoformat(entry["expires_at"]) < date.today():
                return jsonify({"valid": False, "message": "Este código ha expirado."})
        except Exception:
            pass
    if entry.get("plans") and plan and plan not in entry["plans"]:
        return jsonify({"valid": False, "message": f"Código no válido para el plan '{plan}'."})

    return jsonify({
        "valid":    True,
        "discount": entry["discount"],
        "message":  f"✓ {entry['discount']}% de descuento aplicado.",
    })


# ══════════════════════════════════════════════════════════════════
#  RUTA PÚBLICA — Clave gratuita (descuento 100%)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/issue_free", methods=["POST"])
def issue_free():
    ip   = _get_ip()
    data = request.get_json(silent=True) or {}

    username      = (data.get("username")      or "").strip()
    email         = (data.get("email")         or "").strip()
    days          = int(data.get("days", 30))
    license_type  = (data.get("license_type")  or "Basic").strip().capitalize()
    discount_code = (data.get("discount_code") or "").strip().upper()

    if not username:
        return jsonify({"error": "username requerido"}), 400
    if not email:
        return jsonify({"error": "email requerido"}), 400
    if license_type not in LICENSE_TYPES:
        return jsonify({"error": "Tipo de licencia inválido"}), 400
    if days <= 0 or days > 36500:
        return jsonify({"error": "días inválidos"}), 400
    if not discount_code:
        return jsonify({"error": "Se requiere un código de descuento del 100%."}), 400

    if _is_rate_limited(ip):
        return jsonify({"error": "Demasiadas peticiones. Espera un momento."}), 429

    db = _ensure_keys(_load_db())

    if db["settings"].get("maintenance"):
        msg = db["settings"].get("maintenance_msg", "Servicio en mantenimiento.")
        return jsonify({"error": f"🔧 {msg}"}), 503

    dc = db["discount_codes"].get(discount_code)
    if not dc:
        return jsonify({"error": "Código de descuento no válido."}), 400
    if not dc.get("active", True):
        return jsonify({"error": "Este código está desactivado."}), 400
    if dc["max_uses"] > 0 and dc["uses"] >= dc["max_uses"]:
        return jsonify({"error": "Este código ha alcanzado el límite de usos."}), 400
    if dc.get("expires_at"):
        try:
            if date.fromisoformat(dc["expires_at"]) < date.today():
                return jsonify({"error": "Este código ha expirado."}), 400
        except Exception:
            pass
    if dc.get("plans") and license_type.lower() not in dc["plans"]:
        return jsonify({"error": f"Código no válido para el plan '{license_type}'."}), 400
    if int(dc["discount"]) != 100:
        return jsonify({"error": "Este código no cubre el precio completo."}), 400

    db["discount_codes"][discount_code]["uses"] += 1

    max_devices = _MAX_DEVICES.get(license_type, 1)
    key         = generate_license(username, days, "")
    exp         = (date.today() + timedelta(days=days)).isoformat()

    db["licenses"][key] = {
        "username":      username,
        "expires":       exp,
        "note":          f"Clave gratuita · email:{email} · Dto:{discount_code}(100%)",
        "license_type":  license_type,
        "max_devices":   max_devices,
        "bound_devices": [],
        "issued_at":     datetime.utcnow().isoformat(),
        "revoked":       False,
        "revoke_reason": "",
        "uses":          0,
        "last_seen":     "",
        "last_ip":       ip,
        "first_use":     "",
        "email":         email,
        "paypal_order":  "FREE",
    }
    _save_db(db)

    _send_license_email(
        to_email  = email,
        username  = username,
        key       = key,
        plan_name = license_type,
        expires   = exp,
        is_free   = True,
    )

    return jsonify({"key": key, "username": username, "expires": exp, "license_type": license_type})


# ══════════════════════════════════════════════════════════════════
#  RUTA PÚBLICA — Licencia tras pago PayPal verificado
# ══════════════════════════════════════════════════════════════════

_used_orders: set = set()

_PLAN_BASE   = {"Basic": 5.0,  "Pro": 10.0, "Lifetime": 15.0}
_PLAN_XPM    = {"Basic": 1.0,  "Pro": 1.5,  "Lifetime": 0.0}
_MAX_DEVICES = {"Basic": 1,    "Pro": 2,     "Lifetime": 3}


def _expected_price(license_type: str, days: int) -> float:
    base = _PLAN_BASE.get(license_type, 5.0)
    xpm  = _PLAN_XPM.get(license_type, 1.0)
    if license_type == "Lifetime":
        return base
    extra_months = max(0, (days - 30) // 30)
    return round(base + extra_months * xpm, 2)


@app.route("/api/issue_public", methods=["POST"])
def issue_public():
    import requests as _req

    ip   = _get_ip()
    data = request.get_json(silent=True) or {}

    username      = (data.get("username")        or "").strip()
    email         = (data.get("email")           or "").strip()
    days          = int(data.get("days", 30))
    license_type  = (data.get("license_type")    or "Basic").strip().capitalize()
    max_devices   = int(data.get("max_devices", 1))
    order_id      = (data.get("paypal_order_id") or "").strip()
    discount_code = (data.get("discount_code")   or "").strip().upper()

    if not username:
        return jsonify({"error": "username requerido"}), 400
    if not order_id:
        return jsonify({"error": "paypal_order_id requerido"}), 400
    if license_type not in LICENSE_TYPES:
        return jsonify({"error": "Tipo de licencia inválido"}), 400
    if days <= 0 or days > 36500:
        return jsonify({"error": "días inválidos"}), 400
    if order_id in _used_orders:
        return jsonify({"error": "Este pedido ya fue procesado."}), 400
    if _is_rate_limited(ip):
        return jsonify({"error": "Demasiadas peticiones. Espera un momento."}), 429

    db               = _ensure_keys(_load_db())
    applied_discount = 0.0
    valid_code       = None

    if discount_code:
        dc = db["discount_codes"].get(discount_code)
        if dc and dc.get("active", True):
            plan_ok = not dc.get("plans") or license_type.lower() in dc["plans"]
            uses_ok = dc["max_uses"] == 0 or dc["uses"] < dc["max_uses"]
            exp_ok  = True
            if dc.get("expires_at"):
                try: exp_ok = date.fromisoformat(dc["expires_at"]) >= date.today()
                except Exception: pass
            if plan_ok and uses_ok and exp_ok:
                applied_discount = dc["discount"]
                valid_code       = discount_code

    paypal_client_id = os.environ.get("PAYPAL_CLIENT_ID", "")
    paypal_secret    = os.environ.get("PAYPAL_SECRET", "")

    if paypal_client_id and paypal_secret:
        try:
            token_resp = _req.post(
                "https://api-m.paypal.com/v1/oauth2/token",
                auth=(paypal_client_id, paypal_secret),
                data={"grant_type": "client_credentials"},
                timeout=10,
            )
            access_token = token_resp.json().get("access_token", "")
            order_resp   = _req.get(
                f"https://api-m.paypal.com/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            order_data   = order_resp.json()
            order_status = order_data.get("status", "")

            if order_status != "COMPLETED":
                return jsonify({"error": f"Pago no completado (estado: {order_status})."}), 402

            paid_str = (
                order_data.get("purchase_units", [{}])[0]
                .get("payments", {})
                .get("captures", [{}])[0]
                .get("amount", {})
                .get("value", "0")
            )
            paid     = float(paid_str)
            expected = round(_expected_price(license_type, days) * (1 - applied_discount / 100), 2)
            if paid < expected - 0.01:
                return jsonify({"error": f"Importe insuficiente (recibido €{paid:.2f}, esperado €{expected:.2f})."}), 402

        except Exception as e:
            return jsonify({"error": f"No se pudo verificar el pago con PayPal: {str(e)}"}), 500

    _used_orders.add(order_id)

    if valid_code and valid_code in db["discount_codes"]:
        db["discount_codes"][valid_code]["uses"] += 1

    max_devices   = _MAX_DEVICES.get(license_type, 1)
    key           = generate_license(username, days, "")
    exp           = (date.today() + timedelta(days=days)).isoformat()
    note_discount = f" · Dto:{valid_code}({applied_discount}%)" if valid_code else ""

    db["licenses"][key] = {
        "username":      username,
        "expires":       exp,
        "note":          f"Compra web · email:{email} · PayPal:{order_id[:16]}{note_discount}",
        "license_type":  license_type,
        "max_devices":   max_devices,
        "bound_devices": [],
        "issued_at":     datetime.utcnow().isoformat(),
        "revoked":       False,
        "revoke_reason": "",
        "uses":          0,
        "last_seen":     "",
        "last_ip":       ip,
        "first_use":     "",
        "email":         email,
        "paypal_order":  order_id,
    }
    _save_db(db)

    _send_license_email(
        to_email  = email,
        username  = username,
        key       = key,
        plan_name = {"basic": "Basic", "pro": "Pro", "lifetime": "Lifetime"}.get(
                        data.get("plan", "").lower(), license_type),
        expires   = exp,
        is_free   = False,
    )

    return jsonify({"key": key, "username": username, "expires": exp, "license_type": license_type})


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def index():
    from flask import send_from_directory
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)