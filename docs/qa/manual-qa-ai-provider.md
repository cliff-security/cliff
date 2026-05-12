# Manual QA — Tiered AI provider onboarding

Pre-merge smoke test for [IMPL-0011 / ADR-0036](../adr/0036-ai-provider-onboarding.md).
Covers the parts CI can't fully simulate (real OpenRouter handshake,
real OpenCode subprocess, port conflicts, browser behavior).

**Time budget: ~25 minutes if everything works.**

---

## Setup

```bash
# Terminal A — backend (fresh DB)
cd backend
OPENSEC_DATA_DIR=/tmp/opensec-qa \
  OPENSEC_DEMO=true \
  uv run uvicorn opensec.main:app --port 8765 --host 127.0.0.1

# Terminal B — frontend
cd frontend
VITE_BACKEND_URL=http://127.0.0.1:8765 npm run dev -- --port 5174 --host 127.0.0.1
```

Open <http://127.0.0.1:5174/dashboard>. For each section below, keep the
**Network** + **Console** panes of devtools visible.

> If you need a clean slate between tiers: stop the backend, `rm -rf
> /tmp/opensec-qa`, restart.

---

## Tier 1 — Auto-detect *(takes about 2 minutes)*

**Goal**: an `ANTHROPIC_API_KEY` already in your shell → one-click adopt.

1. Stop the backend. Restart with the key in the env:
   ```bash
   ANTHROPIC_API_KEY="<real-anthropic-key>" \
     OPENSEC_DATA_DIR=/tmp/opensec-qa \
     uv run uvicorn opensec.main:app --port 8765 --host 127.0.0.1
   ```
2. Hard-reload `/dashboard`.
   - [ ] Banner appears above the hero: *"We found an Anthropic API
         key in your environment."*
   - [ ] Source text reads `ANTHROPIC_API_KEY env`.
   - [ ] Raw key value does **not** appear anywhere in the banner.
3. Click **Use it**.
   - [ ] Button shows *Connecting…* spinner state briefly.
   - [ ] Banner disappears within a second or two.
   - [ ] Devtools → Network: `POST /api/integrations/ai/autodetect/adopt`
         returns 200.
4. Navigate to **Settings → AI provider**.
   - [ ] Card reads: *"Connected via Anthropic (auto-detected from
         environment)"*.
5. Tail the backend log (`tail -f`) and grep:
   ```bash
   grep -c "$ANTHROPIC_API_KEY" /tmp/opensec-qa-backend.log   # should print 0
   ```
   - [ ] Zero matches — the real key never appears in logs.
6. Quick audit check:
   ```bash
   curl -s http://127.0.0.1:8765/api/audit | jq '.events[] | select(.event_type == "ai_integration.adopt")'
   ```
   - [ ] Event present, `verb` is `ANTHROPIC_API_KEY env`.

### Negative paths

7. With `ANTHROPIC_API_KEY=sk-ant-deliberately-bogus` restart, then
   click **Use it**.
   - [ ] Banner stays visible.
   - [ ] Inline error: *"We couldn't validate that key. Try the connect
         flow instead."*

---

## Tier 2 — OpenRouter OAuth *(takes about 3 minutes — needs a real OpenRouter account)*

**Goal**: cold install → two clicks → connected.

1. Wipe state: stop backend, `rm -rf /tmp/opensec-qa`, restart (no key
   env vars).
2. Settings → AI provider → **Connect AI provider**.
   - [ ] Modal opens. Primary CTA: *"Connect with OpenRouter"*.
   - [ ] Secondary link below: *"I have my own API key →"*.
3. Click **Connect with OpenRouter**.
   - [ ] New tab opens to `https://openrouter.ai/auth?...`.
   - [ ] URL contains `code_challenge=`, `code_challenge_method=S256`,
         and `state=`.
   - [ ] Modal switches to *"Waiting for you to authorize on
         openrouter.ai…"* with a spinner.
   - [ ] *"Open authorization page again"* link visible below the
         spinner.
4. In the OpenRouter tab, sign in (Google or GitHub one-click).
   Authorize OpenSec.
   - [ ] OpenRouter shows *"You can close this tab."*
