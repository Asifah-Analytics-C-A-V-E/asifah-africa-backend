# asifah-africa-backend

**Africa theatre backend for [Asifah Analytics](https://asifahanalytics.com)**

Open-source monitoring of geopolitical pressure, conflict escalation and
humanitarian stress across the Africa theatre. Sister backends cover the Middle
East & North Africa, Europe, Asia & the Pacific, and the Western Hemisphere.

> **What this is.** A one-person project, built on nights and weekends, running
> on free tiers and stubbornness. No affiliation with or endorsement by any
> government or organisation. If it has been useful to you,
> ☕ [a coffee](https://buymeacoffee.com/asifahanalytics) pays for the hosting
> that keeps it up.

> 🚨 **Not for operational use.** Analytical and research purposes only. See
> [`LICENSE`](./LICENSE).

---

## 🌍 Coverage

**What is actually running.** Everything else on this page is a build queue, not
a claim of coverage — a country without a tracker is absent from the Africa read,
not assessed as quiet.

| Country | Rhetoric tracker | Interpreter | Humanitarian | Notes |
|---|---|---|---|---|
| 🇸🇴 Somalia | ✅ | ✅ | ✅ | Junction tracker — reads four external wheels (Turkey, Russia, Bab-el-Mandeb, Israel–Somaliland) |
| 🇸🇩 Sudan | ✅ | ✅ | ✅ | Hub tracker — RSF/SAF, UAE and Russia plugs; multi-hub trajectory |
| 🇲🇱 Mali | ✅ | ✅ | ✅ | Russia spoke — carries the gaining/losing **trajectory** read |
| 🇳🇬 Nigeria | — | — | — | Stability module only (`nigeria_stability.py`, NGX market pulse) |

Three rhetoric trackers feed `africa_regional_bluf.py`, which rolls them into a
single regional posture and emits the signal pool the Global Pressure Index
consumes. The BLUF reports its own coverage honestly: with one tracker live it
says so rather than presenting a country read as a continental synthesis.

### Build queue

Country selection and the analytical drivers below were set in **May 2026** and
have not been re-reviewed since. Treat the drivers as the reason a country
entered the queue, not as a current assessment.

| Next | Country | Driver as of May 2026 |
|---|---|---|
| 1 | 🇧🇫 Burkina Faso | Sahel coup belt; Russia spoke; cotton / gold |
| 2 | 🇳🇪 Niger | Sahel coup belt; Russia spoke; uranium (France / EU exposure) |
| 3 | 🇨🇫 Central African Republic | Longest-running Russian deployment — a separate build, not a Sahel clone |
| — | 🇨🇩 DRC | Cobalt convergence; eastern conflict |
| — | 🇪🇹 Ethiopia | Horn anchor; GERD; Tigray aftershocks |
| — | 🇰🇪 Kenya · 🇹🇿 Tanzania · 🇺🇬 Uganda · 🇷🇼 Rwanda · 🇸🇸 South Sudan | East African Community anchors; regional health and displacement response |
| — | 🇿🇦 South Africa | Diamond convergence; BRICS+ anchor |

Burkina Faso and Niger are deliberately next: the Mali tracker's actor roster,
trigger ladders and trajectory evidence are generic where they can be, so the
two AES neighbours are a transform of it rather than a build from scratch. CAR
is not — different roster, no AES membership, no fuel blockade.

### Out of scope (canonical placement elsewhere)

| Country | Lives in |
|---|---|
| 🇲🇦 Morocco | MENA backend (Maghreb / Western Sahara) |
| 🇱🇾 Libya | MENA backend (Mediterranean / Maghreb), mirrored on the Africa dashboard via Redis fingerprint linkage |
| 🇪🇬 Egypt | MENA backend (Arab world / Nile basin) |

---

## 🏗 Architecture

Follows the canonical Asifah pattern established by the ME, Europe, Asia and WHA
backends.

- **Flask + gunicorn** on Render
- **Shared Upstash Redis** for cross-theatre fingerprints and per-tracker scan caches
- **Multi-source OSINT ingestion** — GDELT, NewsAPI, Brave Search, RSS, Telegram, Bluesky
- **Per-country rhetoric trackers** registered via the `register_<country>_rhetoric_endpoints(app)` pattern
- **Per-country signal interpreters** producing the so-what / red-lines / historical-analogue contract
- **Regional BLUF synthesis** — `africa_regional_bluf.py`
- **Commodity and convergence proxies** reading the ME backend's canonical registries

### Modules

| Area | Files |
|---|---|
| Rhetoric trackers | `rhetoric_tracker_somalia.py`, `rhetoric_tracker_sudan.py`, `rhetoric_tracker_mali.py` |
| Interpreters | `somalia_signal_interpreter.py`, `sudan_signal_interpreter.py`, `mali_signal_interpreter.py` |
| Humanitarian | `somalia_humanitarian.py`, `sudan_humanitarian.py`, `mali_humanitarian.py` |
| Regional synthesis | `africa_regional_bluf.py` |
| Proxies | `commodity_proxy_africa.py`, `convergence_proxy_africa.py` |
| Ingestion | `africa_article_gatherer.py`, `gdelt_gateway.py`, `brave_gateway.py`, `rss_monitor.py`, `telegram_signals_africa.py`, `bluesky_signals_africa.py` |
| Country modules | `nigeria_stability.py`, `ngx_index_scraper.py`, `ngx_pulse_client.py` |
| Shared libraries | `spoke_wheel_reader.py`, `trajectory_reader.py`, `theatre_state.py`, `feed_health.py` |

**Shared libraries deploy byte-identical to every backend.** `spoke_wheel_reader.py`
and `trajectory_reader.py` are library code, not data — the proxy pattern governs
producers, not libraries. If you change one here, change it everywhere.

---

## 🚀 Deployment

Deploys to Render via GitHub auto-deploy.

### Required environment variables

| Variable | Purpose |
|---|---|
| `UPSTASH_REDIS_URL` | Upstash Redis REST endpoint |
| `UPSTASH_REDIS_TOKEN` | Upstash Redis REST bearer token |
| `NEWSAPI_KEY` | NewsAPI.org API key |
| `BRAVE_API_KEY` | Brave Search API key (tertiary OSINT fallback) |
| `TELEGRAM_API_ID` | Telegram MTProto API ID |
| `TELEGRAM_API_HASH` | Telegram MTProto API hash |
| `TELEGRAM_PHONE` | Telegram account phone number |
| `TELEGRAM_SESSION_BASE64` | Base64-encoded Telethon session file |
| `DTM_API_KEY` | IOM Displacement Tracking Matrix API key (humanitarian modules) |
| `PYTHONUNBUFFERED` | Set to `1` — forces stdout flush for Render Live Tail visibility |

### Render configuration

```
Language:        Python 3
Region:          Virginia
Build Command:   pip install -r requirements.txt
Start Command:   gunicorn app:app --timeout 300 --workers 2
Health Check:    /
```

> ⚠️ **CRITICAL:** the start command MUST include `--timeout 300 --workers 2`.
> Default Render Python services use a 30-second timeout, which is shorter than a
> full scan cycle. Forgetting this flag is the single most common Render deploy
> bug across Asifah backends.

### Manual redeploy

Auto-deploy is enabled, but the canonical practice is to confirm each deploy
manually in the Render dashboard so the deploy log can be read before scans run.

> On a 404 after deploy, read the **startup sequence** in the log, not the tail.
> An import error prints its traceback at boot and has usually scrolled away by
> the time you look.

### Endpoints

Full inventory at `/debug/routes`. The ones used most — `<country>` below means
**somalia, sudan or mali only**; a country without a tracker returns 404, which
is a coverage gap, not an outage:

| Endpoint | Purpose |
|---|---|
| `/api/rhetoric/<country>` | Country tracker — add `?force=true` for a fresh scan |
| `/api/rhetoric/<country>/history` | Scan history (120 entries, newest first) |
| `/api/rhetoric/africa/bluf` | Regional BLUF — `?force=true` rebuilds |
| `/api/rhetoric/africa/bluf/debug` | Cache state and per-tracker sensor inventory |
| `/api/africa/humanitarian/<country>` | Humanitarian read |
| `/api/africa/commodity/<target>` | Commodity proxy to the ME backend |
| `/api/africa/convergence/by-country/<country>` | Convergence proxy |
| `/api/nigeria/stability` | Nigeria stability + NGX market pulse |
| `/api/africa/scan-all` | Full theatre scan |
| `/debug/routes` | Registered route inventory |

> ⚠️ `?force=true` on a cold service can exceed a five-minute client timeout.
> Prefer the cached read unless a rebuild is genuinely needed.

---

## 🤝 Cross-backend integration

Africa sits in the three-altitude architecture: sensors below, analyst in the
middle, global index above.

```
Per-country rhetoric trackers (Somalia, Sudan, Mali)
              │
              ▼
   africa_regional_bluf.py  ─────►  Global Pressure Index (GPI)
              ▲                              ▲
              │                              │
        commodity_proxy_africa.py   convergence_proxy_africa.py
              ▲                              ▲
              │                              │
        ME backend's canonical commodity_tracker
                                            +
                            ME backend's convergence_registry
```

**Africa hosts no hub.** Every wheel read here is outbound — African countries
feed hubs resident on other backends (Russia and Turkey via Europe, China via
Asia). `RESIDENT_HUBS` is therefore empty and the convergence panel renders as
pure emanating.

Africa-relevant convergences in the canonical registry:

- `cobalt_drc_active` (anchor: DRC)
- `diamonds_sanctions_regime` (anchor: South Africa + Zimbabwe + DRC)
- `phosphate_food_security` (anchor: Morocco, Africa-impactful)

---

## 📋 Working practices

**Doctrine.** Every module here follows the platform-wide analytical discipline:

- **Convergence, not prediction.** Report the signals that are present. Never
  assert that an outcome is imminent, likely, or dated.
- **`unknown` is a state, never a silence.** A sensor that could not read
  something says so. It does not emit a zero.
- **A real zero is not an unread zero.** "Measured, found nothing" and "nobody
  measured" are different findings and render differently.
- **Absence is reported, not inferred.** Countries without a tracker are absent
  from the regional read, not assessed as quiet.
- **Silence can be the signal.** For claiming actors, quiet against their own
  baseline is a tempo change, not calm.
- **Claims are labelled as claims.** Where a reading rests on an interested
  party's unconfirmed assertions, it is reported as claimed, not established.
- **One writer, many readers.** Data has exactly one producer. Duplicating a
  producer is how two services start disagreeing about the same country.

**Engineering.**

- Surgical find/replace edits preferred over full-file rewrites
- AST validation before every deploy is mandatory:
  `python3 -c "import ast; ast.parse(open('FILE.py').read()); print('ok')"`
- Static reference data carries `source`, source URL and a `data_as_of` date —
  date-stamp rather than hardcode, so staleness is visible rather than assumed
- A diagnostic that lies is worse than no diagnostic. A health check that cannot
  fail is not a health check.

---

## 📞 Contact

Built and maintained by RCGG / Asifah Analytics. Licensing: see
[`LICENSE`](./LICENSE).

- ☕ [Buy Me a Coffee](https://buymeacoffee.com/asifahanalytics) — pays for hosting
- [asifahanalytics.com](https://asifahanalytics.com) · *Not for operational use*

Donations support running costs. They buy no licence, no warranty, no support
obligation and no influence over what gets built.

---

*© 2025–2026 RCGG / Asifah Analytics. All rights reserved.*

*Last updated: 5 October 2026*
