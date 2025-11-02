# Nitter Scraper Web

Ein konservativer, sofort einsatzbereiter Web-Scraper für öffentliche Nitter-Instanzen inklusive lokalem Darkmode-Dashboard.

## Projektstruktur

```
backend/
  app.py
  config.example.json
  nitter_client.py
  requirements.txt
  storage.py
frontend/
  app.js
  index.html
  styles.css
scripts/
  run_dev.sh
  run_dev.ps1
.env.example
LICENSE
README.md
```

## Installation (5 Schritte)

1. Repository klonen oder entpacken: `git clone <repo>`
2. In das Projektverzeichnis wechseln: `cd nitter`
3. Python 3.11 sicherstellen (`python3 --version`)
4. Beispiel-Umgebungsvariablen kopieren (optional): `cp .env.example .env`
5. Abhängigkeiten beim ersten Start über das Startskript installieren lassen (siehe unten).

## Start

### Linux & macOS

```bash
chmod +x scripts/run_dev.sh
./scripts/run_dev.sh
```

### Windows (PowerShell)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
./scripts/run_dev.ps1
```

Die Skripte erzeugen bei Bedarf eine virtuelle Umgebung (`.venv`), installieren die Anforderungen, starten die Flask-Anwendung auf `http://localhost:5173` und öffnen Google Chrome (bzw. den Standardbrowser) automatisch.

## Nutzung

1. **Targets prüfen**: Auf der linken Seite stehen die voreingestellten Nitter-Ziele (User & Hashtags). Neue Ziele können über das Formular hinzugefügt werden.
2. **Live-Stream**: Der Timeline-Tab zeigt neue Tweets automatisch via Server-Sent Events (SSE) an. Filter (Target, Limit, Textsuche) ermöglichen eine schnelle Eingrenzung.
3. **Fetch Once**: Der Button startet eine manuelle Abrufrunde für alle Targets (Summary erscheint im Event-Log).
4. **Export JSONL**: Lädt alle gespeicherten Tweets als `export.jsonl` herunter.
5. **Self-Check**: Liest den Health-Endpunkt und zeigt Instanzzustände, Tokenstände und Backoffs.
6. **Settings**: Informiert über aktive Instanzen, User-Agent und erinnert daran, dass Anpassungen über `backend/config.json` erfolgen.

## Backend-Details

- **Konfiguration**: Beim ersten Start wird `backend/config.example.json` nach `backend/config.json` kopiert. Anpassungen (Instanzen, Polling-Intervalle, Limits) dort vornehmen und Dienst neu starten.
- **Speicherung**: SQLite-DB unter `./data/nitter.db`. Standard-Schema siehe `backend/storage.py`.
- **Abruflogik**: RSS bevorzugt (`feedparser`), HTML-Fallback via Regex. Instanzrotation mit Token-Bucket und exponentiellem Backoff.
- **Scheduler**: Interner Thread prüft Targets gemäß Intervall, sendet SSE-Ereignisse (`tick`, `new_tweet`, `error`, `cooldown`).
- **Sicherheit/Ethik**: Keine Logins, keine Cookies. User-Agent und Polling konservativ halten; Rate Limits respektieren.

## Sicherheitshinweise

- Belasten Sie Nitter-Instanzen nicht unnötig. Verwenden Sie konservative Intervalle und achten Sie auf Backoff-Meldungen.
- `media_download` bleibt bewusst deaktiviert – Fokus auf Textinhalte.
- Prüfen Sie regelmäßig `./data/nitter.log` auf Fehlermeldungen und Rate-Limit-Hinweise.

## Troubleshooting

| Problem | Lösung |
| --- | --- |
| **403/429 Fehler** | Instanz wurde gedrosselt. Scheduler setzt Backoff automatisch. Intervall erhöhen, andere Instanzen ergänzen. |
| **Keine neuen Tweets** | Ziel prüfen (schreibt es überhaupt Tweets?). Intervall oder Suchbegriff anpassen, Logs kontrollieren. |
| **Cooldown-Meldungen häufen sich** | Rate-Limit erreicht. Zusätzliche Nitter-Instanzen in der Config hinterlegen. |
| **SSE-Verbindung getrennt** | Browser/Firewall blockiert SSE. Seite neu laden oder `enable_sse` in `config.json` prüfen. |
| **CORS-Fehler** | Frontend und Backend laufen auf demselben Host. Sollte CORS dennoch auftreten, Browser-Cache leeren oder lokalen Proxy deaktivieren. |

## Warum SSE statt WebSockets?

SSE (Server-Sent Events) ist einfacher zu betreiben: Es benötigt nur eine HTTP-Verbindung, funktioniert hinter den meisten Firewalls und reicht für einseitige Statusupdates völlig aus. Für den konservativen Polling-Ansatz genügt dieses Push-Modell ohne zusätzlichen WebSocket-Overhead.

## Darkmode anpassen

Die UI basiert auf Tailwind-Klassen. Farbwerte lassen sich direkt in `frontend/index.html` anpassen oder über Custom Properties in `frontend/styles.css` erweitern. Beispiel: `bg-slate-900` durch `bg-neutral-900` ersetzen, um den Kontrast zu verändern. Für globale Anpassungen können im `:root`-Block neue CSS-Variablen definiert und in Tailwind-Klassen eingebunden werden.

## Checkliste vor Produktion

- [ ] `backend/config.json` auf individuelle Instanzen, Intervalle und User-Agent prüfen.
- [ ] Polling-Intervalle konservativ wählen, damit Nitter-Instanzen geschont werden.
- [ ] Logs (`./data/nitter.log`) auf Fehler oder Rate Limits kontrollieren.
- [ ] Datenbank-Backup (`./data/nitter.db`) anlegen.
- [ ] Optional Autostart einrichten (z. B. systemd-Service unter Linux).

Viel Erfolg beim sicheren Monitoring Ihrer Nitter-Feeds!