5. Switch back to OpenSec.
   - [ ] Modal flips to success card within ~2s.
   - [ ] Card reads: *"Add five dollars of credits to unlock every
         model, or try free sponsored models now."*
   - [ ] Two actions: *"Add credits at openrouter.ai →"* (opens new
         tab) and *"Start using OpenSec"* (closes modal).
6. Settings page:
   - [ ] *"Connected via OpenRouter as <your-email>"*.
7. Grep logs:
   ```bash
   # The OAuth code and the resulting key should never appear.
   grep -cE "sk-or-v1|code_verifier" /tmp/opensec-qa-backend.log
   ```
   - [ ] Zero matches.

### Port 3000 conflict

8. While modal is closed, occupy port 3000:
   ```bash
   python3 -m http.server 3000
   ```
9. Settings → **Switch provider** → **Connect with OpenRouter**.
   - [ ] HTTP 409 from `POST /api/integrations/ai/openrouter/start`.
   - [ ] Modal renders the *"Port 3000 is busy"* card.
   - [ ] Two actions: *"Use my own API key"* (switches to BYOK) and
         *"Try again"* (retries the start endpoint).
10. Kill `python3 -m http.server` and click **Try again**.
    - [ ] Listener binds successfully, modal flips to waiting state.

### Timeout

11. Start OAuth, do not authorize on openrouter.ai, wait 5 minutes.
    - [ ] Modal flips to *"Took a bit too long"* with retry button.

### Denied

12. Start OAuth, click **Deny** on openrouter.ai.
    - [ ] Modal flips to *"No problem"* with retry button.
    - [ ] No alarming red iconography or apologetic copy.

---

## Tier 3 — Direct BYOK *(takes about 3 minutes — needs a real key for happy path)*

**Goal**: paste-and-go for Anthropic-direct users.

1. From the connect modal, click **I have my own API key →**.
   - [ ] Provider dropdown defaults to **Anthropic**.
   - [ ] Instructions panel lists the three steps to get a key.
   - [ ] *"Open Anthropic console →"* button is present.
2. Click the console button.
   - [ ] New tab opens to <https://console.anthropic.com/settings/keys>.
3. Paste a **real, valid** Anthropic key.
   - [ ] **Save** button stays disabled until the field has ≥ 4 chars.
   - [ ] When you click Save, the button shows *Validating…* and
         spinner.
   - [ ] Within ~3s, modal closes; Settings shows connected state.
4. Paste an **invalid** key (`sk-ant-bogus123`). Click Save.
   - [ ] Inline error: *"This key was rejected by Anthropic."*
   - [ ] Save button is enabled again (so the user can edit + retry).
5. Disconnect network (turn off Wi-Fi briefly). Paste a key. Click Save.
   - [ ] Inline error: *"Can't reach Anthropic. Check your internet
         connection."*

### OpenAI variant

6. Change the dropdown to **OpenAI**.
   - [ ] Subtitle appears under dropdown: *"OpenSec is tuned for Claude.
         Your choice should still work, but Claude tends to perform
         better on security reasoning."*
   - [ ] Instructions update to OpenAI-specific steps.
   - [ ] Console button now reads *"Open OpenAI console →"* and points
         to <https://platform.openai.com/api-keys>.

### Custom variant

7. Change the dropdown to **Custom (OpenAI-compatible)**.
   - [ ] *"Base URL"* and *"Model"* fields appear above the key field.
   - [ ] Save stays disabled until both new fields + key are filled.

---

## Model override *(takes about 1 minute)*

1. Stop backend. Restart with override env var:
   ```bash
   OPENSEC_AI_MODEL_OVERRIDE_ANTHROPIC=claude-opus-4-1 \
     OPENSEC_DATA_DIR=/tmp/opensec-qa \
     uv run uvicorn opensec.main:app --port 8765 --host 127.0.0.1
   ```
2. Watch the boot log.
   - [ ] WARNING line: *"AI model override active for anthropic:
         claude-opus-4-1. OpenSec is tuned for claude-sonnet-4-6;
         performance may vary."*
3. With an Anthropic provider already connected, open Settings.
   - [ ] Warning chip below provider name: *"Custom model:
         claude-opus-4-1. Default recommended."*
