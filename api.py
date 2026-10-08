import os
from datetime import datetime, timezone

import requests
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

# Permanent-looking thumbnail URL without the temporary query string.
CROSS_LOGO_URL = (
    "https://cdn.discordapp.com/attachments/"
    "1129251105675673700/"
    "1547501945227321354/"
    "Thinner_cross_logo_5.png"
)


# ============================================================
# LIVE EMS STATE
# ============================================================

ems_state = {
    "online": False,
    "activated_by": None,
    "activated_at": None,
    "revision": 0
}


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
# GENERAL HELPERS
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
# DISCORD HELPERS
# ============================================================

def discord_headers():
    return {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }


def discord_channel_url():
    return (
        f"{DISCORD_API}/channels/"
        f"{DISCORD_911_CHANNEL_ID}"
    )


# ============================================================
# GET BOT INFORMATION
# ============================================================

def get_bot_user():
    """
    Gets the Discord user information for the bot token.

    We use the bot's user ID when deciding which messages
    belong to our bot.
    """

    try:
        response = requests.get(
            f"{DISCORD_API}/users/@me",
            headers=discord_headers(),
            timeout=15
        )

    except requests.RequestException as exc:
        print(
            "[DISCORD] Could not get bot information:",
            exc
        )

        return None


    if response.status_code != 200:
        print(
            "[DISCORD] Bot information request failed:",
            response.status_code,
            response.text
        )

        return None


    try:
        return response.json()

    except ValueError:
        return None


# ============================================================
# SEND DISCORD MESSAGE
# ============================================================

