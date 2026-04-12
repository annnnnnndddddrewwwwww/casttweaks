"""
╔══════════════════════════════════════════════════════════════════╗
║       CTadvanced  —  License Server  v1.0  —  CASTTWEAKS®       ║
║   Backend Flask para Render.com                                   ║
║                                                                   ║
║   Rutas:                                                          ║
║     POST /api/verify        Verificar clave (cliente)            ║
║     POST /api/issue         Emitir nueva clave (owner)           ║
║     POST /api/revoke        Revocar clave (owner)                ║
║     GET  /api/licenses      Listar todas las claves (owner)      ║
║     GET  /api/health        Health-check                         ║
║                                                                   ║
║   Variables de entorno requeridas en Render:                     ║
║     OWNER_SECRET   → mismo valor que en el cliente               ║
║     OWNER_API_KEY  → clave secreta para rutas de owner           ║
╚══════════════════════════════════════════════════════════════════╝

Deploy en Render:
  1. Sube este archivo a un repo de GitHub (solo este archivo + requirements.txt)
  2. Crea un Web Service en Render apuntando al repo
  3. Build command:  pip install -r requirements.txt
  4. Start command:  gunicorn server:app
  5. Añade las variables de entorno OWNER_SECRET y OWNER_API_KEY

requirements.txt:
  flask
  gunicorn
"""

import os, json, hmac, hashlib, base64
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Configuración desde variables de entorno ─────────────────────
OWNER_SECRET  = os.environ.get("OWNER_SECRET",  "CASTTWEAKS_SECRET_2024_DONT_SHARE")
OWNER_API_KEY = os.environ.get("OWNER_API_KEY", "CHANGE_THIS_IN_RENDER_ENV")
DB_FILE       = "licenses.json"   # Render persiste el filesystem en disco dentro del servicio


# ──══════════════════════════════════════════════════════════════
#  BASE DE DATOS  (JSON en disco — suficiente para <10k licencias)
# ──══════════════════════════════════════════════════════════════

def _load_db() -> dict:
    """Carga la base de datos de licencias."""
    try:
        with open(DB_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"licenses": {}}


def _save_db(db: dict):
    """Guarda la base de datos de licencias."""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


# ──══════════════════════════════════════════════════════════════
#  CRIPTOGRAFÍA  (igual que en el cliente)
# ──══════════════════════════════════════════════════════════════

