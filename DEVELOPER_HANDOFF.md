# Genesys Cloud Click-to-Dial — Developer Handoff

**Document version:** 1.0  
**Date:** August 2026  
**Repository path:** `GenesysCloudScripts/click_to_dial/`  
**Genesys region:** USE1 (`mypurecloud.com`)  
**Status:** Proof-of-concept validated locally; ready for production hardening

---

## 1. Executive summary

This integration lets agents click a phone number in an external CRM and place an **outbound PSTN call** through **Genesys Cloud**, using the **Platform API** (`POST /api/v2/conversations/calls`). The CRM **creates** the conversation; **all call controls** (answer, hold, transfer, disconnect, wrap-up) remain in the **Genesys Cloud web app** at https://apps.mypurecloud.com/.

**Deliberate design choices:**

| Decision | Rationale |
|----------|-----------|
| **No embedded softphone** | Avoids Embeddable Framework complexity; agents use the standard Genesys web client they already know. |
| **OAuth Authorization Code** | `POST /api/v2/conversations/calls` requires a **user context** token. Client Credentials returns `not.a.user` (HTTP 400). |
| **Python + Flask backend** | Matches existing `GenesysCloudScripts` repo patterns; server holds client secret securely. |
| **Outbound queue (`callFromQueueId`)** | Places calls on behalf of a queue for correct caller ID and reporting. |

**Critical agent setting (validated in POC):** Each agent must enable **“Placing calls with another app?”** in Genesys Cloud **Phone Settings**. Without this, the API may return success but the interaction stalls with only an agent participant in `contacting` state and console warnings about **missing participants**.

---

## 2. Solution architecture

### 2.1 High-level flow

```
┌─────────────────────┐         ┌──────────────────────────┐
│   CRM (browser)     │         │  Genesys Cloud web app   │
│   Flask + HTML      │         │  apps.mypurecloud.com    │
│                     │         │                          │
│  • OAuth login      │         │  • WebRTC phone          │
│  • Click phone #    │         │  • On Queue              │
│  • POST /api/dial   │         │  • Call controls         │
└─────────┬───────────┘         └────────────┬─────────────┘
          │                                  │
          │  Authorization Code OAuth        │  Same agent session
          │  (agent access token)            │  (separate browser tab)
          ▼                                  ▼
┌─────────────────────────────────────────────────────────────┐
│              Genesys Cloud Platform API (USE1)              │
│              https://api.mypurecloud.com                    │
│                                                             │
│  POST /api/v2/conversations/calls                           │
│    • phoneNumber (E.164 destination)                        │
│    • callFromQueueId (outbound queue GUID)                  │
│    • attributes (optional CRM context)                      │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Sequence (happy path)

1. Agent opens **Genesys Cloud web app** → logs in → selects **WebRTC phone** → goes **On Queue** on the outbound queue → enables **“Placing calls with another app?”** in Phone Settings.
2. Agent opens **CRM** → redirected to `login.mypurecloud.com` → OAuth Authorization Code → CRM session stores access/refresh tokens + user profile.
3. Agent clicks a phone number in a CRM record.
4. Browser `fetch` → CRM backend `POST /api/dial`.
5. Backend calls `ConversationsApi.post_conversations_calls()` with the agent’s token.
6. Genesys creates conversation (agent leg + customer PSTN leg).
7. Agent manages the live call in the **Genesys web app** tab.

### 2.3 What the CRM does *not* do

- Does not host audio or WebRTC.
- Does not embed the Genesys softphone widget.
- Does not use Client Credentials for dialing.
- Does not replace Genesys recording, compliance, or wrap-up policies (org policies still apply).

---

## 3. Repository structure

```
GenesysCloudScripts/
├── requirements.txt              # Includes Flask + PureCloudPlatformClientV2
└── click_to_dial/
    ├── app.py                    # Flask routes, dial logic, CRM sample data
    ├── genesys_auth.py           # OAuth URL build, token exchange, region host
    ├── DEVELOPER_HANDOFF.md      # This document
    ├── README.md                 # Quick start
    ├── .env                      # Local secrets (gitignored) — create from template below
    ├── templates/
    │   ├── crm.html              # Fake CRM UI + click-to-dial JavaScript
    │   └── login.html            # OAuth error display
    └── static/
        └── crm.css               # Styles