def send_discord_message(embed):
    """
    Send an embed using the existing Discord bot.
    """

    url = f"{discord_channel_url()}/messages"

    payload = {
        "embeds": [embed],

        # Prevent any user-submitted text from generating
        # @everyone, @here, role mentions, etc.
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
            "[DISCORD] Send request failed:",
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
        return response.json()

    except ValueError:
        print(
            "[DISCORD] Discord returned invalid JSON."
        )

        return None


# ============================================================
# DELETE DISCORD MESSAGE
# ============================================================

def delete_discord_message(message_id):
    url = (
        f"{discord_channel_url()}/messages/"
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
            "[DISCORD] Delete request failed:",
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


# ============================================================
# GET RECENT DISCORD MESSAGES
# ============================================================

def get_recent_discord_messages(limit=100):
    """
    Get recent messages from the configured 911 channel.

    This allows the API to find old 911-system messages even
    if Render restarted and lost its in-memory state.
    """

    url = f"{discord_channel_url()}/messages"

    try:
        response = requests.get(
            url,
            headers=discord_headers(),
            params={
                "limit": min(limit, 100)
            },
            timeout=15
        )

    except requests.RequestException as exc:
        print(
            "[DISCORD] Could not read channel:",
            exc
        )

        return None


    if response.status_code != 200:
        print(
            "[DISCORD] Could not read channel:",
            response.status_code,
            response.text
        )

        return None


    try:
        return response.json()

    except ValueError:
        return None


# ============================================================
# IDENTIFY 911 SYSTEM MESSAGES
# ============================================================

def is_911_system_message(message, bot_user_id):
    """
    Only identify messages that:

    1. Were sent by our Discord bot.
    2. Contain one of our known 911 embed titles.

    This avoids deleting unrelated channel messages.
    """

    author = message.get("author") or {}

    if str(author.get("id")) != str(bot_user_id):
        return False


    embeds = message.get("embeds") or []

    if not embeds:
        return False


    known_titles = {
        "IN SERVICE",
        "OUT OF SERVICE",
        "911 CALL",
        "NEW 911 CALL",
        "🚨 NEW 911 CALL",
        "EMS System On",
        "EMS System Off",
        "🚑 911 SYSTEM ONLINE",
        "🚑 911 SYSTEM OFFLINE"
    }


    for embed in embeds:
        title = embed.get("title", "")

        if title in known_titles:
            return True


    return False


# ============================================================
# CLEAR 911 SYSTEM MESSAGES
# ============================================================

def clear_911_system_messages():
    """
    Delete only known 911 system embeds posted by our bot.

    This intentionally does NOT purge the entire channel.
    """

    bot_user = get_bot_user()

    if not bot_user:
        return 0, 1


    bot_user_id = bot_user.get("id")

    if not bot_user_id:
        return 0, 1


    messages = get_recent_discord_messages(
        limit=100
    )

    if messages is None:
        return 0, 1


    deleted = 0
    failed = 0


    for message in messages:

        if not is_911_system_message(
            message,
            bot_user_id
        ):
            continue


        message_id = message.get("id")

        if not message_id:
            continue


        if delete_discord_message(message_id):
            deleted += 1

        else:
            failed += 1


    print(
        "[911] Cleanup complete:",
        deleted,
        "deleted,",
        failed,
        "failed"
    )


    return deleted, failed


# ============================================================
# ORIGINAL IN SERVICE EMBED
# ============================================================

def create_in_service_embed():
    return {
        "title": "IN SERVICE",

        "description": (
            "**Information**\n"
            "Dispatch Center is accepting calls at this time. "
            "Please provide the following information.\n"
            "- Roblox username\n"
            "- Your current location\n"
            "- Your emergency"
        ),

        # discord.Color.blue()
        "color": 0x3498DB,

        "thumbnail": {
            "url": CROSS_LOGO_URL
        }
    }


# ============================================================
# ORIGINAL OUT OF SERVICE EMBED
# ============================================================

def create_out_of_service_embed():
    return {
        "title": "OUT OF SERVICE",

        "description": (
            "**Information**\n"
            "Dispatch Center is not accepting calls at this time. "
            "A member of campus safety or dispatch will put a "
            "message in this channel when they are back in service."
        ),

        # discord.Color.red()
        "color": 0xE74C3C,

        "thumbnail": {
            "url": CROSS_LOGO_URL
        }
    }


# ============================================================
# 911 CALL EMBED
# ============================================================

def create_911_call_embed(
    call_id,
    username,
    display_name,
    location,
    reason
):
    if (
        display_name
        and display_name != username
    ):
        caller = (
            f"{display_name} (@{username})"
        )

    else:
        caller = username


    return {
        "title": "🚨 NEW 911 CALL",

        "color": 0xC40000,

        "fields": [
            {
                "name": "Call ID",
                "value": call_id,
                "inline": False
            },
            {
                "name": "Roblox Username",
                "value": caller,
                "inline": False
            },
            {
                "name": "Location",
                "value": location,
                "inline": False
            },
            {
                "name": "Emergency",
                "value": reason,
                "inline": False
            }
        ],

        "timestamp": iso_now(),

        "thumbnail": {
            "url": CROSS_LOGO_URL
        }
    }


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


    # --------------------------------------------------------
    # REMOVE OLD 911 SYSTEM MESSAGES
    # --------------------------------------------------------

    deleted, failed = clear_911_system_messages()


    # --------------------------------------------------------
    # SEND ORIGINAL IN SERVICE EMBED
    # --------------------------------------------------------

    message = send_discord_message(
        create_in_service_embed()
    )


    if message is None:
        return jsonify({
            "ok": False,
            "error": "Could not send IN SERVICE message"
        }), 502


    # --------------------------------------------------------
    # UPDATE LIVE STATE
    # --------------------------------------------------------

    ems_state["online"] = True

    ems_state["activated_by"] = {
        "username": username,
        "display_name": display_name,
        "user_id": user_id
    }

    ems_state["activated_at"] = iso_now()
    ems_state["revision"] += 1


    print(
        "[911] SYSTEM ONLINE | Activated by:",
        username
    )


    return jsonify({
        "ok": True,
        "online": True,
        "activated_by": username,
        "discord_message_id": message.get("id"),
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


    # Immediately update API state.
    ems_state["online"] = False
    ems_state["revision"] += 1


    # --------------------------------------------------------
    # DELETE:
    #
    # IN SERVICE
    # active 911 calls
    # old OUT OF SERVICE
    #
    # But NOT unrelated channel messages.
    # --------------------------------------------------------

    deleted, failed = clear_911_system_messages()


    # --------------------------------------------------------
    # SEND ORIGINAL OUT OF SERVICE EMBED
    # --------------------------------------------------------

    message = send_discord_message(
        create_out_of_service_embed()
    )


    if message is None:
        return jsonify({
            "ok": False,
            "error": "Could not send OUT OF SERVICE message"
        }), 502


    print(
        "[911] SYSTEM OFFLINE | Deactivated by:",
        username
    )


    return jsonify({
        "ok": True,
        "online": False,
        "deactivated_by": username,
        "discord_message_id": message.get("id"),
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
    # READ / VALIDATE DATA
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # CHECK DISPATCH STATUS
    # --------------------------------------------------------

    if not ems_state["online"]:
        return jsonify({
            "ok": False,
            "error": "911 system is offline"
        }), 409


    # --------------------------------------------------------
    # GENERATE CALL ID
    # --------------------------------------------------------

    call_id = (
        "GSMH-"
        + utc_now().strftime(
            "%Y%m%d-%H%M%S"
        )
        + "-"
        + str(
            user_id or "UNKNOWN"
        )
    )


    # --------------------------------------------------------
    # BUILD CALL EMBED
    # --------------------------------------------------------

    embed = create_911_call_embed(
        call_id=call_id,
        username=username,
        display_name=display_name,
        location=location,
        reason=reason
    )


    # --------------------------------------------------------
    # SEND CALL TO DISCORD
    # --------------------------------------------------------

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
        "| Username:",
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
