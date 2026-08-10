# Click-to-Dial Test CRM

Localhost proof-of-concept: fake CRM records, **OAuth Authorization Code** login as the agent, and **Platform API** outbound dial. **No embedded softphone** — agents use the **Genesys Cloud web app** for all call controls.

## Documentation

| Document | Audience |
|----------|----------|
| [README.md](README.md) | Quick start |
| [DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md) | Full architecture, Genesys config, API spec, production checklist |

## Genesys Admin setup

1. **Admin → Integrations → OAuth → Add Client**
   - **Grant type:** Authorization Code (not Client Credentials)
   - **Redirect URI:** `http://localhost:5000/oauth/callback`
   - **Embeddable Framework is not required** for this integration
   - Assign roles that allow:
     - User read (`UsersApi.get_users_me`)
     - **Create outbound conversations** (`POST /api/v2/conversations/calls`)
     - Outbound queue membership for test agents

2. Copy **Client ID** and **Client Secret** into `.env`.

3. **Outbound queue:** Admin → Contact Center → Queues → copy queue **ID** (GUID) → `GENESYS_OUTBOUND_QUEUE_ID`.

4. Test agent must:
   - Be logged into **[Genesys Cloud web app](https://apps.mypurecloud.com/)** (separate browser tab)
   - Use **web phone** in that app (not desk phone only, unless configured)
   - Be a **member** of the outbound queue and **On Queue** before clicking dial in the CRM

## Environment

```powershell
copy click_to_dial\.env.example click_to_dial\.env
# Edit click_to_dial\.env with OAuth client + queue ID
```

## Run

```powershell
pip install -r requirements.txt
python click_to_dial\app.py
```

Open http://localhost:5000

## How it works

1. **CRM sign-in** — OAuth to `login.mypurecloud.com` (USE1); API calls use the agent's token.
2. **Genesys Cloud web app** — agent works in https://apps.mypurecloud.com/ for answer, hold, transfer, disconnect.
3. **Click phone in CRM** — `POST /api/dial` → `ConversationsApi.post_conversations_calls`:
   - `phoneNumber` (E.164)
   - `callFromQueueId` (outbound queue)
   - `attributes` (`crmAccountId`, `crmContactName`)

The CRM only **creates** the conversation; it does not host call controls.

## Troubleshooting

| Symptom | Check |
|--------|--------|
| 403 on dial | OAuth client roles; agent permission to create calls |
| 400 on dial | Agent logged into Genesys web app; web phone On Queue; valid E.164 |
| Call not ringing agent | Same user/email in CRM OAuth and Genesys web app session |
| Redirect error | Redirect URI matches exactly in Admin and `.env` |

SDK docs: https://mypurecloud.github.io/platform-client-sdk-python/
