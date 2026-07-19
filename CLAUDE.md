# FastDemo Builder — Arbeitsanleitung für Claude

## Projekt

Demo-Website-Generator: Nimmt eine Domain, scraped sie, und generiert in 2–5 Minuten eine professionelle HTML-Website via Claude.

---

## Server

```
Anbieter:   Hetzner Cloud
IP:         167.233.25.202
User:       root
SSH:        ssh root@167.233.25.202
OS:         Ubuntu
```

Bestehende Services (nicht anfassen):
- `website-agent-backend` → Port 8001
- `website-agent-frontend` → Port 3000
- `handwerker-backend` → Port 8002
- `handwerker-frontend` → Port 3001

Unser Service:
- `demo-builder-backend` → Port 8003

---

## Code deployen

```bash
# Lokal committen und pushen:
git add ...
git commit -m "..."
git push origin main

# Auf Server:
ssh root@167.233.25.202
cd /opt/demo-builder
git pull
systemctl restart demo-builder-backend

# Status prüfen:
journalctl -u demo-builder-backend -n 50 -f
```

---

## Dateipfade auf dem Server

```
/opt/demo-builder/
├── .env                        # API Keys (Quelle der Wahrheit)
├── backend/
│   ├── .env                    # Kopie der Root-.env
│   ├── .venv/                  # Python venv
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── pipeline/               # scraper, maps_enricher, analyst, builder, evaluator, deployer, orchestrator
│   ├── routers/                # builds.py, dashboard.py
│   ├── services/               # claude_client, r2_client, apify_client, screenshot_client
│   └── static/                 # index.html, style.css, app.js
└── cloudflare-worker/
    ├── worker.js
    └── wrangler.toml
```

---

## Umgebungsvariablen

Liegen auf dem Server unter `/opt/demo-builder/.env`. Können aus `/opt/website-agent/.env` übernommen werden (gleiche R2/Apify-Keys).

```env
DATABASE_URL=postgresql+asyncpg://agentuser:agentpass2024@localhost:5432/demodb
ANTHROPIC_API_KEY=...
APIFY_API_TOKEN=...
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=website-agent
R2_PUBLIC_URL=https://pub-e99a6cc0592a41d3906183633a0ead00.r2.dev
DEMO_DOMAIN=https://deine-neue-website.ch
```

Nach `.env`-Änderung: `cp /opt/demo-builder/.env /opt/demo-builder/backend/.env && systemctl restart demo-builder-backend`

---

## Datenbank

```
Server:     localhost:5432
DB:         demodb
User:       agentuser
Passwort:   agentpass2024
```

```bash
# DB-Verbindung testen:
sudo -u postgres psql demodb -c "SELECT count(*) FROM builds;"

# Tabellen ansehen:
sudo -u postgres psql demodb -c "\dt"
```

Tabellen: `builds`, `build_versions` — werden beim ersten Start automatisch erstellt.

---

## Nginx

Config: `/etc/nginx/sites-available/demo-builder`

- `demo.amplifyr-digital.ch` → Port 8003 (mit Basic Auth via `/etc/nginx/.htpasswd`)
- `demo-api.amplifyr-digital.ch` → Port 8003 (ohne Auth)

```bash
nginx -t && systemctl reload nginx
```

SSL via Let's Encrypt (certbot), bereits konfiguriert.

---

## Cloudflare Worker

Worker `fastdemo-worker` läuft auf `deine-neue-website.ch/*`.
Liest HTML aus R2-Bucket `website-agent` unter `demos/{slug}/latest/index.html`.

```bash
# Worker deployen (aus /opt/demo-builder/cloudflare-worker):
CLOUDFLARE_API_TOKEN=<token> wrangler deploy --config wrangler.toml
```

---

## R2 Bucket — Key-Struktur

Alle drei Agents nutzen denselben Bucket `website-agent`, aber strikt getrennte Präfixe:

| Service | Key-Muster |
|---|---|
| website-agent | `{place_id}/...`, `{slug}` (flat HTML) |
| handwerker-agent | `handwerker/{place_id}/...`, `handwerker/{slug}/index.html` |
| **demo-builder** | `demos/{build_id}/...`, `demos/{slug}/v{n}/index.html`, `demos/{slug}/latest/index.html` |

---

## Python-Abhängigkeiten

```bash
cd /opt/demo-builder/backend
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium  # falls neu
```

---

## Debugging

```bash
# Live-Logs:
journalctl -u demo-builder-backend -f

# Backend direkt testen:
curl http://localhost:8003/health

# Letzten Build ansehen:
curl http://localhost:8003/api/v1/builds | python3 -m json.tool | head -40

# Service neu starten:
systemctl restart demo-builder-backend
```

---

## Wichtige Architektur-Entscheidungen

- **Kein separates Frontend** — Dashboard wird von FastAPI als statische Datei ausgeliefert
- **Pipeline läuft async** — `asyncio.create_task`, gibt sofort `build_id` zurück
- **Fortschritt via WebSocket** — `/api/v1/builds/ws/{id}` pollt DB alle 2s
- **Evaluator max. 2 Runden** — danach wird trotzdem deployed
- **Slug beim Start generieren** — nicht am Ende, damit R2-Keys sofort verfügbar
- **Blockierende Calls** (Claude, Apify) immer via `asyncio.to_thread()` wrappen
- **HTML-Extraktion** — Builder gibt manchmal Markdown-Codeblock zurück, `extract_html()` in builder.py fängt das ab
