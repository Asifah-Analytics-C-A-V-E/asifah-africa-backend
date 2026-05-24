# asifah-africa-backend

**Backend Africa Files for Asifah Analytics**

The Africa theatre backend for [Asifah Analytics](https://asifahanalytics.com) — a real-time open-source intelligence platform tracking geopolitical pressure, conflict escalation, and humanitarian crisis signals across global theatres.

This backend serves the Africa AOR / AFRICOM theatre. Sister backends cover the Middle East & North Africa, Europe, Asia & The Pacific, and the Western Hemisphere.

> 🚨 **Not for operational use.** Asifah Analytics is built for analytical and research purposes only. See [`LICENSE`](./LICENSE).

---

## 🌍 Coverage

### Tier 1 Countries (launch — May 2026)

Fourteen sub-Saharan and Sahel countries selected to cover:

| # | Country | Primary analytical driver |
|---|---|---|
| 1 | 🇨🇩 DRC | Ebola Bundibugyo PHEIC epicenter (Ituri, Nord-Kivu, Sud-Kivu); cobalt convergence |
| 2 | 🇺🇬 Uganda | Ebola spread; East African Community anchor |
| 3 | 🇷🇼 Rwanda | Ebola response; M23 / DRC backing |
| 4 | 🇸🇸 South Sudan | Ebola at-risk; 2026 peace process |
| 5 | 🇰🇪 Kenya | Ebola response; East African anchor; Haiti deployment |
| 6 | 🇹🇿 Tanzania | Ebola response; East African anchor |
| 7 | 🇸🇩 Sudan | Active war; IPC Phase 5 famine; RSF / SAF / UAE / Russia axis |
| 8 | 🇪🇹 Ethiopia | Horn of Africa anchor; GERD; Tigray aftershocks |
| 9 | 🇸🇴 Somalia | Al-Shabaab; AMISOM successor; Indian Ocean |
| 10 | 🇳🇬 Nigeria | West Africa anchor; Boko Haram; oil |
| 11 | 🇲🇱 Mali | Wagner stronghold; Sahel coup belt |
| 12 | 🇳🇪 Niger | Wagner; uranium (France/EU exposure); Sahel coup |
| 13 | 🇧🇫 Burkina Faso | Wagner; Sahel coup; cotton/gold |
| 14 | 🇿🇦 South Africa | Diamond convergence; BRICS+ anchor |

### Out of scope (canonical placement elsewhere)

| Country | Lives in |
|---|---|
| 🇲🇦 Morocco | MENA backend (Maghreb / Western Sahara) |
| 🇱🇾 Libya | MENA backend (Mediterranean / Maghreb), mirrored on Africa dashboard via Redis fingerprint linkage |
| 🇪🇬 Egypt | MENA backend (Arab world / Nile basin) |

---

## 🏗 Architecture

Africa backend follows the canonical Asifah pattern established by the ME, Europe, Asia, and WHA backends:

- **Flask + gunicorn** running on Render ($7/mo Starter tier, Virginia region)
- **Shared Upstash Redis** instance for cross-theatre fingerprints + per-tracker scan caches
- **Multi-source OSINT ingestion** — GDELT, NewsAPI, Brave Search, RSS, Telegram, Bluesky
- **Per-country rhetoric trackers** (modular Python files registered via `register_<country>_rhetoric_endpoints(app)` pattern)
- **Regional BLUF synthesis** via `africa_regional_bluf.py` (rolls up per-country signals into theatre prose)
- **Commodity + convergence proxies** read from the ME backend's canonical registries

### Build status

| Component | Status |
|---|---|
| Backend repo + Render service | 🟢 Live (this repo) |
| `app.py` skeleton | ⏳ In progress |
| Telegram + Bluesky source modules | ⏳ In progress |
| Commodity + convergence proxies | ⏳ In progress |
| Sudan rhetoric tracker (first) | 🔴 Not started |
| `africa_regional_bluf.py` | 🔴 Not started |
| Per-country stability pages | 🔴 Not started |

---

## 🚀 Deployment

This service deploys to Render via GitHub auto-deploy.

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
| `DTM_API_KEY` | IOM Displacement Tracking Matrix API key (for humanitarian module) |
| `PYTHONUNBUFFERED` | Set to `1` — forces stdout flush for Render Live Tail visibility |

### Render configuration

```
Language:        Python 3
Region:          Virginia
Build Command:   pip install -r requirements.txt
Start Command:   gunicorn app:app --timeout 300 --workers 2
Instance Type:   Starter ($7/mo)
Health Check:    /
```

> ⚠️ **CRITICAL:** the start command MUST include `--timeout 300 --workers 2`. Default Render Python services use a 30-second timeout, which is shorter than a full scan cycle. Forgetting this flag is the single most common Render deploy bug across Asifah backends.

### Manual redeploy

After every commit to `main`, manually trigger a redeploy in the Render dashboard. Auto-deploy is enabled but the canonical practice is to confirm each deploy manually so we can verify the deploy log before scans run.

### Force-refresh endpoints (once trackers ship)

- `https://asifah-africa-backend.onrender.com/api/rhetoric/<country>?force=true` — fresh scan
- `https://asifah-africa-backend.onrender.com/api/rhetoric/africa/bluf?force=true` — regional BLUF
- `https://asifah-africa-backend.onrender.com/api/africa/commodity/<country>` — commodity proxy
- `https://asifah-africa-backend.onrender.com/debug/routes` — registered route inventory

---

## 🤝 Cross-backend integration

Africa is part of the three-altitude architecture:

```
Per-country rhetoric trackers (Sudan, DRC, ...)
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

Africa-relevant convergences already in the canonical registry:

- `cobalt_drc_active` (anchor: DRC)
- `diamonds_sanctions_regime` (anchor: South Africa + Zimbabwe + DRC)
- `phosphate_food_security` (anchor: Morocco, but Africa-impactful)

---

## 📋 Working practices

- **Surgical find / replace** edits preferred over full file rewrites
- **AST validation pre-deploy** is mandatory: `python3 -c "import ast; ast.parse(open('FILE.py').read()); print('ok')"`
- **Data honesty standard:** all static reference data includes source, source URL, and `data_as_of` date
- **Convergence-not-prediction framing:** Africa modules will follow the Black Swan analytical discipline — report what signals are present, not whether outcomes are imminent

---

## 📞 Contact

Built and maintained by RCGG / Asifah Analytics. For licensing inquiries see [`LICENSE`](./LICENSE).

[asifahanalytics.com](https://asifahanalytics.com) · *Not for operational use*

---

*© 2025-2026 Asifah Analytics. All rights reserved.*