def _sign(payload: str) -> str:
    return hmac.new(
        OWNER_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def generate_license(username: str, days: int, hwid: str = "", note: str = "") -> str:
    """Genera una clave firmada con HMAC-SHA256."""
    exp     = (date.today() + timedelta(days=days)).isoformat()
    payload = f"{username}|{exp}|{hwid}"
    sig     = _sign(payload)
    raw     = f"{payload}||{sig}"
    key     = base64.b64encode(raw.encode()).decode().rstrip("=")
    chunks  = [key[i:i+8] for i in range(0, len(key), 8)]
    return "-".join(chunks)


def decode_key(key: str) -> dict | None:
    """Decodifica una clave y devuelve sus campos, o None si es inválida."""
    try:
        raw = key.replace("-", "").replace(" ", "")
        pad = 4 - len(raw) % 4
        if pad != 4:
            raw += "=" * pad
        decoded  = base64.b64decode(raw).decode()
        payload, sig = decoded.rsplit("||", 1)
        parts    = payload.split("|")
        username, exp_str, hwid = parts[0], parts[1], parts[2]
        expected = _sign(payload)
        if not hmac.compare_digest(sig, expected):
            return None
        return {"username": username, "expires": exp_str, "hwid": hwid}
    except Exception:
        return None


# ──══════════════════════════════════════════════════════════════
#  DECORADORES DE AUTENTICACIÓN
# ──══════════════════════════════════════════════════════════════

def require_owner(f):
    """Requiere la cabecera X-Owner-Key con el valor correcto."""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-Owner-Key", "")
        if not hmac.compare_digest(api_key, OWNER_API_KEY):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ──══════════════════════════════════════════════════════════════
#  RUTAS PÚBLICAS  (usadas por el cliente CTadvanced)
# ──══════════════════════════════════════════════════════════════

@app.route("/api/health", methods=["GET"])
def health():
    """Health check — Render lo usa para saber si el servicio está vivo."""
    return jsonify({"status": "ok", "ts": datetime.utcnow().isoformat()})


@app.route("/api/verify", methods=["POST"])
def verify():
    """
    Verifica una clave contra la base de datos del servidor.
    Body JSON: { "key": "...", "hwid": "..." }
    Devuelve:  { "valid": bool, "username": str, "expires": str,
                 "days_left": int, "error": str }
    """
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    hwid = (data.get("hwid") or "").strip()

    if not key:
        return jsonify({"valid": False, "error": "Clave vacía."}), 400

    # 1. Verificar firma criptográfica
    decoded = decode_key(key)
    if not decoded:
        return jsonify({"valid": False, "error": "Firma inválida. Clave incorrecta o modificada."})

    # 2. Comprobar revocación en la base de datos
    db    = _load_db()
    entry = db["licenses"].get(key)

    if entry is None:
        # Clave con firma válida pero no registrada en el servidor
        # → rechazar (solo se aceptan claves emitidas desde el panel)
        return jsonify({"valid": False, "error": "Clave no registrada. Contacta al owner."})

    if entry.get("revoked"):
        reason = entry.get("revoke_reason", "Sin motivo especificado.")
        return jsonify({"valid": False, "error": f"Licencia revocada: {reason}"})

    # 3. Comprobar caducidad
    try:
        exp_date  = date.fromisoformat(decoded["expires"])
        days_left = (exp_date - date.today()).days
        if days_left < 0:
            return jsonify({"valid": False, "error": f"Licencia expirada el {decoded['expires']}."})
    except Exception:
        return jsonify({"valid": False, "error": "Fecha de expiración inválida."})

    # 4. Comprobar HWID binding
    hwid_in_key  = decoded.get("hwid", "")
    stored_hwid  = entry.get("bound_hwid", "")

    if hwid_in_key:
        # Clave generada con HWID fijo
        if hwid and hwid_in_key.upper() != hwid.upper():
            return jsonify({"valid": False, "error": "Esta clave está registrada en otro ordenador."})
    elif stored_hwid:
        # HWID vinculado en el servidor al primer uso
        if hwid and stored_hwid.upper() != hwid.upper():
            return jsonify({"valid": False, "error": "Esta clave ya está registrada en otro ordenador."})
    elif hwid:
        # Primer uso → vincular HWID en el servidor
        entry["bound_hwid"]  = hwid
        entry["first_use"]   = datetime.utcnow().isoformat()
        _save_db(db)

    # 5. Actualizar last_seen
    entry["last_seen"] = datetime.utcnow().isoformat()
    entry["uses"]      = entry.get("uses", 0) + 1
    _save_db(db)

    return jsonify({
        "valid":     True,
        "username":  decoded["username"],
        "expires":   decoded["expires"],
        "days_left": days_left,
    })


# ──══════════════════════════════════════════════════════════════
#  RUTAS OWNER  (solo accesibles con X-Owner-Key)
# ──══════════════════════════════════════════════════════════════

@app.route("/api/issue", methods=["POST"])
@require_owner
def issue():
    """
    Emite una nueva licencia y la registra en la base de datos.
    Body JSON: { "username": str, "days": int, "hwid": str, "note": str }
    """
    data     = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    days     = int(data.get("days", 30))
    hwid     = (data.get("hwid") or "").strip()
    note     = (data.get("note") or "").strip()

    if not username:
        return jsonify({"error": "username requerido"}), 400
    if days <= 0:
        return jsonify({"error": "days debe ser > 0"}), 400

    key = generate_license(username, days, hwid)
    exp = (date.today() + timedelta(days=days)).isoformat()

    db = _load_db()
    db["licenses"][key] = {
        "username":   username,
        "expires":    exp,
        "hwid":       hwid,
        "note":       note,
        "issued_at":  datetime.utcnow().isoformat(),
        "bound_hwid": hwid,   # puede estar vacío → se vincula al primer uso
        "revoked":    False,
        "uses":       0,
        "last_seen":  "",
        "first_use":  "",
    }
    _save_db(db)

    return jsonify({"key": key, "username": username, "expires": exp})


@app.route("/api/revoke", methods=["POST"])
@require_owner
def revoke():
    """
    Revoca una licencia.
    Body JSON: { "key": str, "reason": str }
    """
    data   = request.get_json(silent=True) or {}
    key    = (data.get("key") or "").strip()
    reason = (data.get("reason") or "Revocada por el owner.").strip()

    if not key:
        return jsonify({"error": "key requerida"}), 400

    db = _load_db()
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404

    db["licenses"][key]["revoked"]       = True
    db["licenses"][key]["revoke_reason"] = reason
    db["licenses"][key]["revoked_at"]    = datetime.utcnow().isoformat()
    _save_db(db)

    return jsonify({"ok": True, "key": key, "reason": reason})


@app.route("/api/unrevoke", methods=["POST"])
@require_owner
def unrevoke():
    """Reactiva una licencia revocada."""
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()

    db = _load_db()
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404

    db["licenses"][key]["revoked"]       = False
    db["licenses"][key]["revoke_reason"] = ""
    _save_db(db)
    return jsonify({"ok": True, "key": key})


@app.route("/api/licenses", methods=["GET"])
@require_owner
def list_licenses():
    """Devuelve todas las licencias con sus metadatos."""
    db = _load_db()
    return jsonify({"licenses": db["licenses"]})


@app.route("/api/delete", methods=["POST"])
@require_owner
def delete_license():
    """Elimina permanentemente una licencia de la base de datos."""
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()

    db = _load_db()
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404

    del db["licenses"][key]
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/reset_hwid", methods=["POST"])
@require_owner
def reset_hwid():
    """Limpia el HWID vinculado de una licencia (permite cambio de PC)."""
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()

    db = _load_db()
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404

    db["licenses"][key]["bound_hwid"] = ""
    db["licenses"][key]["first_use"]  = ""
    _save_db(db)
    return jsonify({"ok": True})


# ──══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ──══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Solo para desarrollo local — en Render usa gunicorn
    app.run(debug=True, port=5000)
