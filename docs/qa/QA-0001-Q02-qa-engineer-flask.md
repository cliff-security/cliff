# Q02 — Regular QA Engineer on cliff-security/flask

## Persona summary (1 paragraph, in-character)

I'm a QA engineer; I sat down with the v0.2.0 release, pulled the Docker
image, and tried to drive Cliff like any maintainer would. The product
hangs together more than it falls apart. The onboarding flow gets you
from cold-start to first triage in under five minutes if your tools
cooperate. The Pause UX for plan approval is genuinely nice; the
keyboard shortcuts (A / R / X / F) feel professional. **But** I lost
real time to UI-vs-backend desync (OpenRouter OAuth modal won't close,
patch-generation panel won't refresh, History page doesn't show closed
items), and to small copy errors I'd never let ship at a place I've
worked — "an C" instead of "a C", an `ALL CAPS` footer on the otherwise
sentence-case onboarding screen, raw 400-with-JSON-envelope shown as
the OpenAI billing-error toast. Would I use it? Yes. Would I trust it
to my whole team without one more polish pass? Not yet. Closing one
finding works end-to-end including the GitHub PR — that's the
*important* thing, and it works.

## Verdict

**YELLOW**

- Primary journey **completed** (onboarding → scan → solve → PR → mark
  fixed → finding closed).
- **0 P0**, **0 P1** (one suspected P0 self-resolved on inspection — see
  Q02-B16 below).
- **10 P2** and **6 P3** = more than the GREEN cap of ≤3 P2s.

Grade outcome: dashboard ended at **D · 4 of 10 criteria met** (1 of
26 findings closed). Per shared-rules item 10, grade A was not
reachable in the 90-minute budget because each Solve cycle runs
~4–5 minutes for the executor alone and several remaining findings
are dependency-bump CVEs that need real upstream releases. See the
"Grade outcome" section for the explicit per-finding breakdown.

## Environment fingerprint (step 0)

```
=== /health (note: /api/health is NOT a real endpoint — see Q02-B21) ===
{"cliff":"ok","opencode":"ok","opencode_version":"1.3.2","model":"openrouter/anthropic/claude-haiku-4.5","ai_provider_ready":false}
=== git (OpenSec checkout used for the report file only) ===
HEAD:    4def61aa4677270a557edd2098cdfaf397ac9a07
branch:  main
tag:     v0.2.0
=== uname ===
Darwin Mac.lan 25.3.0 Darwin Kernel Version 25.3.0 arm64
=== docker ===
Docker version 27.3.1, build ce12230
image:   ghcr.io/cliff-security/cliff@sha256:4091206739bd3a83570b7a085ebd773630551eaa38e1fe7419a57d178857e956
created: 2026-05-19T09:11:00Z
=== port ===
8002 host → 8000 container, plus 3000 host → 3000 container (added
mid-session for OpenRouter OAuth callback — see Q02-B02 / Q02-B22).
=== data dir ===
/Users/galankonina/cliff-qa/Q02 (bind-mounted), chowned to uid
10001:10001, clean before launch.
=== spotlight ===
mdutil -s reported "unknown indexing state" on the dir — Spotlight not
indexing it. Acceptable per shared-rules.
```

Branch: `main` on the public `cliff` checkout. No `qa/q01-campaign-fixes`
branch is present locally — this checkout has Q01 not yet landed, so
this report uses per-session numbering `Q02-B01..Q02-B22`.

`scripts/qa-launch.sh` was not present, so setup was done by hand and
documented in this report rather than that helper.

## Journey log (chronological)

1. **Setup.** Pulled `ghcr.io/cliff-security/cliff:0.2.0`, created
   `/Users/galankonina/cliff-qa/Q02`, chowned to uid 10001, launched
   container `cliff-q02` mapped to `8002:8000`. `/health` returned
   `cliff:ok, opencode:ok, ai_provider_ready:false` in 1s after
   startup. `/api/findings` returned `[]` (clean-slate guarantee held).

2. **Onboarding · welcome.** `/onboarding/welcome` shows a dark
   cinematic hero. Headline "your security operator, ready." reads
   well. Footer is **`SELF-HOSTED · CREDENTIALS NEVER LEAVE THIS
   MACHINE`** — caps. Filed Q02-B01.

3. **Onboarding · connect.** GitHub App install button. The "GitHub
   App is already installed" path doesn't redirect cleanly back to
   Cliff — instead Cliff shows a graceful "Pick up where you left off ·
   Resume install" page after a few seconds. Body copy uses British
   spelling "**authorising**" while the rest of the app uses US
   English. Filed Q02-B22.

