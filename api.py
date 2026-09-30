import os
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify


app = Flask(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

EMS_API_SECRET = os.environ.get("EMS_API_SECRET")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


if not EMS_API_SECRET:
    raise RuntimeError(
        "EMS_API_SECRET environment variable is not configured."
    )


if not DISCORD_WEBHOOK_URL:
    raise RuntimeError(
        "DISCORD_WEBHOOK_URL environment variable is not configured."
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
    """
    Checks for the secret sent by the Roblox server.

    Roblox should send:
    X-EMS-Secret: YOUR_SECRET
    """

    supplied_secret = request.headers.get("X-EMS-Secret")

    return (
        supplied_secret is not None
        and supplied_secret == EMS_API_SECRET
    )


# ============================================================
# DISCORD WEBHOOK HELPER
# ============================================================

def send_discord_webhook(payload):
    """
    Sends a payload to the Discord webhook.

    Returns:
        (True, None) if successful
        (False, error_message) if unsuccessful
    """

    try:

        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10
        )

        if response.status_code not in (200, 204):

            print(
                f"Discord webhook failed "
                f"({response.status_code}): "
                f"{response.text}"
            )

            return (
                False,
                f"Discord returned status "
                f"{response.status_code}"
            )

        return True, None

    except requests.RequestException as error:

        print(
            f"Discord webhook request failed: {error}"
        )

        return False, str(error)


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

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    if not authorized_request():

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 401


    # --------------------------------------------------------
    # Get Roblox information
    # --------------------------------------------------------

    data = request.get_json(silent=True) or {}


    username = data.get("roblox_username")

    display_name = data.get(
        "roblox_display_name"
    )

    user_id = data.get(
        "roblox_user_id"
    )


    if not username:

        return jsonify({
            "success": False,
            "error": "Missing roblox_username"
        }), 400


    # --------------------------------------------------------
    # Update EMS state
    # --------------------------------------------------------

    ems_state["enabled"] = True

    ems_state["roblox_username"] = username

    ems_state["roblox_display_name"] = display_name

    ems_state["roblox_user_id"] = user_id

    ems_state["updated_at"] = (
        datetime.now(timezone.utc).isoformat()
    )

    ems_state["revision"] += 1


    # --------------------------------------------------------
    # Send Discord notification
    # --------------------------------------------------------

    discord_payload = {

        "username": "GSMH EMS Dispatch",

        "embeds": [
            {

                "title": "EMS System On",

                "description": (
                    "The GSMH 911/EMS system "
                    "has been activated."
                ),

                "color": 5763719,

                "fields": [

                    {
                        "name": "Activated By",
                        "value": (
                            f"{display_name or username} "
                            f"(@{username})"
                        ),
                        "inline": True
                    },

                    {
                        "name": "Roblox User ID",
                        "value": str(
                            user_id or "Unknown"
                        ),
                        "inline": True
                    }

                ],

                "timestamp": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )

            }
        ]
    }


    webhook_success, webhook_error = (
        send_discord_webhook(
            discord_payload
        )
    )


    print(
        f"EMS SYSTEM ON - "
        f"Activated by {username}"
    )


    # --------------------------------------------------------
    # Response
    # --------------------------------------------------------

    return jsonify({

        "success": True,

        "message": "EMS system enabled",

        "discord_notification": (
            webhook_success
        ),

        "state": ems_state

    })


# ============================================================
# EMS OFF
# ============================================================

