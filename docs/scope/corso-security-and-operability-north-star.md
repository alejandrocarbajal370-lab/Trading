# CORSO Security & Operability — Intake, Dashboard, Monitoring

Status: **MIXED — see per-section status below.** This document does not change the Step 6 gate
status, `trade_decision`, `signals_generated` or any other current-truth field owned by the
Investment OS North Star or the roadmap. It governs the periphery (who may act on Intake/Dashboard,
what an operability monitor may show) and proposes future engine-adjacent surfaces; it grants no
new engine, execution, backtesting or portfolio authorization.

## 1. Access control — Data Intake and Dashboard

Status: **IMPLEMENTED** (as of 2026-09-19, `corso-intake` commit `a64cb10`,
`corso-dashboard` commit `ce6f095`). Factual "as-built" state, not a target aspiration.

Both peripheral apps previously had no meaningful authentication posture: Intake had a single
email/password check with no lockout, no 2FA and a 30-day session; the Dashboard was fully public.
Because real capital moves through the economic facts Intake promotes, and because the Dashboard
displays that same portfolio state, both were hardened directly rather than deferred:

**Data Intake** (`corso-intake`, Postgres-backed, single human user):
- Account lockout after 5 failed password attempts (15-minute cooldown), enforced through one
  choke point (`verifyPassword`) shared by the login precheck and the NextAuth `authorize()`
  callback, so it cannot be bypassed by calling either path alone.
- TOTP two-factor authentication (`otpauth` + `qrcode`, no native deps), with a two-step login
  (password, then code) built so the password is never resent to the client for the second step —
  a short-lived, single-use, server-held token bridges the two steps instead.
- Hashed, single-use recovery codes, generated once and shown once.
- Append-only `login_audit_log` (every attempt, success or failure, with result/IP/user-agent).
- Session lifetime cut from the framework's 30-day default to 4 hours (30-minute sliding renewal).
- HTTP security headers: CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, HSTS,
  `Referrer-Policy`, `Permissions-Policy`.

**Dashboard** (`corso-dashboard`, no database — mock/read-only rendering today):
- A shared-password gate enforced in the Edge proxy (`src/proxy.ts`) in front of every route except
  `/login` and static assets.
- No session store: the session is a signed, expiring token (HMAC-SHA256 via Web Crypto, so the
  same verification code runs in both the Edge proxy and the Node login/logout actions), held as an
  HttpOnly cookie, 8-hour lifetime.
- Password compared against a bcrypt hash held only in an environment variable
  (`DASHBOARD_PASSWORD_HASH`), never in source or client code.
- Same CSP/security-header set as Intake.

This closes the most urgent items from the prior security review (missing 2FA, no rate limiting,
indefinite sessions, a fully public dashboard). It does not add encryption at rest, IP allow-listing
or a WAF; those remain open if the threat model changes (e.g. multiple human users, or capital scale
that changes the cost/benefit of additional controls).

## 2. Proposed engine operability monitors (Equity / Fixed Income)

Status: **FUTURE / NOT_IMPLEMENTED / NOT_AUTHORIZED.** Opinion and proposal only.

A "Fixed Income functioning monitor" and "Equity functioning monitor" are a reasonable idea, but
today there is nothing to monitor in the trading-performance sense: `signals_generated=false`,
`trade_decision=NO_TRADE`, and Step 6 remains foundation-only with all 10 gates `OPEN_EXTERNAL`. A
monitor framed around PnL, hit-rate or signal quality would therefore either show empty states
indefinitely or invite exactly the kind of fabricated/interpolated value this program has
repeatedly guarded against.

The recommendation is to scope these as **operability/health monitors**, not performance
dashboards, answering questions such as: did the last scheduled run complete; how many
`validation_manifest.json` checks passed/failed (`monitoring/manifest.py` already produces this
shape); what is the current state of each Step 6 gate; is upstream data (PIT security master,
provider feeds, IBKR read-only observation probe) fresh and reachable; how many securities are
admitted vs excluded and why. This is low-risk (it exposes governance/pipeline state that already
exists as `RunContext`/`ValidationManifest` output, nothing new is computed), useful immediately
(operability matters even in FOUNDATION_ONLY), and consistent with existing product boundaries —
per the Dashboard North Star, Equity and Fixed Income are asset classes, not top-level tabs, so
these views belong inside the existing **Operations** and **Audit** tabs as asset-class-scoped
panels, not as two new top-level "monitor" surfaces.