4. Open a workspace, then inspect:
   ```bash
   cat /tmp/opensec-qa/workspaces/<workspace_id>/opencode.json
   ```
   - [ ] `model` field reads `claude-opus-4-1`, not `claude-sonnet-4-6`.
   - [ ] No `api_key`, no `sk-` substring anywhere in the file.
5. Unset the env var, restart, reload Settings.
   - [ ] Chip disappears.

---

## OpenCode env injection *(takes about 2 minutes — needs a real key)*

**Goal**: confirm the workspace subprocess has `*_API_KEY` in its env.

1. Connect any provider via the flows above.
2. Click into any finding and open the workspace.
3. On the host:
   ```bash
   ps aux | grep opencode      # find a workspace pid (cwd = workspaces/<id>)
   ```
4. macOS:
   ```bash
   ps eww <pid> | tr ' ' '\n' | grep -E 'API_KEY|TOKEN'
   ```
   Linux:
   ```bash
   tr '\0' '\n' < /proc/<pid>/environ | grep -E 'API_KEY|TOKEN'
   ```
   - [ ] The expected env var is present (`ANTHROPIC_API_KEY`,
         `OPENROUTER_API_KEY`, or `OPENAI_API_KEY` depending on
         provider).
   - [ ] Its value matches the key you connected.
5. Disconnect via Settings → **Disconnect**.
   - [ ] Confirmation dialog surfaces the *"To fully revoke this key
         from OpenRouter's side, visit openrouter.ai/settings/keys"*
         copy.
   - [ ] After confirming, Settings card flips to *"Not connected."*
6. Open a fresh workspace.
   ```bash
   ps eww <new-pid> | tr ' ' '\n' | grep -E 'ANTHROPIC|OPENROUTER|OPENAI'
   ```
   - [ ] No AI env vars present in the new subprocess.

---

## Migration banner *(takes about 1 minute)*

**Goal**: existing paste-flow users see a one-time prompt.

1. Manually insert a legacy `app_setting` row to simulate an existing
   user:
   ```bash
   sqlite3 /tmp/opensec-qa/opensec.db \
     "INSERT INTO app_setting (key, value, updated_at) VALUES ('api_key:anthropic', '{\"key\":\"sk-x\",\"key_masked\":\"sk-...x\"}', datetime('now'));"
   ```
2. Reload `/dashboard` with the AI provider **not** connected.
   - [ ] *"Try our new one-click AI setup."* banner appears.
3. Click *Not now*.
   - [ ] Banner disappears.
4. Reload.
   - [ ] Banner stays hidden.
5. In devtools:
   ```js
   localStorage.removeItem('opensec.aiMigrationBanner.dismissed');
   localStorage.setItem(
     'opensec.aiMigrationBanner.firstShownAt',
     String(Date.now() - 31 * 24 * 60 * 60 * 1000),
   );
   ```
   Reload.
   - [ ] Banner does **not** render (30-day auto-hide kicked in).

---

## Design system compliance *(takes about 2 minutes)*

Open the connect modal. With devtools → **Computed**:

- [ ] No element on the modal has `border-style: solid` with a
      `border-width: 1px` (use the Elements panel filter).
- [ ] Primary CTAs (Connect / Save / Start using OpenSec) compute
      `background-color: rgb(77, 68, 227)` → `#4d44e3`.
- [ ] Body text computes a non-pure-black color (something close to
      `#2b3437`).
- [ ] Manrope is loaded for `h2.font-headline`.
- [ ] Material Symbols Outlined is loaded for the arrow icon on the
      primary OpenRouter card.
- [ ] All button labels are sentence case (*"Connect with OpenRouter"*,
      *"Start using OpenSec"* — never *"Connect With OpenRouter"*).

---

## Dismissibility & gating *(takes about 1 minute)*

1. Open the connect modal, then press **Esc**.
   - [ ] Modal closes.
2. Re-open via Settings, then click on the dimmed backdrop outside the
   panel.
   - [ ] Modal closes.
3. With AI **unconfigured**, navigate to a workspace.
   - [ ] Agent CTAs are disabled.
   - [ ] Hovering shows tooltip: *"Configure AI provider first."*
   - [ ] Clicking opens the connect modal at the *picking-method* card.

---

## Sign-off

Tester: ____________________     Date: ____________________

All sections passed? __ Yes / __ No

If no, list which boxes failed and attach screenshots:
