import os
import requests

from datetime import datetime, timezone
from flask import Flask, jsonify, request


app = Flask(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

EMS_API_SECRET = os.environ.get("EMS_API_SECRET")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not EMS_API_SECRET:
    raise RuntimeError(
        "EMS_API_SECRET environment variable is missing."
    )

if not DISCORD_WEBHOOK_URL:
    raise RuntimeError(
        "DISCORD_WEBHOOK_URL environment variable is missing."
    )


# ============================================================
# TEMPORARY STATE
# ============================================================
#
# This is only the live state.
# Permanent call records will be moved to our database next.
#

ems_state = {
    "online": False,
    "activated_by": None,
    "activated_at": None,
    "revision": 0,
}


# Messages created by the webhook during the current API session.
#
# When !off is used, these Discord messages can be deleted.
#
# IMPORTANT:
# Call HISTORY will eventually be stored separately in the database.
active_discord_messages = []


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
# DISCORD WEBHOOK
# ============================================================

def send_discord_message(payload, track=True):
    """
    Send a webhook message and request Discord to return
    the created message.

    That gives us its message ID so it can later be deleted.
    """

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            params={
                "wait": "true"
            },
            json=payload,
            timeout=15
        )

    except requests.RequestException as exc:
        print(
            "[DISCORD] Request failed:",
            exc
        )

        return None


    if response.status_code not in (200, 204):
        print(
            "[DISCORD] Webhook failed:",
            response.status_code,
            response.text
        )

        return None


    # wait=true should normally return the message object.
    if response.status_code == 200:

        try:
            message = response.json()
        except ValueError:
            return None


        message_id = message.get("id")

        if message_id and track:
            active_discord_messages.append(
                str(message_id)
            )


        return message


    return {}


def delete_discord_message(message_id):
    """
    Delete a message that was created by this webhook.
    """

    try:
        response = requests.delete(
            f"{DISCORD_WEBHOOK_URL}/messages/{message_id}",
            timeout=15
        )

    except requests.RequestException as exc:

        print(
            "[DISCORD] Could not delete message",
            message_id,
            exc
        )

        return False


    # 204 = successfully deleted
    # 404 = already gone
    if response.status_code in (204, 404):
        return True


    print(
        "[DISCORD] Delete failed:",
        message_id,
        response.status_code,
        response.text
    )

    return False


def clear_active_discord_messages():
    """
    Delete only messages created and tracked by this API.

    This does NOT purge unrelated messages from the channel.
    """

    global active_discord_messages

    message_ids = list(active_discord_messages)

    deleted = 0
    failed = 0


    for message_id in message_ids:

        if delete_discord_message(message_id):
            deleted += 1
        else:
            failed += 1


    active_discord_messages = []


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
# EMS STATUS
# ============================================================

