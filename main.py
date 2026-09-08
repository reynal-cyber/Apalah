import asyncio
import html
import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from telethon import TelegramClient, events
from telethon.sessions import StringSession


# =========================================================
# CONFIG
# =========================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

ADMIN_ID = int(os.environ["ADMIN_ID"])
PANEL_PASSWORD = os.environ["PANEL_PASSWORD"]

PORT = int(os.getenv("PORT", "8000"))

SESSIONS_FILE = Path("sessions.json")

app = FastAPI()

clients = {}
sessions_lock = asyncio.Lock()

web_token = secrets.token_urlsafe(32)


# =========================================================
# JSON STORAGE
# =========================================================

def load_sessions():

    if not SESSIONS_FILE.exists():

        SESSIONS_FILE.write_text(
            json.dumps({"sessions": []}, indent=2),
            encoding="utf-8"
        )

    try:

        data = json.loads(
            SESSIONS_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            return {"sessions": []}

        return data

    except Exception:

        return {"sessions": []}


def save_sessions(data):

    temp = SESSIONS_FILE.with_suffix(".tmp")

    temp.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

    temp.replace(SESSIONS_FILE)


# =========================================================
# USERBOT
# =========================================================

async def start_userbot(session_string):

    async with sessions_lock:

        if session_string in clients:

            return True, "already_running"

        client = TelegramClient(
            StringSession(session_string),
            API_ID,
            API_HASH,
            auto_reconnect=True
        )

        try:

            await client.connect()

            if not await client.is_user_authorized():

                await client.disconnect()

                return False, "not_authorized"

            me = await client.get_me()

            @client.on(events.ChatAction)
            async def join_handler(event):

                if not (
                    event.user_joined
                    or event.user_added
                ):
                    return

                try:

                    await event.delete()

                    print(
                        f"[{me.id}] "
                        f"deleted join message "
                        f"in {event.chat_id}"
                    )

                except Exception as e:

                    print(
                        f"[{me.id}] "
                        f"delete error: {e}"
                    )

            clients[session_string] = {
                "client": client,
                "id": me.id,
                "name": me.first_name or "",
                "username": me.username or ""
            }

            print(
                f"[USERBOT ONLINE] "
                f"{me.id}"
            )

            return True, "started"

        except Exception as e:

            try:
                await client.disconnect()
            except Exception:
                pass

            print(
                f"[USERBOT ERROR] {e}"
            )

            return False, str(e)


async def stop_userbot(session_string):

    async with sessions_lock:

        info = clients.pop(
            session_string,
            None
        )

        if not info:
            return False

        try:
            await info["client"].disconnect()
        except Exception:
            pass

        return True


async def start_saved_sessions():

    data = load_sessions()

    for session in data.get(
        "sessions",
        []
    ):

        asyncio.create_task(
            start_userbot(session)
        )

        await asyncio.sleep(0.5)


# =========================================================
# WEB AUTH
# =========================================================

def check_web_auth(request: Request):

    return (
        request.cookies.get(
            "panel_token"
        ) == web_token
    )


LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Telegram Manager</title>
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<style>

body {
    background:#111;
    color:#eee;
    font-family:Arial;
    max-width:600px;
    margin:50px auto;
    padding:20px;
}

input,button {
    width:100%;
    padding:12px;
    margin-top:10px;
    box-sizing:border-box;
}

button {
    cursor:pointer;
}

</style>
</head>

<body>

<h2>Telegram Manager</h2>

<form method="post" action="/login">

<input
    type="password"
    name="password"
    placeholder="Panel password"
    required
>

<button>
Login
</button>

</form>

</body>
</html>
"""


@app.get(
    "/login",
    response_class=HTMLResponse
)
async def login_page():

    return LOGIN_HTML


@app.post("/login")
async def login(
    password: str = Form(...)
):

    if not secrets.compare_digest(
        password,
        PANEL_PASSWORD
    ):

        return HTMLResponse(
            "Invalid password",
            status_code=401
        )

    response = RedirectResponse(
        "/",
        status_code=303
    )

    response.set_cookie(
        "panel_token",
        web_token,
        httponly=True,
        secure=True,
        samesite="strict"
    )

    return response


# =========================================================
# DASHBOARD
# =========================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
async def dashboard(
    request: Request
):

    if not check_web_auth(request):

        return RedirectResponse(
            "/login"
        )

    data = load_sessions()

    rows = ""

    for index, session in enumerate(
        data.get("sessions", []),
        start=1
    ):

        info = clients.get(session)

        if info:

            name = html.escape(
                info["name"]
            )

            username = html.escape(
                info["username"]
            )

            status = "🟢 ONLINE"

            uid = info["id"]

        else:

            name = "Unknown"
            username = "-"
            status = "🔴 OFFLINE"
            uid = "-"

        rows += f"""
        <tr>
            <td>{index}</td>
            <td>{name}</td>
            <td>{username}</td>
            <td>{uid}</td>
            <td>{status}</td>

            <td>

            <form
                method="post"
                action="/session/delete/{index - 1}"
            >

            <button>
            Delete
            </button>

            </form>

            </td>
        </tr>
        """

    return f"""
<!DOCTYPE html>

<html>

<head>

<title>Telegram Manager</title>

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<style>

body {{
    background:#111;
    color:#eee;
    font-family:Arial;
    padding:20px;
}}

table {{
    width:100%;
    border-collapse:collapse;
}}

td,th {{
    border:1px solid #444;
    padding:8px;
}}

input,button {{
    padding:10px;
    margin-top:8px;
}}

input {{
    width:100%;
    box-sizing:border-box;
}}

button {{
    cursor:pointer;
}}

</style>

</head>

<body>

<h1>Telegram Userbot Manager</h1>

<h2>Userbots</h2>

<table>

<tr>
<th>#</th>
<th>Name</th>
<th>Username</th>
<th>ID</th>
<th>Status</th>
<th>Action</th>
</tr>

{rows}

</table>

<hr>

<h2>Add Session</h2>

<form
method="post"
action="/session/add"
>

<textarea
name="session"
placeholder="Paste StringSession"
required
style="
width:100%;
height:120px;
box-sizing:border-box;
"
></textarea>

<button>
Add & Start
</button>

</form>

<p>
Session harus sudah terautentikasi.
Jangan memasukkan OTP atau password 2FA di panel.
</p>

</body>

</html>
"""


# =========================================================
# ADD SESSION
# =========================================================

@app.post(
    "/session/add"
)
async def add_session(
    request: Request,
    session: str = Form(...)
):

    if not check_web_auth(request):

        return RedirectResponse(
            "/login"
        )

    session = session.strip()

    if not session:

        return RedirectResponse(
            "/"
        )

    data = load_sessions()

    sessions = data.setdefault(
        "sessions",
        []
    )

    if session not in sessions:

        sessions.append(session)

        save_sessions(data)

    ok, reason = await start_userbot(
        session
    )

    return RedirectResponse(
        "/",
        status_code=303
    )


# =========================================================
# DELETE SESSION
# =========================================================

@app.post(
    "/session/delete/{index}"
)
async def delete_session(
    request: Request,
    index: int
):

    if not check_web_auth(request):

        return RedirectResponse(
            "/login"
        )

    data = load_sessions()

    sessions = data.get(
        "sessions",
        []
    )

    if (
        index < 0
        or index >= len(sessions)
    ):

        return RedirectResponse(
            "/"
        )

    session = sessions[index]

    await stop_userbot(
        session
    )

    sessions.pop(index)

    save_sessions(data)

    return RedirectResponse(
        "/",
        status_code=303
    )


# =========================================================
# TELEGRAM CONTROL BOT
# =========================================================

control_bot = TelegramClient(
    "control_bot",
    API_ID,
    API_HASH,
    auto_reconnect=True
)


def is_admin(event):

    return event.sender_id == ADMIN_ID


@control_bot.on(
    events.NewMessage(
        pattern=r"^/start$"
    )
)
async def start_command(event):

    if not is_admin(event):
        return

    await event.reply(
        "🤖 Manager aktif.\n\n"
        "/status\n"
        "/list\n"
        "/panel"
    )


@control_bot.on(
    events.NewMessage(
        pattern=r"^/status$"
    )
)
async def status_command(event):

    if not is_admin(event):
        return

    if not clients:

        await event.reply(
            "🔴 Tidak ada userbot aktif."
        )

        return

    text = "📊 STATUS\n\n"

    for info in clients.values():

        state = (
            "🟢 ONLINE"
            if info["client"].is_connected()
            else "🔴 OFFLINE"
        )

        username = (
            f"@{info['username']}"
            if info["username"]
            else "-"
        )

        text += (
            f"👤 {info['name']}\n"
            f"🆔 {info['id']}\n"
            f"📛 {username}\n"
            f"📡 {state}\n\n"
        )

    await event.reply(text)


@control_bot.on(
    events.NewMessage(
        pattern=r"^/list$"
    )
)
async def list_command(event):

    if not is_admin(event):
        return

    data = load_sessions()

    sessions = data.get(
        "sessions",
        []
    )

    await event.reply(
        f"📋 Session tersimpan: "
        f"{len(sessions)}\n"
        f"🟢 Aktif: {len(clients)}"
    )


@control_bot.on(
    events.NewMessage(
        pattern=r"^/panel$"
    )
)
async def panel_command(event):

    if not is_admin(event):
        return

    # Ganti dengan URL publik Infrlo kamu
    PANEL_URL = os.environ.get(
        "PANEL_URL",
        "https://YOUR-DOMAIN"
    )

    await event.reply(
        f"🔐 Admin Panel:\n{PANEL_URL}"
    )


# =========================================================
# RUN
# =========================================================

async def telegram_loop():

    await control_bot.start(
        bot_token=BOT_TOKEN
    )

    print(
        "[CONTROL BOT] ONLINE"
    )

    await start_saved_sessions()

    await control_bot.run_until_disconnected()


async def web_loop():

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )

    server = uvicorn.Server(config)

    await server.serve()


async def main():

    await asyncio.gather(
        telegram_loop(),
        web_loop()
    )


if __name__ == "__main__":

    asyncio.run(main())