If and when Equity/FI produce real signals under a closed Step 6, a second, separately authorized
phase can add performance/quality telemetry (e.g. confidence calibration, out-of-sample tracking).
That phase is not requested or authorized by this document.

## 3. Frequency of analysis and model recomposition

Status: **FUTURE / NOT_IMPLEMENTED / NOT_AUTHORIZED.** Opinion and proposal only.

No cadence exists to document today, because there is no live signal generation to schedule. The
honest answer to "how often does the model recompose" is currently "it doesn't — it produces
`NO_TRADE`." A cadence decision made before Step 6 closes would risk becoming a de facto activation
pressure ("we already built the schedule, why not use it"), which this document deliberately avoids
by not proposing a specific number now.

What is safe to record as target direction: **research/shadow-mode runs** (Equity Shadow, per the
Investment OS North Star's development sequence) can run on a fixed schedule today without
implying execution authority, since they produce no `trade_decision` other than `NO_TRADE`/informational
research cases. Any future **live recomposition cadence** is a separate, later, explicitly
authorized decision gated on Step 6 closure, real provider admission and the Portfolio Engine's own
authorization — not something this document, or the Intake/Dashboard security work, should
pre-decide.

## 4. Paper trading data — current finding

Status: **FACTUAL FINDING**, verified against code, not documentation claims.

There is no paper-trading account, order or position data anywhere in this system today for the
Dashboard (or anything else) to read. The only IBKR integration in the codebase
(`governance/ibkr_probe.py`, ADR 0009 and ADR 0011) is an explicitly **read-only, localhost-only
market-data observation probe** — it resolves contracts and reads ticks to gather evidence for
provider-admission decisions; it holds no account, places no orders and stores no position/PnL
state. `PAPER_IBKR` remains, per the Dashboard North Star, a defined-but-unauthorized future
environment: "That target does not authorize paper execution now." Until a separately authorized
phase stands up an actual paper-trading adapter and ledger, "the Dashboard reads paper trading
data" has no data source to point at. The Dashboard's only real economic-fact source remains
Data Intake → the append-only ledger, as already scoped.

## 5. Data-flow architecture — recommendation

Status: **OPINION**, offered against the three-step flow described by the product owner
(1. run QVM/FI, 2. human decision via Intake, 3. Dashboard consumes all of it) and the open question
of whether adding operability monitors should feed the Dashboard, or be independent.

Recommendation: **neither.** Do not chain the Dashboard behind the monitors, and do not build the
monitors as an independent silo with its own copy of the data. Both should be peer, read-only views
over the same **Governed Data Core** the Investment OS North Star already defines (identity / PIT /
provenance / lineage / versions), which already has two write paths and should keep exactly two:

```text
   Equity/FI engine runs                 Human, via Data Intake
   (research/shadow outputs,      +      (real economic facts:
    validation manifests,                 trades, cash movements,
    gate/run state)                       dividends)
                    \                    /
                     Governed Data Core
              (canonical outputs, ledger, run/gate state,
               versioned, provenanced, append-only)
                    /                    |                \
              Dashboard          Operability Monitors    Audit trail
          (Portfolio/Research/    (Operations/Audit       (drill-down,
           Overview panels)        panels, per §2)         lineage)
```

This is the same principle already stated for the Dashboard ("the backend calculates and owns
canonical semantics; the frontend presents them") extended to the monitors: a monitor is another
frontend, not a second backend. Concretely, this means a monitor never becomes a new upstream
dependency the Dashboard reads through — if the model run is unhealthy, both the Dashboard and the
monitor should observe that independently from the same run/gate state, rather than the Dashboard
inferring engine health from what the monitor renders. This is the most efficient shape because it
adds zero new data-synchronization problems: one source of truth, N read views, each showing only
the states (`MISSING`, `NOT_APPLICABLE`, `PARTIAL`, etc.) that source already defines.

## 6. Deployment note

`corso-intake` was hardened, tested end-to-end locally (login, lockout, TOTP setup/verify/disable,
production build) and pushed to `main` (`a64cb10`) for Vercel to redeploy. Two manual steps remain
outside this session's access: applying the same idempotent schema migration to the production
(Neon) database, and setting `DASHBOARD_AUTH_SECRET` / `DASHBOARD_PASSWORD_HASH` in Vercel for
`corso-dashboard` (`ce6f095`, also pushed). Neither app's production deployment was directly
verified from this session for lack of Vercel dashboard/API access.
