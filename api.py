import os
import requests

from datetime import datetime, timezone
from flask import Flask, jsonify, request


app = Flask(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

EMS_API_SECRET = os.environ.get("EMS_API_SECRET")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DISCORD_911_CHANNEL_ID = os.environ.get("DISCORD_911_CHANNEL_ID")

if not EMS_API_SECRET:
    raise RuntimeError(
        "EMS_API_SECRET environment variable is missing."
    )

if not DISCORD_BOT_TOKEN:
    raise RuntimeError(
        "DISCORD_BOT_TOKEN environment variable is missing."
    )

if not DISCORD_911_CHANNEL_ID:
    raise RuntimeError(
        "DISCORD_911_CHANNEL_ID environment variable is missing."
    )


DISCORD_API = "https://discord.com/api/v10"


# ============================================================
# TEMPORARY LIVE STATE
# ============================================================

ems_state = {
    "online": False,
    "activated_by": None,
    "activated_at": None,
    "revision": 0
}


# Messages created by THIS 911 API.
# We'll move this tracking into PostgreSQL later.
active_911_messages = []


# ============================================================
# SECURITY
# ============================================================

def authorized_request():

    supplied_secret = request.headers.get(
        "X-EMS-Secret",
        ""
    )

    return supplied_secret == EMS_API_SECRET


def unauthorized_response():

    return jsonify({
        "ok": False,
        "error": "Unauthorized"
    }), 401


# ============================================================
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().isoformat()


def clean_string(value, max_length):

    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    return value[:max_length]


# ============================================================
# DISCORD
# ============================================================

def discord_headers():

    return {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }


def send_discord_message(embed, track=True):

    url = (
        f"{DISCORD_API}/channels/"
        f"{DISCORD_911_CHANNEL_ID}/messages"
    )

    payload = {
        "embeds": [embed],

        "allowed_mentions": {
            "parse": []
        }
    }

    try:

        response = requests.post(
            url,
            headers=discord_headers(),
            json=payload,
            timeout=15
        )

    except requests.RequestException as exc:

        print(
            "[DISCORD] Request failed:",
            exc
        )

        return None


    if response.status_code != 200:

        print(
            "[DISCORD] Send failed:",
            response.status_code,
            response.text
        )

        return None


    try:
        message = response.json()

    except ValueError:
        return None


    message_id = message.get("id")


    if message_id and track:

        active_911_messages.append(
            str(message_id)
        )


    return message


def delete_discord_message(message_id):

    url = (
        f"{DISCORD_API}/channels/"
        f"{DISCORD_911_CHANNEL_ID}/messages/"
        f"{message_id}"
    )


    try:

        response = requests.delete(
            url,
            headers=discord_headers(),
            timeout=15
        )

    except requests.RequestException as exc:

        print(
            "[DISCORD] Delete failed:",
            message_id,
            exc
        )

        return False


    if response.status_code in (204, 404):
        return True


    print(
        "[DISCORD] Delete failed:",
        message_id,
        response.status_code,
        response.text
    )

    return False


def clear_active_911_messages():

    global active_911_messages

    messages = list(active_911_messages)

    deleted = 0
    failed = 0


    for message_id in messages:

        if delete_discord_message(message_id):
            deleted += 1

        else:
            failed += 1


    active_911_messages = []


    return deleted, failed


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "ok": True,
        "service": "GSMH 911 API",
        "status": "online"
    }), 200


# ============================================================
# STATUS
# ============================================================

@app.route("/ems/status", methods=["GET"])
def status():

    if not authorized_request():
        return unauthorized_response()


    return jsonify({
        "ok": True,
        "ems": ems_state
    }), 200


# ============================================================
# EMS ON
# ============================================================

@app.route("/ems/on", methods=["POST"])
def ems_on():

    if not authorized_request():
        return unauthorized_response()


    data = request.get_json(
        silent=True
    ) or {}


    username = clean_string(
        data.get("roblox_username"),
        50
    )

    display_name = clean_string(
        data.get("roblox_display_name"),
        50
    )

    user_id = data.get(
        "roblox_user_id"
    )


    if not username:

        return jsonify({
            "ok": False,
            "error": "roblox_username is required"
        }), 400


    # Clear previous offline message/session messages.
    deleted, failed = clear_active_911_messages()


    embed = {
        "title": "🚑 911 SYSTEM ONLINE",

        "description": (
            "**Grey Sloan Ambulance Service Dispatch**\n\n"
            "The in-game 911 system is now accepting "
            "emergency calls."
        ),

        "color": 3447003,

        "fields": [
            {
                "name": "Activated By",
                "value": username,
                "inline": True
            },
            {
                "name": "Status",
                "value": "🟢 Accepting Calls",
                "inline": True
            }
        ],

        "timestamp": iso_now(),

        "footer": {
            "text": (
                "Grey Sloan Ambulance Service "
                "• Emergency Dispatch"
            )
        }
    }


    message = send_discord_message(
        embed
    )


    if message is None:

        return jsonify({
            "ok": False,
            "error": "Discord notification failed"
        }), 502


    ems_state["online"] = True

    ems_state["activated_by"] = {
        "username": username,
        "display_name": display_name,
        "user_id": user_id
    }

    ems_state["activated_at"] = iso_now()
    ems_state["revision"] += 1


    print(
        f"[911] ONLINE - Activated by {username}"
    )


    return jsonify({
        "ok": True,
        "online": True,
        "activated_by": username,
        "messages_deleted": deleted,
        "delete_failures": failed
    }), 200