```

### 3.1 Key source files

| File | Responsibility |
|------|----------------|
| `app.py` | Flask app; OAuth routes; `POST /api/dial`; E.164 normalization; `CreateCallRequest` assembly |
| `genesys_auth.py` | Region host (`api.mypurecloud.com`); authorize URL; code→token exchange; token→`ApiClient` |
| `templates/crm.html` | Renders account table; JavaScript calls `/api/dial` on phone click |
| `genesys_auth.read_oauth_settings()` | Validates required env vars at runtime |

---

## 4. Genesys Cloud configuration

### 4.1 OAuth client (Admin)

**Path:** Admin → Integrations → OAuth → Add Client

| Setting | Value |
|---------|--------|
| **Grant type** | **Authorization Code** |
| **Redirect URI** | Dev: `http://localhost:5000/oauth/callback` |
| | Prod: `https://<your-crm-host>/oauth/callback` (must match exactly) |
| **Embeddable Framework** | **Not required** for this integration |

**OAuth scopes** (enable on the client and authorize for the org):

| Scope | Purpose |
|-------|---------|
| `users:readonly` | `GET /api/v2/users/me` after login |
| `conversations` | `POST /api/v2/conversations/calls` (create/modify conversations) |

Scopes alone are not sufficient — the signed-in **user** must also have Genesys permissions for outbound voice and queue membership.

**Do not use** the existing **Client Credentials** OAuth client from other scripts in this repo (`01_test_connection.py`, etc.). Click-to-dial requires a **separate Authorization Code client**.

### 4.2 Outbound queue

1. Admin → Contact Center → Queues → select outbound queue.
2. Copy the queue **ID** (GUID).
3. Set `GENESYS_OUTBOUND_QUEUE_ID` in environment config.
4. Ensure test/production agents are **members** of this queue.

The API field is `callFromQueueId` (SDK: `call_request.call_from_queue_id`). This sets outbound caller ID context and queue attribution per Genesys documentation.

### 4.3 Agent prerequisites

Each agent using click-to-dial must:

| Requirement | Details |
|-------------|---------|
| **License** | Genesys Cloud voice + web phone capability |
| **Phone type** | Genesys Cloud **WebRTC phone** assigned (unless org routes API dial to another station type) |
| **Queue** | Member of the configured outbound queue |
| **Status** | **On Queue** before clicking dial in CRM |
| **Same user** | CRM OAuth login and Genesys web app login must be the **same Genesys user** (same email) |
| **“Placing calls with another app?”** | **ON** — Calls → Phone Settings → toggle ON |