@app.post("/ems/off")
def ems_off():

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    if not authorized_request():

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 401


    # --------------------------------------------------------
    # Get Roblox information
    # --------------------------------------------------------

    data = request.get_json(silent=True) or {}


    username = data.get("roblox_username")

    display_name = data.get(
        "roblox_display_name"
    )

    user_id = data.get(
        "roblox_user_id"
    )


    if not username:

        return jsonify({
            "success": False,
            "error": "Missing roblox_username"
        }), 400


    # --------------------------------------------------------
    # Update EMS state
    # --------------------------------------------------------

    ems_state["enabled"] = False

    ems_state["roblox_username"] = username

    ems_state["roblox_display_name"] = display_name

    ems_state["roblox_user_id"] = user_id

    ems_state["updated_at"] = (
        datetime.now(timezone.utc).isoformat()
    )

    ems_state["revision"] += 1


    # --------------------------------------------------------
    # Send Discord notification
    # --------------------------------------------------------

    discord_payload = {

        "username": "GSMH EMS Dispatch",

        "embeds": [
            {

                "title": "EMS System Off",

                "description": (
                    "The GSMH 911/EMS system "
                    "has been deactivated."
                ),

                "color": 15548997,

                "fields": [

                    {
                        "name": "Deactivated By",
                        "value": (
                            f"{display_name or username} "
                            f"(@{username})"
                        ),
                        "inline": True
                    },

                    {
                        "name": "Roblox User ID",
                        "value": str(
                            user_id or "Unknown"
                        ),
                        "inline": True
                    }

                ],

                "timestamp": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )

            }
        ]
    }


    webhook_success, webhook_error = (
        send_discord_webhook(
            discord_payload
        )
    )


    print(
        f"EMS SYSTEM OFF - "
        f"Deactivated by {username}"
    )


    # --------------------------------------------------------
    # Response
    # --------------------------------------------------------

    return jsonify({

        "success": True,

        "message": "EMS system disabled",

        "discord_notification": (
            webhook_success
        ),

        "state": ems_state

    })


# ============================================================
# SUBMIT 911 CALL
# ============================================================

@app.post("/911/call")
def submit_911_call():

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    if not authorized_request():

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 401


    # --------------------------------------------------------
    # Get call information
    # --------------------------------------------------------

    data = request.get_json(silent=True) or {}


    username = data.get(
        "roblox_username"
    )

    display_name = data.get(
        "roblox_display_name"
    )

    user_id = data.get(
        "roblox_user_id"
    )

    location = data.get(
        "location"
    )

    reason = data.get(
        "reason"
    )


    # --------------------------------------------------------
    # Validate information
    # --------------------------------------------------------

    if not username:

        return jsonify({
            "success": False,
            "error": "Missing roblox_username"
        }), 400


    if not location:

        return jsonify({
            "success": False,
            "error": "Missing location"
        }), 400


    if not reason:

        return jsonify({
            "success": False,
            "error": "Missing reason"
        }), 400


    # Convert to strings and limit length
    username = str(username)[:100]

    location = str(location)[:500]

    reason = str(reason)[:1000]


    if display_name:
        display_name = str(
            display_name
        )[:100]


    # --------------------------------------------------------
    # Build Discord embed
    # --------------------------------------------------------

    discord_payload = {

        "username": "GSMH 911 Dispatch",

        "embeds": [
            {

                "title": "🚨 911 CALL",

                "description": (
                    "A new emergency call "
                    "has been submitted."
                ),

                "color": 15158332,

                "fields": [

                    {
                        "name": "Caller",
                        "value": (
                            f"{display_name or username} "
                            f"(@{username})"
                        ),
                        "inline": True
                    },

                    {
                        "name": "Roblox User ID",
                        "value": str(
                            user_id or "Unknown"
                        ),
                        "inline": True
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

                "footer": {
                    "text": (
                        "Grey Sloan Ambulance Service"
                    )
                },

                "timestamp": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )

            }
        ]
    }


    # --------------------------------------------------------
    # Send to Discord
    # --------------------------------------------------------

    webhook_success, webhook_error = (
        send_discord_webhook(
            discord_payload
        )
    )


    if not webhook_success:

        return jsonify({

            "success": False,

            "error": (
                "The 911 call was received "
                "but could not be sent "
                "to Discord."
            )

        }), 502


    # --------------------------------------------------------
    # Server logging
    # --------------------------------------------------------

    print(
        f"911 CALL | "
        f"Caller: {username} | "
        f"Location: {location} | "
        f"Reason: {reason}"
    )


    # --------------------------------------------------------
    # Success
    # --------------------------------------------------------

    return jsonify({

        "success": True,

        "message": (
            "911 call successfully submitted"
        )

    }), 200


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