# ============================================================
# EMS OFF
# ============================================================

@app.route("/ems/off", methods=["POST"])
def ems_off():

    if not authorized_request():
        return unauthorized_response()


    data = request.get_json(
        silent=True
    ) or {}


    username = clean_string(
        data.get("roblox_username"),
        50
    )


    if not username:

        return jsonify({
            "ok": False,
            "error": "roblox_username is required"
        }), 400


    # Delete online status + active call messages.
    deleted, failed = clear_active_911_messages()


    embed = {
        "title": "🚑 911 SYSTEM OFFLINE",

        "description": (
            "**Grey Sloan Ambulance Service Dispatch**\n\n"
            "The in-game 911 system is currently "
            "not accepting emergency calls."
        ),

        "color": 15158332,

        "fields": [
            {
                "name": "Deactivated By",
                "value": username,
                "inline": True
            },
            {
                "name": "Status",
                "value": "🔴 Not Accepting Calls",
                "inline": True
            }
        ],

        "timestamp": iso_now(),

        "footer": {
            "text": (
                "Grey Sloan Ambulance Service "
                "• Emergency Dispatch"
            )
        }
    }


    message = send_discord_message(
        embed
    )


    if message is None:

        return jsonify({
            "ok": False,
            "error": "Discord notification failed"
        }), 502


    ems_state["online"] = False
    ems_state["revision"] += 1


    print(
        f"[911] OFFLINE - Deactivated by {username}"
    )


    return jsonify({
        "ok": True,
        "online": False,
        "deactivated_by": username,
        "messages_deleted": deleted,
        "delete_failures": failed
    }), 200


# ============================================================
# 911 CALL
# ============================================================

@app.route("/911/call", methods=["POST"])
def submit_911_call():

    if not authorized_request():
        return unauthorized_response()


    data = request.get_json(
        silent=True
    ) or {}


    username = clean_string(
        data.get("roblox_username"),
        50
    )

    display_name = clean_string(
        data.get("roblox_display_name"),
        50
    )

    location = clean_string(
        data.get("location"),
        100
    )

    reason = clean_string(
        data.get("reason"),
        500
    )

    user_id = data.get(
        "roblox_user_id"
    )

    job_id = data.get(
        "roblox_job_id"
    )

    place_id = data.get(
        "roblox_place_id"
    )


    if not username:

        return jsonify({
            "ok": False,
            "error": "roblox_username is required"
        }), 400


    if not location:

        return jsonify({
            "ok": False,
            "error": "location is required"
        }), 400


    if not reason:

        return jsonify({
            "ok": False,
            "error": "reason is required"
        }), 400


    if not ems_state["online"]:

        return jsonify({
            "ok": False,
            "error": "911 system is offline"
        }), 409


    # Temporary ID.
    # PostgreSQL will give us permanent sequential IDs later.
    call_id = (
        "GSMH-"
        + utc_now().strftime("%Y%m%d-%H%M%S")
        + "-"
        + str(user_id or "UNKNOWN")
    )


    if display_name and display_name != username:

        caller = (
            f"{display_name} (@{username})"
        )

    else:
        caller = username


    embed = {
        "title": "🚨 NEW 911 CALL",

        "description": (
            "A new emergency call has been received "
            "from the in-game 911 system."
        ),

        "color": 15158332,

        "fields": [
            {
                "name": "Call ID",
                "value": call_id,
                "inline": False
            },
            {
                "name": "Caller",
                "value": caller,
                "inline": False
            },
            {
                "name": "Location",
                "value": location,
                "inline": False
            },
            {
                "name": "Reason for Call",
                "value": reason,
                "inline": False
            }
        ],

        "timestamp": iso_now(),

        "footer": {
            "text": (
                "Grey Sloan Ambulance Service "
                "• Emergency Dispatch"
            )
        }
    }


    message = send_discord_message(
        embed
    )


    if message is None:

        return jsonify({
            "ok": False,
            "error": "Could not send call to Discord"
        }), 502


    print(
        "[911 CALL]",
        call_id,
        "| User:",
        username,
        "| Location:",
        location,
        "| Job:",
        job_id,
        "| Place:",
        place_id
    )


    return jsonify({
        "ok": True,
        "call_id": call_id,
        "discord_message_id": message.get("id")
    }), 201


# ============================================================
# LOCAL RUN
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
