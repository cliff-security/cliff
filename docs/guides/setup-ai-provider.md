# Setting up an AI provider

Cliff uses an AI provider to enrich findings, plan fixes, and write the
remediation PRs. We support three paths to a working setup — in order of
how few clicks they take.

> **You can ignore this whole page if you already have an `ANTHROPIC_API_KEY`,
> `OPENROUTER_API_KEY`, or `OPENAI_API_KEY` in your shell.** Open the dashboard
> and click *Use it* on the banner that appears at the top.

---

## What Cliff is optimized for

Cliff is tuned for **Claude Sonnet 4.6**. We picked it because it's the
model that does the security-reasoning work best on the agents we ship.
Whichever path you pick, Cliff will configure Sonnet 4.6 for you
automatically (or the best Claude available on the provider you choose).

You can override the model — see [Model override](#model-override) below —
but the default is what we test against.

---

## Tier 1 — Auto-detect *(1 click)*

If you already use an AI tool on your machine, Cliff will offer to use
its key on first boot. This is the fastest path.

Cliff scans these locations, in order, and stops at the first one with
a key:

1. `~/.claude/.credentials.json` — Claude Code's local credentials file.
2. `ANTHROPIC_API_KEY` environment variable.
3. `OPENROUTER_API_KEY` environment variable.
4. `OPENAI_API_KEY` environment variable.
5. `~/.aider/.env` — Aider's `.env` file.
6. `~/.config/openai/auth.json` (or `config`) — the OpenAI CLI config.

The scan is **read-only**. Nothing is stored in Cliff until you click
*Use it* on the banner.

If anything goes wrong (the file is malformed, the key doesn't validate
against the provider) the banner stays put and the connect modal offers
the OpenRouter flow.

---

## Tier 2 — OpenRouter OAuth *(2 clicks)*

For users who don't have an AI key yet, **OpenRouter is the recommended
path.** One account gets you every model — Claude, GPT, Gemini, open-source
models — and OpenRouter accepts Google / GitHub one-click sign-in.

### Steps

1. From the dashboard, open the connect modal (the auto-detect banner has
   a *No, set up something else* link, or open it from Settings → AI
   provider → Connect AI provider).
2. Click **Connect with OpenRouter**. OpenRouter opens in a new tab.
3. Sign in with Google or GitHub. Authorize Cliff.
4. The OpenRouter tab shows *"You can close this tab."* Switch back to
   Cliff — the modal flips to the success card.
5. Click **Start using Cliff**. You're done.

### Add credits

The success card has an *Add credits at openrouter.ai →* link. Five
dollars buys roughly thirty Cliff workspace runs. You can use free
sponsored models without credits, but performance is uneven; we
recommend adding credits.

### Port 3000 conflicts

Cliff needs port 3000 on your machine for a one-time secure handshake
with OpenRouter. If another app on your machine is using it (most often
a Node dev server) you'll see this card:

> Port 3000 is busy.

Close the other app and click **Try again**, or click **Use my own API
key** to fall through to Tier 3.

### Running Cliff in Docker

The OAuth listener has to be reachable from the host browser. Two
requirements:

1. **Publish port 3000.** `docker run … -p 3000:3000 …`, or uncomment
   the `3000:3000` line in the bundled `docker/docker-compose.yml`
   (left commented by default so BYOK users don't squat the host's
   port 3000).
2. **Bind 0.0.0.0 inside the container.** The official image sets
   `CLIFF_OAUTH_CALLBACK_HOST=0.0.0.0` automatically. If you've built
   a custom image and overridden this var, the listener won't see the
   forwarded traffic and the UI surfaces a *"Port 3000 is busy"* card
   even though nothing else holds it.

On a host (non-Docker) install, leave `CLIFF_OAUTH_CALLBACK_HOST`
unset — it defaults to `127.0.0.1` so the one-shot listener is never
externally reachable. The state-mismatch / CSRF guard runs identically
regardless of bind host, so the wider bind in Docker doesn't weaken
the flow.

---

## Tier 3 — Direct BYOK *(your own key)*

For users with an existing Anthropic, OpenAI, or self-hosted endpoint.

1. In the connect modal, click **I have my own API key →**.
2. Pick a provider. Anthropic is the default.
3. Follow the provider-specific instructions in the modal — there's a
   deep-link button to the right console page.
4. Paste your key. Cliff validates it in the background; you'll see a
   ✓ when it passes.
5. Click **Save**.

### Provider notes

- **Anthropic** — best supported. Get a key at
  [console.anthropic.com](https://console.anthropic.com/settings/keys).
  Keys start with `sk-ant-`.
- **OpenAI** — works but a one-line note in the modal reminds you that
  Cliff is tuned for Claude. Keys at
  [platform.openai.com](https://platform.openai.com/api-keys).
- **Custom (OpenAI-compatible)** — any endpoint that speaks the OpenAI
  `chat/completions` API. You'll need to provide the base URL and the
  model name.

### Common errors

| What you see | What it means |
|---|---|
| *This key was rejected by Anthropic.* | The key isn't valid. Re-check it (Anthropic keys start with `sk-ant-`). |
| *Your account doesn't have access.* | The key is valid but your provider account isn't set up for billing yet. Open the console deep-link in the modal. |
| *Can't reach Anthropic.* | Network issue between your machine and the provider. |

---

## After you're connected

The Settings page shows the active provider and the source it came from:

> Connected via OpenRouter as `you@example.com`

You can:

- **Switch provider** — opens the connect modal again.
- **Disconnect** — clears Cliff's local copy of the key. **Disconnect
  is local-only.** To fully revoke the key from OpenRouter's side, visit
  [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys).
  (We can't revoke the key server-side without OpenRouter's
  `client_secret`, which we don't ship in self-hosted code.)

---

## Model override

Cliff hardcodes the recommended model per provider. If you want to
override, set one of these env vars before launching:

```bash
export CLIFF_AI_MODEL_OVERRIDE_OPENROUTER="anthropic/claude-opus-4-1"
export CLIFF_AI_MODEL_OVERRIDE_ANTHROPIC="claude-opus-4-1"
export CLIFF_AI_MODEL_OVERRIDE_OPENAI="gpt-5"
export CLIFF_AI_MODEL_OVERRIDE_CUSTOM="llama-3.1-70b"
```

Cliff logs a warning at boot when any override is active, and the
Settings card surfaces a *"Custom model: …. Default recommended."*
chip so you can see it from the UI.

We don't expose a UI override — the env-var path keeps model selection
out of the primary flow. Pinned defaults reduce drift across releases.

---

## Where keys live

- All keys are encrypted at rest using `CredentialVault`
  (AES-256-GCM, ADR-0016). The encryption key resolves via
  system keyring → `CLIFF_CREDENTIAL_KEY` env var →
  `<data_dir>/.credential-key`.
- Keys are decrypted only in memory at workspace-spawn time and
  injected into the OpenCode subprocess as `OPENROUTER_API_KEY` /
  `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. They never appear in
  `opencode.json`, in `auth.json`, or in logs.
- Disconnecting removes both the `ai_integration` row and the
  encrypted credential.

---

## Reference

- [ADR-0036 — Tiered AI provider onboarding](../adr/0036-ai-provider-onboarding.md)
- [IMPL-0011 — Tiered AI provider onboarding](../architecture/plans/IMPL-0011-ai-provider-onboarding.md)
- [ADR-0016 — Credential vault](../adr/0016-credential-vault.md)