Reference: [Allow apps to place calls](https://help.genesys.cloud/articles/allow-apps-to-place-calls/)

> **Important:** “Placing calls with another app?” is a **per-user, per-browser** preference. It is **not** configurable via Platform API or Admin bulk settings. Document this in agent onboarding.

### 4.4 USE1 endpoints

| Purpose | URL |
|---------|-----|
| Login / OAuth | `https://login.mypurecloud.com` |
| Platform API | `https://api.mypurecloud.com` |
| Web app | `https://apps.mypurecloud.com/` |

Other regions: change `GENESYS_REGION` and `GENESYS_WEB_APP_URL` accordingly.

---

## 5. Environment configuration

Create `click_to_dial/.env` (never commit):

```env
# OAuth — Authorization Code client (NOT Client Credentials)
GENESYS_OAUTH_CLIENT_ID=your_auth_code_client_id
GENESYS_OAUTH_CLIENT_SECRET=your_auth_code_client_secret
GENESYS_OAUTH_REDIRECT_URI=http://localhost:5000/oauth/callback

# Region (USE1)
GENESYS_REGION=mypurecloud.com
GENESYS_WEB_APP_URL=https://apps.mypurecloud.com/

# Outbound queue GUID
GENESYS_OUTBOUND_QUEUE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Flask
FLASK_SECRET_KEY=long-random-string-for-session-signing
FLASK_PORT=5000
FLASK_DEBUG=1
```

**Production notes:**

- Use HTTPS redirect URI registered in OAuth client.
- Set `FLASK_DEBUG=0`.
- Use a stable `FLASK_SECRET_KEY` (session invalidation if it changes).
- Store secrets in a vault (Azure Key Vault, AWS Secrets Manager, etc.), not plain files.

---

## 6. Local development setup

### 6.1 Prerequisites

- Python 3.10+
- Windows/macOS/Linux
- Genesys Cloud USE1 org access
- OAuth client + outbound queue configured (Section 4)

### 6.2 Install and run

```powershell
cd C:\GenesysCloudScripts
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Configure .env (see Section 5)
python click_to_dial\app.py
```

Open http://localhost:5000

### 6.3 Test procedure

1. **Genesys web app tab:** Log in → WebRTC connected → On Queue → **“Placing calls with another app?” = ON**.
2. **CRM tab:** Log in via OAuth (same user).
3. Click a **real, routable** E.164 number (not placeholder samples unless updated).
4. Confirm in Genesys web app: interaction appears with **agent + customer** participants.
5. Complete call controls (hold, transfer, disconnect, wrap-up) in Genesys only.

**Health check:** `GET http://localhost:5000/health` → `{"status":"ok"}`

---

## 7. Application API (CRM backend)

### 7.1 Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | Session | CRM home page |
| `GET` | `/login` | None | Redirects to Genesys OAuth authorize |
| `GET` | `/oauth/callback` | None | Exchanges code for tokens; loads user profile |
| `POST` | `/logout` | Session | Clears session |
| `POST` | `/api/dial` | Session | Creates outbound call |
| `GET` | `/health` | None | Health probe |

### 7.2 `POST /api/dial`

**Request body (JSON):**

```json
{
  "phone": "+17574704567",
  "name": "Jane Doe",
  "account_id": "ACCT-1001"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `phone` | Yes | Destination number; normalized to E.164 server-side |
| `name` | No | Contact name → conversation attribute `crmContactName` |
| `account_id` | No | CRM account ID → conversation attribute `crmAccountId` |

**Success response (HTTP 200):**

```json
{
  "ok": true,
  "conversation_id": "173e47bb-fd4f-4bd6-a82f-feb6a807c12e",
  "dialed": "+17574704567",
  "agent_email": "agent@company.com",
  "message": "Outbound call created. Use the Genesys Cloud web app for call controls ..."
}
```

**Error responses:** HTTP 400 (validation), 502 (Genesys API error with `detail`).

### 7.3 Genesys Platform API call (internal)

The backend builds:

```python
call_request = CreateCallRequest()
call_request.phone_number = "<E.164>"
call_request.call_from_queue_id = "<GENESYS_OUTBOUND_QUEUE_ID>"
call_request.attributes = {
    "crmAccountId": "<account_id>",      # optional
    "crmContactName": "<contact_name>",  # optional
}
ConversationsApi.post_conversations_calls(call_request)
```

**Official references:**

- [Python SDK](https://mypurecloud.github.io/platform-client-sdk-python/)
- [OAuth Authorization Code guide](https://developer.genesys.cloud/authorization/platform-auth/guides/oauth-auth-code-guide)
- [OAuth scopes](https://developer.genesys.cloud/authorization/platform-auth/scopes)
- API: `POST /api/v2/conversations/calls`

---

## 8. Authentication and session model

### 8.1 OAuth Authorization Code flow

1. `GET /login` → redirect to  
   `https://login.mypurecloud.com/oauth/authorize?response_type=code&client_id=...&redirect_uri=...&state=...`
2. User authenticates at Genesys.
3. `GET /oauth/callback?code=...&state=...` → server exchanges code at `POST /oauth/token` (via SDK `get_code_authorization_token`).
4. Server calls `UsersApi.get_users_me()` and stores in Flask session:
   - `access_token`, `refresh_token`
   - `user_id`, `user_name`, `user_email`
5. `state` parameter validated for CSRF protection.

### 8.2 Token refresh

The SDK `ApiClient` is configured with `client_id`, `client_secret`, `access_token`, and `refresh_token`. The SDK can transparently refresh expired access tokens on API calls; refreshed tokens are written back to the Flask session after dial.

### 8.3 Security considerations for production

| Topic | POC behavior | Production recommendation |
|-------|----------------|---------------------------|
| Session storage | Flask cookie session | Encrypted server-side session store (Redis) |
| HTTPS | Localhost HTTP | TLS everywhere; HTTPS redirect URI only |
| Client secret | `.env` file | Secret manager; never in frontend |
| CORS | Same-origin | Explicit CORS policy if SPA on different domain |
| CSRF | OAuth `state` only | Add CSRF token on `POST /api/dial` |
| Token storage | Session cookie | Consider short-lived tokens; secure/httpOnly cookies |

---

## 9. Frontend integration pattern

The POC uses server-rendered HTML (`crm.html`). Production CRM integration options:

### Option A — Keep server-rendered pattern

Embed click-to-dial links/buttons in existing CRM pages; POST to your backend `/api/dial` with session cookie auth.

### Option B — SPA / separate CRM frontend

1. Implement OAuth Authorization Code (or PKCE) in CRM frontend/backend.
2. On phone click, call CRM backend dial endpoint with agent’s session.
3. Do **not** call Genesys API directly from browser (exposes token handling complexity).

### JavaScript pattern (from POC)

```javascript
const response = await fetch('/api/dial', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ phone, name, account_id }),
});
const data = await response.json();
```

Replace hardcoded `CRM_RECORDS` in `app.py` with real CRM database/API queries.

---

## 10. Troubleshooting guide

### 10.1 Common errors

| Symptom | Likely cause | Resolution |
|---------|--------------|------------|
| `not.a.user` (HTTP 400) | Client Credentials used instead of user token | Use Authorization Code OAuth |
| HTTP 403 on dial | Missing scope or user permission | Add `conversations` scope; verify agent roles |
| Redirect URI mismatch | Admin vs `.env` mismatch | Match exactly including scheme/host/path |
| API success, call stuck **Dialing** | Agent station not connected | WebRTC connected; On Queue |
| Console: **missing participants**, agent `contacting` | **“Placing calls with another app?”** OFF | Enable in Genesys Phone Settings |
| Customer never rings | Invalid/fake phone number | Use real E.164 test number |
| Agent never rings | Different user in CRM vs Genesys app | Same email/user in both sessions |

### 10.2 Validated console warning (resolved)

```
Found an interaction with missing participants
participants: [{ purpose: "agent", calls: [{ state: "contacting" }] }]
```

**Root cause:** External app (CRM API) placing call without **“Placing calls with another app?”** enabled.  
**Fix:** Agent enables setting in Genesys web app Phone Settings.

### 10.3 Admin verification

For failed calls, use **conversation ID** from API response:

Admin → Contact Center → Interactions → search by ID → inspect participant list and states.

---

## 11. Production hardening checklist

Use this when moving from POC to production:

- [ ] Deploy CRM backend with HTTPS and production redirect URI
- [ ] Register production redirect URI on OAuth client
- [ ] Move secrets to enterprise secret store
- [ ] Replace `CRM_RECORDS` with live CRM data source
- [ ] Add structured logging (conversation ID, agent ID, dialed number, latency, errors)
- [ ] Add rate limiting on `/api/dial`
- [ ] Add CSRF protection on dial endpoint
- [ ] Document agent onboarding (Phone Settings toggle, On Queue, web app tab)
- [ ] Define queue selection strategy if agents have multiple outbound queues
- [ ] Load test outbound trunk capacity
- [ ] Align conversation attributes (`crmAccountId`, etc.) with Architect screen-pop / analytics
- [ ] Optional: pre-dial diagnostics (`GET /api/v2/users/stations/me`)
- [ ] Optional: monitoring/alerting on dial failure rate

---

## 12. Known limitations and future enhancements

| Limitation | Notes |
|------------|-------|
| Single outbound queue per deployment | `GENESYS_OUTBOUND_QUEUE_ID` is global; multi-queue needs UI or per-agent config |
| No embedded softphone | By design; agents need Genesys web app open |
| Agent phone setting not API-configurable | “Placing calls with another app?” must be set manually per browser |
| Flask dev server | Replace with Gunicorn/uWSGI + reverse proxy for production |
| Sample CRM data | Hardcoded in `app.py` — replace with real integration |

**Suggested enhancements:**

- `/api/diagnostics` — station + queue readiness before dial
- Per-agent queue picker from `GET /api/v2/users/{userId}/queues`
- Screen-pop integration via conversation attributes + Architect
- SSO alignment so CRM and Genesys share identity provider

---

## 13. Reference links

| Resource | URL |
|----------|-----|
| Python SDK docs | https://mypurecloud.github.io/platform-client-sdk-python/ |
| Developer Center | https://developer.genesys.cloud/ |
| OAuth Authorization Code | https://developer.genesys.cloud/authorization/platform-auth/guides/oauth-auth-code-guide |
| OAuth scopes | https://developer.genesys.cloud/authorization/platform-auth/scopes |
| Allow apps to place calls | https://help.genesys.cloud/articles/allow-apps-to-place-calls/ |
| WebRTC troubleshooting | https://help.genesys.cloud/articles/troubleshoot-genesys-cloud-webrtc-phone/ |
| Community: single-participant API issue | https://community.genesys.com/discussion/post-apiv2conversationscalls-creating-interactions-with-a-single-participant |

---

## 14. Contacts and ownership

| Role | Action |
|------|--------|
| **Genesys admin** | OAuth client, scopes, queue, agent licenses |
| **CRM dev team** | Integrate dial endpoint, replace sample data, production deploy |
| **Operations** | Agent training (Phone Settings, On Queue, two-tab workflow) |
| **Genesys Care** | Platform bugs (persistent single-participant issue after config verified) |

---

*End of developer handoff document.*
