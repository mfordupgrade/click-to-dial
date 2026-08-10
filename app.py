"""
Click-to-dial test CRM (Flask + Genesys Cloud Platform API).

Flow
----
1. Agent signs in with Genesys OAuth (Authorization Code) — acts as that user.
2. Agent keeps the Genesys Cloud **web app** open in a separate tab for call controls
   (no embedded softphone in the CRM).
3. Agent clicks a phone number on a fake CRM record.
4. Backend calls POST /api/v2/conversations/calls with callFromQueueId.

Run (from repo root, venv activated):
    python click_to_dial/app.py

Then open http://localhost:5000
"""

from __future__ import annotations

import os
import re
import secrets
import sys
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import PureCloudPlatformClientV2
from PureCloudPlatformClientV2.rest import ApiException

# Allow imports when running as python click_to_dial/app.py
CLICK_TO_DIAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CLICK_TO_DIAL_DIR.parent
if str(CLICK_TO_DIAL_DIR) not in sys.path:
    sys.path.insert(0, str(CLICK_TO_DIAL_DIR))

from genesys_auth import (  # noqa: E402
    api_client_from_tokens,
    apply_genesys_region,
    build_authorize_url,
    exchange_authorization_code,
    read_oauth_settings,
)


# ---------------------------------------------------------------------------
# Fake CRM records for localhost testing — replace with real CRM data later.
# ---------------------------------------------------------------------------
CRM_RECORDS = [
    {
        "name": "Jane Doe",
        "phone": "+17574704567",
        "account_id": "ACCT-1001",
        "company": "Acme Insurance",
    },
    {
        "name": "Robert Chen",
        "phone": "+13175550200",
        "account_id": "ACCT-2048",
        "company": "Northwind Health",
    },
    {
        "name": "Maria Garcia",
        "phone": "+13175550300",
        "account_id": "ACCT-3099",
        "company": "Summit Financial",
    },
]


def load_env_files() -> None:
    """Prefer click_to_dial/.env, then project .env / .env.prod."""
    for candidate in (
        CLICK_TO_DIAL_DIR / ".env",
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / ".env.prod",
    ):
        if candidate.is_file():
            load_dotenv(candidate)
            return
    load_dotenv()


load_env_files()

app = Flask(
    __name__,
    template_folder=str(CLICK_TO_DIAL_DIR / "templates"),
    static_folder=str(CLICK_TO_DIAL_DIR / "static"),
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))


def login_required(view_func):
    """Redirect to login when the Flask session has no Genesys access token."""

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("access_token"):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def get_authenticated_api_client():
    """
    Build an SDK ApiClient from session tokens (auto-refreshes when configured).
    """
    settings = read_oauth_settings()
    return api_client_from_tokens(
        access_token=session["access_token"],
        refresh_token=session.get("refresh_token"),
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
    )


def normalize_e164(phone: str) -> str:
    """Basic E.164 check — Genesys expects + and country code for PSTN."""
    cleaned = phone.strip()
    if not cleaned.startswith("+"):
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) == 10:
            cleaned = f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            cleaned = f"+{digits}"
        else:
            cleaned = f"+{digits}" if digits else cleaned
    return cleaned


@app.route("/")
@login_required
def crm_home():
    """Fake CRM page — click-to-dial only; call controls stay in Genesys Cloud web app."""
    genesys_web_app_url = os.getenv(
        "GENESYS_WEB_APP_URL",
        "https://apps.mypurecloud.com/",
    ).strip()
    return render_template(
        "crm.html",
        records=CRM_RECORDS,
        user_name=session.get("user_name", ""),
        user_email=session.get("user_email", ""),
        genesys_web_app_url=genesys_web_app_url,
    )


@app.route("/login")
def login():
    """Start OAuth Authorization Code flow."""
    if session.get("access_token"):
        return redirect(url_for("crm_home"))

    settings = read_oauth_settings()
    apply_genesys_region(settings["region"])

    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state

    authorize_url = build_authorize_url(
        client_id=settings["client_id"],
        redirect_uri=settings["redirect_uri"],
        state=state,
        region_host=settings["region"],
    )
    return redirect(authorize_url)


