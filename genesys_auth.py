"""
Genesys Cloud OAuth (Authorization Code) helpers for the click-to-dial test app.

Uses the logged-in agent's access token — required for POST /api/v2/conversations/calls.
Client Credentials cannot place agent calls.
"""

from __future__ import annotations

import os
import urllib.parse

import PureCloudPlatformClientV2


def apply_genesys_region(region_host: str) -> None:
    """Point the SDK at https://api.<region> (USE1: mypurecloud.com)."""
    region_host = region_host.removeprefix("https://").removeprefix("http://")
    if region_host.lower().startswith("api."):
        region_host = region_host[4:]
    PureCloudPlatformClientV2.configuration.host = f"https://api.{region_host}"


def login_base_url(region_host: str) -> str:
    """OAuth login host, e.g. https://login.mypurecloud.com."""
    region_host = region_host.removeprefix("https://").removeprefix("http://")
    if region_host.lower().startswith("api."):
        region_host = region_host[4:]
    if region_host.lower().startswith("login."):
        region_host = region_host[6:]
    return f"https://login.{region_host}"


def build_authorize_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    region_host: str,
) -> str:
    """Build Genesys OAuth authorize URL for Authorization Code grant."""
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{login_base_url(region_host)}/oauth/authorize?{query}"


def exchange_authorization_code(
    auth_code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> tuple[object, dict]:
    """
    Trade the authorization code for access + refresh tokens.

    Returns (ApiClient, auth_token_info dict from Genesys).
    """
    api_client = PureCloudPlatformClientV2.api_client.ApiClient()
    api_client, token_info = api_client.get_code_authorization_token(
        client_id,
        client_secret,
        auth_code,
        redirect_uri,
    )
    return api_client, token_info


def api_client_from_tokens(
    access_token: str,
    refresh_token: str | None,
    client_id: str,
    client_secret: str,
):
    """Rebuild an ApiClient from tokens stored in the Flask session."""
    api_client = PureCloudPlatformClientV2.api_client.ApiClient()
    api_client.access_token = access_token
    api_client.refresh_token = refresh_token
    api_client.client_id = client_id
    api_client.client_secret = client_secret
    return api_client


def read_oauth_settings() -> dict[str, str]:
    """Load OAuth client settings from environment variables."""
    client_id = os.getenv("GENESYS_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GENESYS_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv(
        "GENESYS_OAUTH_REDIRECT_URI",
        "http://localhost:5000/oauth/callback",
    ).strip()
    region = os.getenv("GENESYS_REGION", "mypurecloud.com").strip()
    queue_id = os.getenv("GENESYS_OUTBOUND_QUEUE_ID", "").strip()

    if not client_id or not client_secret:
        raise ValueError(
            "GENESYS_OAUTH_CLIENT_ID and GENESYS_OAUTH_CLIENT_SECRET must be set."
        )
    if not queue_id:
        raise ValueError("GENESYS_OUTBOUND_QUEUE_ID must be set (outbound queue GUID).")

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "region": region,
        "queue_id": queue_id,
    }