@app.route("/ems/status", methods=["GET"])
def ems_status():

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


    roblox_username = clean_string(
        data.get("roblox_username"),
        50
    )

    roblox_display_name = clean_string(
        data.get("roblox_display_name"),
        50
    )

    roblox_user_id = data.get(
        "roblox_user_id"
    )


    if not roblox_username:

        return jsonify({
            "ok": False,
            "error": "roblox_username is required"
        }), 400


    # --------------------------------------------------------
    # Update system state
    # --------------------------------------------------------

    ems_state["online"] = True

    ems_state["activated_by"] = {
        "username": roblox_username,
        "display_name": roblox_display_name,
        "user_id": roblox_user_id
    }

    ems_state["activated_at"] = iso_now()

    ems_state["revision"] += 1


    # --------------------------------------------------------
    # Remove previous tracked status/call messages
    # --------------------------------------------------------

    deleted, failed = clear_active_discord_messages()


    # --------------------------------------------------------
    # Discord embed
    # --------------------------------------------------------

    embed = {
        "title": "911 SYSTEM ONLINE",

        "description": (
            "**Grey Sloan Ambulance Service Dispatch**\n\n"
            "The in-game 911 system is now accepting calls."
        ),

        "color": 3447003,

        "fields": [
            {
                "name": "Activated By",
                "value": roblox_username,
                "inline": True
            },
            {
                "name": "Status",
                "value": "Accepting Calls",
                "inline": True
            }
        ],

        "timestamp": iso_now(),

        "footer": {
            "text": "Grey Sloan Ambulance Service • 911 Dispatch"
        }
    }


    discord_message = send_discord_message({
        "embeds": [embed],

        # Prevent user-controlled content from creating mentions.
        "allowed_mentions": {
            "parse": []
        }
    })


    if discord_message is None:

        # Roll state back because Roblox should NOT think
        # the system activated successfully.
        ems_state["online"] = False

        return jsonify({
            "ok": False,
            "error": "Discord notification failed"
        }), 502


    print(
        f"[EMS] ONLINE - Activated by {roblox_username}"
    )


    return jsonify({
        "ok": True,
        "online": True,
        "activated_by": roblox_username,
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


    roblox_username = clean_string(
        data.get("roblox_username"),
        50
    )


    if not roblox_username:

        return jsonify({
            "ok": False,
            "error": "roblox_username is required"
        }), 400


    # --------------------------------------------------------
    # Mark system offline
    # --------------------------------------------------------

    ems_state["online"] = False
    ems_state["revision"] += 1


    # --------------------------------------------------------
    # Clear active 911 Discord messages
    # --------------------------------------------------------

    deleted, failed = clear_active_discord_messages()


    # --------------------------------------------------------
    # Send OFFLINE message
    # --------------------------------------------------------

    embed = {
        "title": "911 SYSTEM OFFLINE",

        "description": (
            "**Grey Sloan Ambulance Service Dispatch**\n\n"
            "The in-game 911 system is currently not accepting calls."
        ),

        "color": 15158332,

        "fields": [
            {
                "name": "Deactivated By",
                "value": roblox_username,
                "inline": True
            },
            {
                "name": "Status",
                "value": "Not Accepting Calls",
                "inline": True
            }
        ],

        "timestamp": iso_now(),

        "footer": {
            "text": "Grey Sloan Ambulance Service • 911 Dispatch"
        }
    }


    # Track this too.
    #
    # When !on is used later, the offline message will be
    # removed and replaced by the new online message.
    discord_message = send_discord_message({
        "embeds": [embed],

        "allowed_mentions": {
            "parse": []
        }
    })


    if discord_message is None:

        return jsonify({
            "ok": False,
            "error": "Discord notification failed"
        }), 502


    print(
        f"[EMS] OFFLINE - Deactivated by {roblox_username}"
    )


    return jsonify({
        "ok": True,
        "online": False,
        "deactivated_by": roblox_username,
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


    # --------------------------------------------------------
    # Validate data
    # --------------------------------------------------------

    roblox_username = clean_string(
        data.get("roblox_username"),
        50
    )

    roblox_display_name = clean_string(
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

    roblox_user_id = data.get(
        "roblox_user_id"
    )

    roblox_job_id = data.get(
        "roblox_job_id"
    )

    roblox_place_id = data.get(
        "roblox_place_id"
    )


    if not roblox_username:

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


    # --------------------------------------------------------
    # Check EMS status
    # --------------------------------------------------------

    if not ems_state["online"]:

        return jsonify({
            "ok": False,
            "error": "911 system is offline"
        }), 409


    # --------------------------------------------------------
    # Temporary Call ID
    # --------------------------------------------------------
    #
    # The permanent database version will give us a proper
    # sequential call number.
    #

    call_id = (
        "GSMH-"
        + utc_now().strftime("%Y%m%d-%H%M%S")
        + "-"
        + str(roblox_user_id or "UNKNOWN")
    )


    # --------------------------------------------------------
    # Discord Embed
    # --------------------------------------------------------

    caller_display = roblox_username

    if (
        roblox_display_name
        and roblox_display_name != roblox_username
    ):

        caller_display = (
            f"{roblox_display_name} "
            f"(@{roblox_username})"
        )


    embed = {
        "title": "🚨 NEW 911 CALL",

        "description": (
            "A new emergency call has been received "
            "through the in-game 911 system."
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
                "value": caller_display,
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
            "text": "Grey Sloan Ambulance Service • Emergency Dispatch"
        }
    }


    # --------------------------------------------------------
    # Send to Discord
    # --------------------------------------------------------

    discord_message = send_discord_message({
        "embeds": [embed],

        "allowed_mentions": {
            "parse": []
        }
    })


    if discord_message is None:

        return jsonify({
            "ok": False,
            "error": "Could not send call to Discord"
        }), 502


    discord_message_id = discord_message.get(
        "id"
    )


    # --------------------------------------------------------
    # Temporary logging
    # --------------------------------------------------------

    print(
        "[911 CALL]",
        call_id,
        "|",
        roblox_username,
        "|",
        location,
        "|",
        reason,
        "| Job:",
        roblox_job_id,
        "| Place:",
        roblox_place_id
    )


    return jsonify({
        "ok": True,
        "call_id": call_id,
        "discord_message_id": discord_message_id
    }), 201


# ============================================================
# RUN LOCALLY
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