@app.route("/oauth/callback")
def oauth_callback():
    """OAuth redirect handler — exchange code for tokens and load user profile."""
    error = request.args.get("error")
    if error:
        return render_template(
            "login.html",
            error=f"Genesys login failed: {error}",
        ), 400

    returned_state = request.args.get("state", "")
    if not returned_state or returned_state != session.pop("oauth_state", None):
        return render_template("login.html", error="Invalid OAuth state (CSRF check)."), 400

    auth_code = request.args.get("code")
    if not auth_code:
        return render_template("login.html", error="No authorization code returned."), 400

    settings = read_oauth_settings()
    apply_genesys_region(settings["region"])

    try:
        api_client, token_info = exchange_authorization_code(
            auth_code=auth_code,
            client_id=settings["client_id"],
            client_secret=settings["client_secret"],
            redirect_uri=settings["redirect_uri"],
        )
    except Exception as exc:
        return render_template("login.html", error=f"Token exchange failed: {exc}"), 400

    session["access_token"] = api_client.access_token
    session["refresh_token"] = token_info.get("refresh_token") or api_client.refresh_token

    try:
        users_api = PureCloudPlatformClientV2.UsersApi(api_client)
        current_user = users_api.get_users_me()
    except ApiException as api_error:
        session.clear()
        return render_template(
            "login.html",
            error=f"Could not load user profile (HTTP {api_error.status}).",
        ), 400

    session["user_id"] = getattr(current_user, "id", None)
    session["user_name"] = getattr(current_user, "name", None) or ""
    session["user_email"] = getattr(current_user, "email", None) or ""

    return redirect(url_for("crm_home"))


@app.route("/logout", methods=["POST"])
def logout():
    """Clear session and return to login."""
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/dial", methods=["POST"])
@login_required
def api_dial():
    """
    Click-to-dial: create outbound PSTN call for the logged-in agent.

    Uses POST /api/v2/conversations/calls with callFromQueueId (outbound queue).
    The agent must be logged into the Genesys Cloud web app with web phone active
    there — this CRM does not host call controls.
    """
    payload = request.get_json(silent=True) or {}
    phone_raw = (payload.get("phone") or "").strip()
    contact_name = (payload.get("name") or "").strip()
    account_id = (payload.get("account_id") or "").strip()

    if not phone_raw:
        return jsonify({"ok": False, "error": "Phone number is required."}), 400

    phone_number = normalize_e164(phone_raw)
    if not re.match(r"^\+\d{8,15}$", phone_number):
        return jsonify(
            {"ok": False, "error": f"Invalid E.164 phone number: {phone_number!r}"}
        ), 400

    settings = read_oauth_settings()
    apply_genesys_region(settings["region"])

    api_client = get_authenticated_api_client()
    conversations_api = PureCloudPlatformClientV2.ConversationsApi(api_client)

    call_request = PureCloudPlatformClientV2.CreateCallRequest()
    call_request.phone_number = phone_number
    call_request.call_from_queue_id = settings["queue_id"]

    # Pass CRM context on the conversation for screen-pop / reporting (optional).
    attributes: dict[str, str] = {}
    if account_id:
        attributes["crmAccountId"] = account_id
    if contact_name:
        attributes["crmContactName"] = contact_name
    if attributes:
        call_request.attributes = attributes

    try:
        response = conversations_api.post_conversations_calls(call_request)
    except ApiException as api_error:
        message = f"Genesys API error (HTTP {api_error.status})."
        if api_error.status == 403:
            message += " Check OAuth client roles for outbound/conversation create."
        elif api_error.status == 400:
            message += (
                " Is the agent logged into the Genesys Cloud web app with web phone On Queue?"
            )
        return jsonify({"ok": False, "error": message, "detail": str(api_error)}), 502

    # Persist refreshed tokens if the SDK rotated them during the call.
    if getattr(api_client, "access_token", None):
        session["access_token"] = api_client.access_token
    if getattr(api_client, "refresh_token", None):
        session["refresh_token"] = api_client.refresh_token

    conversation_id = getattr(response, "id", None) or ""
    return jsonify(
        {
            "ok": True,
            "conversation_id": conversation_id,
            "dialed": phone_number,
            "agent_email": session.get("user_email", ""),
            "message": (
                "Outbound call created. Use the Genesys Cloud web app for call controls "
                "(answer, hold, transfer, disconnect)."
            ),
        }
    )


@app.route("/health")
def health():
    """Simple health check for localhost."""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    print(f"Click-to-dial CRM: http://localhost:{port}")
    print("Ensure GENESYS_OAUTH_* and GENESYS_OUTBOUND_QUEUE_ID are set in .env")
    app.run(host="127.0.0.1", port=port, debug=debug)
