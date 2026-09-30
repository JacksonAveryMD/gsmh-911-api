import os
from datetime import datetime, timezone

from flask import Flask, request, jsonify


app = Flask(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

EMS_API_SECRET = os.environ.get("EMS_API_SECRET")

if not EMS_API_SECRET:
    raise RuntimeError(
        "EMS_API_SECRET environment variable is not configured."
    )


# ============================================================
# EMS STATE
# ============================================================

ems_state = {
    "enabled": False,
    "roblox_username": None,
    "roblox_display_name": None,
    "roblox_user_id": None,
    "updated_at": None,
    "revision": 0
}


# ============================================================
# AUTHENTICATION
# ============================================================

def authorized_request():
    supplied_secret = request.headers.get(
        "X-EMS-Secret"
    )

    return (
        supplied_secret is not None
        and supplied_secret == EMS_API_SECRET
    )


# ============================================================
# HOME / HEALTH CHECK
# ============================================================

@app.get("/")
def home():

    return jsonify({
        "service": "GSMH 911 API",
        "status": "online"
    })


# ============================================================
# GET CURRENT EMS STATUS
# ============================================================

@app.get("/ems/status")
def get_ems_status():

    return jsonify(ems_state)


# ============================================================
# EMS ON
# ============================================================

@app.post("/ems/on")
def ems_on():

    if not authorized_request():

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 401


    data = request.get_json(
        silent=True
    ) or {}


    username = data.get(
        "roblox_username"
    )


    if not username:

        return jsonify({
            "success": False,
            "error": "Missing roblox_username"
        }), 400


    ems_state["enabled"] = True

    ems_state["roblox_username"] = username

    ems_state["roblox_display_name"] = data.get(
        "roblox_display_name"
    )

    ems_state["roblox_user_id"] = data.get(
        "roblox_user_id"
    )

    ems_state["updated_at"] = (
        datetime.now(timezone.utc).isoformat()
    )

    ems_state["revision"] += 1


    print(
        f"EMS SYSTEM ON - "
        f"Activated by {username}"
    )


    return jsonify({
        "success": True,
        "message": "EMS system enabled",
        "state": ems_state
    })


# ============================================================
# EMS OFF
# ============================================================

@app.post("/ems/off")
def ems_off():

    if not authorized_request():

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 401


    data = request.get_json(
        silent=True
    ) or {}


    username = data.get(
        "roblox_username"
    )


    if not username:

        return jsonify({
            "success": False,
            "error": "Missing roblox_username"
        }), 400


    ems_state["enabled"] = False

    ems_state["roblox_username"] = username

    ems_state["roblox_display_name"] = data.get(
        "roblox_display_name"
    )

    ems_state["roblox_user_id"] = data.get(
        "roblox_user_id"
    )

    ems_state["updated_at"] = (
        datetime.now(timezone.utc).isoformat()
    )

    ems_state["revision"] += 1


    print(
        f"EMS SYSTEM OFF - "
        f"Deactivated by {username}"
    )


    return jsonify({
        "success": True,
        "message": "EMS system disabled",
        "state": ems_state
    })


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