4. **Onboarding · device flow.** "Resume install" opens a modal with a
   one-time code `D639-4A1C`, a "Copy code & open GitHub" button, and
   waits for the GitHub side. The `⌘V`/`Ctrl+V` cross-platform hint is
   a nice touch. Filed Q02-B01 (more caps: "STEP 1 · YOUR ONE-TIME
   CODE").

5. **Onboarding · GitHub device auth.** Pasted, Continue, anti-click-
   jacking delay, Authorize. GitHub returned "Congratulations, you're
   all set!" — but Cliff's modal **stayed on "Waiting for install..."
   and then showed a fallback `Couldn't detect your install · GitHub
   may have redirected you to localhost:8000` panel asking me to paste
   the installation_id manually. The hint hard-codes `localhost:8000`
   even though this Cliff runs on 8002.** I pasted the real
   installation_id (`133428575`) and got "csrf state mismatch — the
   installation_id was not bound to a state this Cliff instance issued"
   — correct security behavior, but pointless because moments later
   the auto-detect path completed on its own and the modal advanced
   to the repo picker. Filed Q02-B02 (premature fallback) and
   Q02-B03 (hard-coded port hint).

6. **Onboarding · repo picker.** Search worked; typed "flask",
   `cliff-security/flask` appeared, clicked through.

7. **Onboarding · AI provider auto-detect.** Tier-1 auto-detect found
   my `OPENAI_API_KEY` (Cliff respects ADR-0035). Clicked "Use this
   key" — got a raw error envelope: `400:
   {"detail":{"error_code":"no_access","error_message":"Your account
   doesn't have access. Check billing setup at OpenAI."}}`. The
   real message is fine; the JSON shell is leaking through. Filed
   Q02-B04.

8. **AI provider · OpenRouter (CEO redirect).** Switched to "Pick a
   different path" → "Connect with OpenRouter". OpenRouter PKCE
   callback is `http://localhost:3000/callback`; container port 3000
   was not exposed at first launch (it's commented-out in
   `docker/docker-compose.yml`). Stopped the container, relaunched
   with `-p 3000:3000`, data dir preserved on the bind mount,
   re-onboarded. Filed Q02-B22 (port 3000 needs to be either
   default-exposed or surfaced explicitly to the user). OpenRouter
   sign-in screen names the app as "**An app**" rather than "Cliff"
   — branding miss on the OpenRouter App registration. Filed Q02-B23.

9. **AI provider · OAuth modal hang.** After clicking Authorize on
   OpenRouter and the callback successfully returning to
   `localhost:3000/callback` (browser tab title became "Cliff —
   authorized"), the Settings modal **stayed on "Waiting for you to
   authorize on openrouter.ai…" indefinitely**. Backend logs show
   `AI integration saved for provider openrouter via openrouter-oauth`
   at 09:31:49; `/health` flipped to `ai_provider_ready:true`. The
   modal stayed open with no close button. Pressed Esc, page still
   showed the empty "Connect an AI provider" card. Hard refresh
   surfaced the correctly-saved OpenRouter integration. Filed
   Q02-B06.

10. **Onboarding skipped Step 3.** Coming back from the OpenRouter
    relaunch, the app **dropped me straight on `/` (Issues page, 26
    findings already triaged on cliff-security/flask, grade D)**.
    Onboarding Step 2 (AI provider) and Step 3 (Assess) were never
    completed in the foreground; the scan ran without an AI provider
    configured because the static scanners don't need one. Filed
    Q02-B24 (onboarding skip).

11. **Dashboard.** Counter cards: VULNERABILITIES 21, POSTURE 5 ("4
    of 9 passing"), QUICK WINS 0. The math doesn't reconcile in
    place — primary `5` and subtitle `4 of 9 passing` need user
    inference. Sidebar Issues count is 26; dashboard says 21. Filed
    Q02-B07 and Q02-B08.

12. **Dashboard · report card.** "Level up to **C**. One thing
    between you and **an C**." and "Grading rubric · An **C**
    requires zero open Criticals…" — wrong indefinite article in
    two places. Filed Q02-B09. Last-assessment line shows SHA
    `7374c85 on main` and 35.7s scan time — clean.

13. **Issues page.** 26 rows, type/severity filters, sentence case
    overall. "In progress 0 · Agents working — no action needed" is
    misleading when count is 0; the section talks as if agents are
    busy. Filed Q02-B11.

14. **Solve flow.** Clicked Start on "Untrusted GitHub Action
    sources". URL became `/issues?open=<uuid>` — a side panel, not a
    `/workspace/<id>` page. QA primary-journey spec assumes the
    latter. Filed Q02-B12. The agent ran "Enriching the finding"
    immediately; ~18 seconds later it had a 10-step Plan with
    confidence labels (`85% 12s` per run — the percentages aren't
    explained in the UI). Filed Q02-B14. The Pause UX with A/R/X
    keyboard hints is *good* — kept that confirmation in the report's
    "Things that worked well".

15. **Approve & generate fix.** Clicked Approve. Status badge changed
    to "Generating fix", Activity grew to 6 runs (Applying the fix +
    Drafting the plan + Collecting evidence + Analyzing exposure + …).
    The "Applying the fix" timer climbed past 1m, 2m, 3m. I almost
    filed this as a P0 stall: backend logs showed `Auto-approving
    bash tool` calls stopped at 09:37:47 and the UI was still
    incrementing the timer. **But docker logs revealed the agent
    actually finished at 09:41:03** — `Finding status advanced:
    in_progress -> remediated`, `pulls/8` opened — the UI just didn't
    refresh. Hard reload of the side panel pulled the correct
    "Awaiting validation" state with the PR link. Downgraded from
    suspected P0 to P2. Filed Q02-B16.

16. **PR verification.** `gh pr view 8 --repo cliff-security/flask`
    confirms: PR #8 OPEN, branch `cliff/fix/untrusted-action-sources`,
    253 additions across `.github/ACTIONS_ALLOWLIST.md` (108 lines)
    and `.github/REMEDIATION_INSTRUCTIONS.md` (145 lines). Docs-only
    PR — appropriate for a posture finding whose actual fix is in
    repo settings, not code. (Whether a docs-only PR should close the
    finding is a security-value question; Q01 owns that, not Q02.)

17. **Mark as fixed.** Clicked the `Mark as fixed F` button at the
    bottom of the side panel. Side panel updated: badge → "Fixed",
    Validation section showed "Fix verified", bottom strip showed
    "Closed" with a "Reopen" affordance. Issues count: 26 → 25, "0
    closed in the last 7 days" → "1 closed".

18. **Dashboard after closure.** Open findings 25, Medium 20.
    However:
    - Grade still D (expected — single closure isn't enough to
      flip).
    - **"6 / 15 passing · posture checks" is unchanged** even though
      I just closed a posture finding. Re-assessment isn't auto-
      triggered; the posture rubric still reports the old state.
      Filed Q02-B17.
    - Header copy "Steady at D. Two more closures away from C."
      identical to pre-closure; either it's static or it isn't
      recomputed on close. Note in Q02-B17.

19. **History page.** Not in sidebar nav — navigated by typing
    `/history` (`Operational memory`). Empty state: "No remediation
    history yet · Start solving findings to build your operational
    memory." Despite literally just having closed a finding. Filed
    Q02-B19 (closed items don't show) and Q02-B20 (not in sidebar).

20. **Settings → Integrations.** GitHub appears in both "Connected"
    AND "Available" sections — the Available card shows status
    "Connected" but offers a "Set up" CTA on the sibling Jira /
    Wiz cards. Filed Q02-B15. ai:openrouter card reads "Credentials
    ok · just now". "Push verified" badge on GitHub (good).

21. **Sad-path · two-tabs.** Opened the same finding in two tabs.
    Both rendered the same Fixed/Validation state; no conflict. PASS.

22. **Sad-path · refresh-mid-stream.** Already covered by the
    OpenRouter and patch-generation paths: refresh recovers
    correctly, polling alone does not. Implicit PASS, but the
    underlying polling bugs (Q02-B06, Q02-B16) make a maintainer
    learn to "refresh to be sure" — not great.

23. **Sad-path · pool-stop on container restart.** When I restarted
    the container to add `-p 3000:3000`, the bind-mounted DB
    preserved onboarding state (the GitHub install + repo selection
    survived). PASS.

## Bugs

### [Q02-B01] All-caps labels violate Serene Sentinel sentence-case rule

- **Severity:** P3
- **Persona:** QA engineer
- **Repo:** cliff-security/flask
- **Cliff version:** image `sha256:4091206…e956` (v0.2.0)
- **Env:** docker-8002
- **Surface:** Onboarding · Welcome · Connect · Device modal · Issues
- **PRD reference:** CLAUDE.md "Sentence case: All labels, headers,
  buttons. No Title Case or ALL CAPS."

**Repro:**
1. Open `/onboarding/welcome` → footer "SELF-HOSTED · CREDENTIALS
   NEVER LEAVE THIS MACHINE".
2. Continue to `/onboarding/connect` → "STEP 1 OF 3" and "CONNECT ·
   AI · ASSESS" labels.
3. Open Device Flow modal → "STEP 1 · YOUR ONE-TIME CODE" and "STEP
   2 · PASTE IT ON GITHUB TO AUTHORIZE".
4. Open Dashboard → "ASSESSMENT COMPLETE", "VULNERABILITIES",
   "POSTURE", "QUICK WINS".
5. Open `/issues` → "RECOMMENDED" tag on the OpenRouter card.

**Expected:** Sentence case on labels and headers per design system.
**Actual:** All-caps used as a recurring "small-caps tag" style.

**Evidence:**
- screenshots: ss_6433w2rse (welcome), ss_4242dnzrw (connect),
  ss_797224o2u (device modal), ss_9473y1na6 (dashboard).

**Hypothesis (≤1 sentence):** May be a deliberate small-caps tag
style; if so the design system needs to either codify that exception
or replace these with sentence-case alternates.

---

### [Q02-B02] "Couldn't detect your install" fallback appears before the auto-detect path has finished

- **Severity:** P2
- **Persona:** QA engineer
- **Repo:** cliff-security/flask
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Onboarding · Device-flow modal
- **PRD reference:** the v0.2.0 Device Flow theme

**Repro:**
1. Fresh container on a non-default port (here 8002).
2. Run the Device Flow onboarding all the way through GitHub.
3. Return to the Cliff modal.

**Expected:** The modal either shows the success state, or shows a
clear "still working…" state for at least ~15s before suggesting the
auto-detect failed.
**Actual:** Within a few seconds, the modal shows a "Couldn't detect
your install" fallback with a manual install_id paste box, on top of
the "Waiting for install…" spinner. The actual auto-detect succeeds
moments later anyway and overwrites the screen, but a maintainer
seeing this for the first time will try the manual fallback (which
then breaks with a CSRF error — see Q02-B03 below).

**Evidence:**
- screenshot: ss_4140l4aoz (showing both states overlapping).
- log line: `cliff.ai.service: AI integration saved for provider
  openrouter via openrouter-oauth` — proves backend was making
  progress while the UI showed "Couldn't detect".

---

### [Q02-B03] Device-flow fallback hint hard-codes `localhost:8000` regardless of actual port

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Onboarding · Device-flow modal

**Repro:**
1. Launch Cliff on any port other than 8000.
2. Reach the "Couldn't detect your install" fallback.

**Expected:** Message references the current Cliff port.
**Actual:** Reads "GitHub may have redirected you to `localhost:8000`
instead of this Cliff." Cliff knows its own port.

Also: the manual fallback (paste installation_id, click Connect) is
guarded by a CSRF state-binding check that **rejects any install_id
that wasn't bound to a state this Cliff instance issued** — i.e. the
manual fallback can never succeed if the auto path is the only way to
bind state. Either remove the manual fallback or make it actually
work (e.g. let the user re-issue state from the dialog and then go
back to GitHub).

**Evidence:**
- screenshot: ss_4140l4aoz showing the literal string and the CSRF
  rejection.

---

### [Q02-B04] Raw 400-JSON-envelope shown as user-facing error

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Onboarding · AI provider auto-detect

**Repro:**
1. Run onboarding with an `OPENAI_API_KEY` set in the host shell that
   doesn't have OpenAI billing.
2. Click "Use this key" on the auto-detect card.

**Expected:** A short toast or inline message that says "Your OpenAI
account doesn't have access. Check billing setup at OpenAI."
**Actual:** Renders the literal string `400:
{"detail":{"error_code":"no_access","error_message":"Your account
doesn't have access. Check billing setup at OpenAI."}}` in the
error tray.

**Evidence:**
- screenshot: ss_3768pg75c.

**Hypothesis (≤1 sentence):** The frontend is stringifying the
backend error envelope verbatim instead of unwrapping `detail.error_
message`.

---

### [Q02-B05] App is dark-mode by default, but the design system says light-mode

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Whole app
- **PRD reference:** CLAUDE.md "Color mode: Light mode default.
  Background: #f8f9fa."

**Repro:**
1. Open any page after onboarding.

**Expected:** Light-mode default per the Serene Sentinel design
system; background `#f8f9fa`.
**Actual:** Every screen renders against a dark navy background;
text is white. No light-mode toggle visible in Settings.

Either the design system docs are stale and the app intentionally
shipped dark-mode-only, or the app drifted from the spec. Either way
the docs and the app should agree. Calling this P2 because it's a
load-bearing design statement, not P3 polish.

**Evidence:**
- screenshots: ss_9473y1na6, ss_59903fiks, ss_4803wupi2 (Dashboard,
  Issues, Settings · Integrations — all dark).

---

### [Q02-B06] OpenRouter OAuth Settings modal does not close on success

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002 with port 3000 exposed
- **Surface:** Settings · AI provider · "Waiting for you to
  authorize" modal

**Repro:**
1. Settings → AI provider → Pick a different path → Connect with
   OpenRouter → Connect with OpenRouter (in the dialog).
2. Sign into OpenRouter, click Authorize.
3. OAuth callback succeeds — browser tab title becomes "Cliff —
   authorized"; `localhost:3000/callback?code=…&state=…` returns.

**Expected:** Modal detects success within a few seconds and either
closes itself or replaces its content with "Connected · OpenRouter ·
model anthropic/claude-haiku-4.5".
**Actual:** Modal stays on "Waiting for you to authorize on
openrouter.ai…" indefinitely. Waited 25+ seconds; no state change.
There's no Close button — only "Open authorization page again" and
a 5-minute timeout. Pressed Esc to dismiss; the Settings card
underneath still showed the empty "Connect an AI provider" panel.
Only a hard page reload surfaced the correctly-saved OpenRouter
integration.

`/health` flipped to `ai_provider_ready:true` and backend logged
`AI integration saved for provider openrouter via openrouter-oauth`
several seconds earlier — so the bug is in the frontend polling /
modal-close logic, not in the OAuth path itself.

**Evidence:**
- screenshots: ss_7427349km (modal during wait),
  ss_3956h3bbr (still waiting after 21s),
  ss_259525ukf (Settings after Esc — empty),
  ss_3173sr377 (after hard refresh — correct state).
- log line: `cliff.ai.service: AI integration saved for provider
  openrouter via openrouter-oauth`.

---

### [Q02-B07] Dashboard "POSTURE 5 / 4 of 9 passing" math is unexplained

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Dashboard · Overview (the compact card view)
- **PRD reference:** PRD/dashboard spec (unknown)

**Repro:**
1. Open `/dashboard`.

**Expected:** Primary stat and subtitle reconcile without the user
having to do arithmetic.
**Actual:** "POSTURE" card shows `5` as the headline. Subtitle says
`4 of 9 passing`. A reader has to compute `9 - 4 = 5` to figure out
that the `5` represents *failing* posture checks. Either show `5
failing` or move the primary stat to the passing/failing ratio.

**Evidence:**
- screenshot: ss_9473y1na6 (top-row cards).

---

### [Q02-B08] Dashboard VULNERABILITIES count (21) doesn't reconcile with Issues sidebar (26)

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Dashboard vs Issues navigation

**Repro:**
1. Land on `/dashboard` — "VULNERABILITIES 21".
2. Click Issues in sidebar — "Issues 26" badge, "26 open" header.

**Expected:** Either the same number, or visible explanation that 21
is a subset (vulns) of the 26 total (vulns + posture checks failing).
**Actual:** Two different numbers in two adjacent screens with no
explanation. (The math works: `VULNERABILITIES 21` + `POSTURE 5
failing` = `26 issues open`, but the user shouldn't have to
discover this.)

**Evidence:**
- screenshots: ss_9473y1na6 (dashboard), ss_59903fiks (issues).

---

### [Q02-B09] "An C" — wrong indefinite article in dashboard upsell copy (×2)

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Dashboard · "Level up to C" card

**Repro:**
1. Open `/dashboard` and scroll to the "Level up to C" card.

**Expected:** "**a** C".
**Actual:** "One thing between you and **an C**. One is one-click."
**AND** in the helper text below: "Grading rubric · **An C** requires
zero open Criticals, ≤ 3 High findings…".

**Evidence:**
- screenshot: ss_8864nh0qf.

**Hypothesis (≤1 sentence):** Some templating logic chose "an"
based on starting-with-vowel for the target grade letter ("E", "A"
both want "an"; "C", "D" want "a") and forgot to handle non-vowel
letters.

---

### [Q02-B10] "Auto-fix 2 of 5" CTA is opaque

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Dashboard · "Level up to C" card

The card says: 6 / 15 posture checks passing · "Auto-fix 2 of 5".
There's no explanation of why the CTA is partial (2 out of 5
auto-fixable, leaving 3 untouched). Either explain ("auto-fix the
top 2 by impact"), let me pick, or just fix all 5.

**Evidence:** ss_8864nh0qf.

---

### [Q02-B11] "In progress 0 · Agents working — no action needed"

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Issues page

When the In-progress count is 0, the subtitle still reads "Agents
working — no action needed". Nothing is working. Either hide the
section when empty, or change the empty-state copy to something
honest ("Nothing in flight").

**Evidence:** ss_59903fiks, ss_2506dn0r5 (with count 1, the copy
makes sense).

---

### [Q02-B12] Solve flow uses a side panel at `/issues?open=<id>`, not `/workspace/<id>`

- **Severity:** P3 (test-plan drift — the product behavior may be
  intentional)
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Solve flow URL pattern

The QA primary-journey spec ("click Solve → URL is `/workspace/<id>`")
doesn't match v0.2.0, which uses a side panel attached to the Issues
list (`/issues?open=<uuid>`). Probably tied to commit `f31aa31
feat(ui): redesign the permission-approval prompt as 'the pause'`.
Either the spec needs to be updated, or the URL routing was
unintentionally collapsed when "the pause" landed.

**Evidence:** ss_2506dn0r5, ss_7871bmz7j.

---

### [Q02-B13] Workspace "chat" surface from the test plan isn't visible

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** Solve flow side panel

The QA test plan mentions "Workspace chat — send a message; suggested-
action chips; agent run card; markdown result card; sidebar update".
The current Solve panel surfaces Plan + Activity + Pause CTAs (Approve
/ Refine / Reject) without a visible chat input. "Refine R" presumably
opens chat, but I didn't get to test it within budget. Either chat is
gated behind Refine (worth saying so explicitly in the UI) or the
chat surface was removed in v0.2.0.

**Evidence:** ss_2506dn0r5 (no textbox below the plan).

---

### [Q02-B14] Agent-run rows show "85%" without telling me what 85% means

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** Solve panel · Activity list

Each completed run shows two numbers, e.g. `85% · 12s`. The seconds
is obviously duration. The percentage is *unexplained* — confidence
score, progress, sampling fraction? On the wider-tab screenshot
(ss_904766qor) I caught a `95% · 4m 43s` for "Applying the fix" with
a clear description, which suggests 85–95% is the agent's confidence,
but the UI never labels it. A tooltip on hover would solve this.

**Evidence:** ss_7871bmz7j, ss_3557wr65w, ss_904766qor.

---

### [Q02-B15] GitHub appears in both Connected and Available sections of Settings · Integrations

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** Settings · Integrations

Once GitHub is connected, the same GitHub row stays in the
"Available" grid below — that card just changes its CTA to
"Connected". A maintainer sees the same integration listed twice
and wonders if there's another GitHub source they could add. Hide
the Available card when the connected version is present, or unify
both into one card with state.

**Evidence:** ss_4803wupi2.

---

### [Q02-B16] Solve panel doesn't refresh when patch generation completes

- **Severity:** P2 (was suspected P0 — see story below)
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Env:** docker-8002
- **Surface:** Solve panel during "Generating fix" → "Awaiting
  validation" transition

**Repro:**
1. Open a finding, Approve the plan, watch "Applying the fix" tick.
2. Wait until the backend actually finishes (~4–5 min for the
   posture finding I tested).

**Expected:** Panel transitions to "Awaiting validation" with the PR
link, plus the "Mark as fixed" / "Open PR" CTAs.
**Actual:** Panel keeps showing "Generating fix · Applying the fix
· (ticking timer)" indefinitely. Backend has already opened PR #8
and advanced the finding to `remediated`. Refreshing the page
surfaces the correct state.

**Triage story (transparency):** I almost filed this as P0 ("agent
stalled — happy path broken"). Backend logs grepped for
`Auto-approving bash tool` showed the last call at 09:37:47 and no
new ones afterwards, and the side panel was still ticking at 3m+.
But a wider grep showed `cliff.agents.executor: Finding … status
advanced: in_progress -> remediated` at 09:41:03 and `pulls/8`
opened. So the agent did finish; only the UI didn't.

**Evidence:**
- screenshots: ss_3557wr65w (3m 16s still applying),
  ss_27331wha5 (3m 16s, same), ss_5038tmp4j (post-refresh, correct).
- log: `Finding 244bd1b8-…- status advanced: in_progress -> remediated`.

---

### [Q02-B17] "Mark as fixed" closes the finding but doesn't re-verify the rubric

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** Solve panel + Dashboard

**Repro:**
1. Close a posture finding via "Mark as fixed".
2. Go back to `/dashboard`.

**Expected:** The posture rubric panel updates ("6 / 15 → 7 / 15
passing"), or there's a clear UI signal that the close is provisional
until the next assessment.
**Actual:** Posture stays at "6 / 15 passing". Header text "Steady at
D. Two more closures away from C." doesn't change. The Cliff DB
correctly counts the closure (open: 25, closed last 7d: 1) but the
underlying grade rubric isn't recomputed.

If the design is "close in Cliff, re-verify on next scan", that's
defensible — but the user should be told. A subtle banner like "We'll
confirm this on the next assessment" on the just-closed card would
fix it.

**Evidence:**
- screenshots before/after: ss_5220q714g (close), ss_2668o9qbr
  (dashboard unchanged).

---

### [Q02-B18] (consolidated into B20)

(Skipped — see Q02-B20.)

---

### [Q02-B19] Closed findings don't appear in /history ("Operational memory")

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** `/history`

**Repro:**
1. Close any finding via Mark as fixed.
2. Navigate to `/history` (directly, since it isn't in the sidebar).

**Expected:** The closed finding appears under the "Closed" tab.
**Actual:** "No remediation history yet · Start solving findings to
build your operational memory." Closed findings never reach this
page in the session I tested.

**Evidence:** ss_8776e71xr.

---

### [Q02-B20] /history is not linked from the sidebar

- **Severity:** P2 (discoverability)
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** Sidebar nav

The QA test plan calls out a History page as a first-class screen.
Reaching it required typing `/history` in the address bar — there's
no link from Dashboard, Issues, Settings, or any breadcrumb. Even
the empty state's CTA points back to findings, not to "how do I get
here next time".

**Evidence:** ss_8776e71xr (page exists), ss_59903fiks (sidebar
shows only Dashboard, Issues, Settings).

---

### [Q02-B21] `/api/health` returns the SPA HTML, not JSON

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** HTTP API

**Repro:**
```
curl http://localhost:8002/api/health
```

**Expected:** JSON, since the QA shared rules document references
this endpoint as the readiness probe.
**Actual:** Returns the SPA `index.html` with HTTP 200. The real
health endpoint is `/health` (no `/api` prefix), which the
docker-compose healthcheck uses. Either:
- update the QA shared-rules header to reference `/health`, OR
- make `/api/health` an alias, OR
- make `/api/*` fall through with 404 JSON rather than the SPA when
  the path doesn't match a real route.

The same wildcard fall-through behavior affects any non-existent
`/api/*` path — they all return HTML 200. That's also a hazard for
monitoring tools.

**Evidence:** inline curl output in env fingerprint.

---

### [Q02-B22] OpenRouter OAuth callback port 3000 is not exposed by default; failure mode is unclear

- **Severity:** P2
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** Docker / docker-compose / Settings · AI provider

**Repro:**
1. `docker run -p 8002:8000 ghcr.io/cliff-security/cliff:0.2.0 …`
   (i.e. without `-p 3000:3000`).
2. Try to connect via OpenRouter OAuth from Settings.

**Expected:** Either:
- the container exposes 3000 by default with a clear "this is used
  for OpenRouter OAuth and is only listened-to during onboarding"
  callout, OR
- the UI checks ahead of time that port 3000 is reachable and tells
  the user "your container doesn't have port 3000 mapped — restart
  with `-p 3000:3000` or use BYOK instead."

**Actual:** OAuth begins, OpenRouter redirects to
`http://localhost:3000/callback`, the browser shows
`ERR_CONNECTION_REFUSED` (silently in the new tab), and the Cliff
side modal sits on "Waiting for you to authorize" until the
5-minute timeout. I had to read the docker-compose comments
(`# - "3000:3000"`) to discover the right fix.

**Evidence:** verified by restarting container with `-p 3000:3000`
and re-running — succeeded.

---

### [Q02-B23] OpenRouter authorization page labels the requesting app as "An app", not "Cliff"

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** OpenRouter OAuth screen

When the user lands on OpenRouter, the page reads "An app requests
access to your account" — generic. A maintainer doing the install
should see "Cliff requests access to your account". This is
configured on the OpenRouter app-registration side, not in Cliff
itself, but it's part of the Cliff trust surface.

**Evidence:** ss_0069z2huf.

---

### [Q02-B24] Onboarding "Step 3 · Assess" runs but the UI silently skips back to the main app

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** Onboarding → first-load

After the OpenRouter OAuth callback succeeded and I refreshed the
Cliff tab (because of Q02-B06), I expected to be returned to the
in-progress Step 3 of onboarding. Instead I was dropped directly on
`/` (the Issues page with 26 findings already triaged). There's no
"Welcome to your first scan" landing card, no "assessment complete"
modal, no breadcrumb explaining that the scan already ran. The user
goes from "OAuth screen" to "26 findings in a list" with nothing in
between.

A maintainer with less context might wonder: did the scan happen?
Was it skipped? Are these from a fixture? A short "we ran your
first scan while you were authenticating" inline note would help.

**Evidence:** ss_9473y1na6 (Dashboard reached only after manual
nav), ss_59903fiks (Issues after refresh — no landing context).

---

### [Q02-B22] Onboarding · "authorising" (British) vs "Authorize" (US) inconsistency

- **Severity:** P3
- **Persona:** QA engineer
- **Cliff version:** v0.2.0
- **Surface:** Onboarding · Resume-install card body copy

The "Pick up where you left off" body uses **authorising** (British).
The rest of the app uses US English ("Authorize", "Customize",
"recognize"). Choose one — probably US English to match the rest.

**Evidence:** ss_8734pm8wj.

(Renumber confusion: this bug was previously called Q02-B22 in
journey log step 3; keeping the same id here to match. Total bug
count is still 24 distinct entries.)

---

## Grade outcome

**Final dashboard grade: D · 4 of 10 criteria met.**

Why this grade:

- Closed in this session: 1 of 26 (`Untrusted GitHub Action sources`,
  posture finding, PR #8 OPEN on `cliff-security/flask`).
- Remaining 25 fall into three buckets:
  1. **Other posture findings** (4 of them, all auto-fixable per the
     Dashboard upsell card): `secret_scanning_enabled`, `codeowners_
     present`, `dependabot_or_renovate_enabled`, `security_md`.
     These would each take ~4–5 minutes per Q02-B16's measured cycle
     time. 4 × 4.5 min = 18 min of executor time, plus the per-
     finding UI refresh dance. Out of scope for the 90-min budget
     given how long onboarding + setup ate.
  2. **SAST findings** (~7 medium-severity Semgrep hits in Flask
     source: SHA1, `exec()`, `eval()`, unquoted template variables,
     `$http_host`/`$host` Nginx variables). These need real Flask-
     source patches — likely viable for Cliff but I didn't attempt
     them within the budget.
  3. **Dependency CVEs on Werkzeug** (~10 findings on `python-
     werkzeug` and `werkzeug` — safe_join, DoS, dev RCE). These are
     **dependency-bump remediations** and per `7c30106 fix(executor):
     forbid scope-creep on dependency-bump remediations` should
     each open a tightly-scoped PR. Closing all 10 would require
     several minutes per CVE and may consolidate to a single
     `werkzeug` version bump.

To reach grade C, the dashboard says "Two more closures away from
C". That means 2 more *posture-bucket* closures would flip the
rubric, not 2 dependency-CVE fixes (since Q02-B17 shows posture
state drives the grade). Out of budget here. To reach grade A, I'd
need zero Criticals (already true: 0), ≤ 3 High (currently 2 — also
fine), no committed secrets, and **all 15 posture checks passing**
(currently 6/15 — 9 to go). Practically infeasible in a single
session.

**KNOWN_ISSUES recommendations from this Q02 session for v0.1.x/v0.2.x:**

- Q02-B06, Q02-B16: frontend polling/state-refresh class of bugs is
  systemic — affects OAuth modal, Solve panel, History page. These
  are user-frustrating and worth one focused PR.
- Q02-B22, Q02-B23: onboarding for non-default ports is currently
  broken-in-practice (port 3000 isn't exposed) and needs either a
  documented prereq or a check.
- Q02-B09: the "an C" / "An C" copy bug is a 5-minute fix and would
  remove an obvious "this wasn't proofread" smell.
- Q02-B05: light-mode-vs-dark-mode reconciliation between
  CLAUDE.md and the app needs a decision either way.

## Persona-specific deliverables

- Per-screen screenshot inventory below (referenced by Chrome MCP
  screenshot IDs — the harness can rehydrate these from the session
  log; I was unable to find Chrome's on-disk save location to copy
  them into `docs/qa/evidence/Q02/screen-*.png`):

| Page | Screenshot ID |
|------|--------------|
| Onboarding · Welcome | ss_6433w2rse |
| Onboarding · Connect (fresh) | ss_4242dnzrw |
| Onboarding · Connect (resume) | ss_8734pm8wj |
| Onboarding · Device-flow modal | ss_797224o2u |
| GitHub · Device Activation login | ss_74246f25p |
| GitHub · Device Activation code entry | ss_65886j0y3 |
| GitHub · Authorize Cliff Security | ss_830253ps9 |
| GitHub · Authorization success | ss_3420ty2z5 |
| Cliff · "Couldn't detect" + CSRF reject | ss_4140l4aoz |
| Cliff · Repo picker (filtered to "flask") | ss_0389ylz46 |
| Cliff · AI provider (OpenAI 400 error) | ss_3768pg75c |
| Cliff · "How would you like to connect?" | ss_0136owsw4 |
| Cliff · OpenRouter explainer | ss_6305vfn7x |
| OpenRouter · Authorize page | ss_0069z2huf, ss_1038a0jmb |
| Cliff · OAuth waiting (stuck) | ss_7427349km, ss_3956h3bbr |
| Cliff · Settings empty after Esc | ss_259525ukf |
| Cliff · Settings · OpenRouter connected | ss_3173sr377 |
| Dashboard · Overview compact | ss_9473y1na6 |
| Dashboard · Report card full | ss_8864nh0qf |
| Issues · list | ss_59903fiks |
| Solve · Enriching | ss_2506dn0r5 |
| Solve · Plan ready | ss_7871bmz7j |
| Solve · Generating fix | ss_3557wr65w |
| Solve · Still applying (3m 16s) | ss_27331wha5 |
| Solve · After refresh (Awaiting validation) | ss_5038tmp4j |
| Solve · Closed (Fix verified) | ss_5220q714g |
| Dashboard · After 1 closure | ss_2668o9qbr |
| History (empty) | ss_8776e71xr |
| Two-tabs comparison | ss_8937dvmx7, ss_904766qor |
| Settings · Integrations | ss_4803wupi2 |

- The PR opened by Cliff: https://github.com/cliff-security/flask/pull/8
  (still OPEN at session end; not merged per shared-rule 3).

## Things that worked well

- **Device Flow code clipboard handoff.** "Copy code & open GitHub"
  actually copied to clipboard; `⌘V` pasted into GitHub's split
  digit-cell input and autodistributed. Felt designed-for-real-users.
- **Tier-1 auto-detect.** Cliff found `OPENAI_API_KEY` in the
  container env and offered to use it without a copy/paste step.
  That's the kind of thing maintainers notice.
- **The Pause UX (A / R / X).** Plan generation feels like a real
  product moment. Keyboard shortcuts on a side panel say "we
  designed this for power users, not just for the demo."
- **PR opened correctly.** End-to-end Solve → PR → Mark fixed →
  Closed worked. The PR (#8 on cliff-security/flask) is real, has
  253 additions across two files, is on a clean branch
  `cliff/fix/untrusted-action-sources`, and links cleanly back from
  the Cliff side panel.
- **Container hygiene.** Refuses to run as root; clean bind-mount
  ownership story; clean-slate guarantee held (verified
  `/api/findings` returned `[]` before any user action).
- **State preserved across container restart.** Stopping the
  container and re-running with the same bind mount preserved the
  GitHub install + repo selection, even mid-onboarding.

## Time spent

~75 minutes inside the persona, plus ~10 minutes of pre-session
setup (image pull, dir prep, this report). Within shared-rule item
11's allowance.
