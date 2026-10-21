# 🖥️ Nginx Wargames WOPR dashboard

> *"A strange game. The only winning move is not to play."*

A retro **War Games** (1983) inspired system monitor. The dashboard targets a Raspberry Pi running Nginx and replaces the default nginx landing page with a fully functional command center. I built this using my favorite TUI (Warp) just for fun. I have been working on a build sheet for a home lab and thought it would be cool to have a command center screen running on top of the rack. The chatbot is currently just a small library but I plan to expand that to the Smart Factory Omnis bot with it's own TUI inline so I can work directly from the dashboard. As I add more nodes the center will expand to toggle across the network and I will add Tailwind to make it globablly available and likely run a local ledger for passwordless security. No matter where this one goes I had a ton of fun building it over a few days. War Games is still a great movie and the command center in the movie is still some of my favorite visual design of the era.

Live telemetry. Real attack data. Playable retro games. CRT scanlines. What more could you want?
## Windows Command Center

The Windows edition is a local-first, retro command center for a spare screen:
real PC telemetry, a PowerShell/Azure CLI reference terminal, offline robotic
JOSHUA speech, games, and optional public-world intelligence. No Azure account
is required. The terminal **explains commands; it cannot execute them**.

### Easiest setup: portable ZIP

Once a Windows build artifact is available:

1. Download `WOPR-Windows-x64.zip` from this repository's **Actions → Windows
   portable WOPR** successful run. You may need to sign in to GitHub to download
   Actions artifacts. Extract the artifact, then extract the WOPR ZIP inside it.
2. Open `WOPR.exe` in the extracted `WOPR` folder. Keep `_internal/` and `speech/`
   alongside it. Do not run as administrator.
3. Your browser opens at a randomly selected **local-only** address. Use the
   voice test/greeting control to hear JOSHUA; browsers require a user gesture
   before playing audio.
4. Choose whether to enable public feeds. Local stats, voice and games work
   offline. Fullscreen, privacy, amber/green themes and low-motion controls make
   the dashboard suitable for a second screen.
   Windows starts in compact **WALLBOARD** mode on wide displays; select
   **SHOW TERMINAL** to open the PowerShell/Azure reference and expanded panels.
5. Use the dashboard shutdown control or **Ctrl+C in the WOPR console** to stop
   the local server. Closing a browser tab alone does not stop it.

There is no Python/Nginx installer, account setup, firewall rule, automatic
startup entry, or Azure CLI dependency in a portable build. Initial builds are
unsigned: SmartScreen and managed-company policies may block them. Follow your
organization's approval process; do not disable protections to run WOPR.

**Build status:** the repository contains the build workflow, not a prebuilt
Windows executable. A ZIP exists only after that workflow actually succeeds.
Windows x64 is the first packaging target; native ARM64 is not currently built.

### What is real?

- **Local:** CPU/per-core load, memory, drives and disk activity, network
  throughput, connection/process counts, uptime, battery/AC and bounded
  process-name/resource summaries. Available Windows service and
  Defender/firewall state is read-only and best-effort.
  The local flight recorder shows measured threshold changes and runtime
  events—not invented attacks or private Windows event-log messages.
- **Unavailable sensors:** CPU/GPU temperatures and unsupported metrics show
  `N/A` rather than made-up readings. No low-level hardware drivers are installed.
- **Global, opt-in:** SANS Internet Storm Center InfoCon, CISA's known-exploited
  vulnerability bulletins, NOAA space-weather Kp and USGS earthquake locations.
  Each feed has its own status/timestamps; a global alert is **not** a detected
  attack on your computer, and an advisory is **not** a scan of installed software.
- **Theater:** the cyber attack arcs/radar effects are labeled simulations or
  visualizations. The separate earthquake map uses published coordinates.

The Windows helper covers PowerShell and Azure CLI discovery, objects/pipelines,
files, processes, services, networking, logs, JSON, subscriptions, resource
groups, VMs, storage and query examples. It is an offline reference, not a
general-purpose AI model. Never paste passwords, tokens, or other secrets into it.
Use Microsoft Learn links for authoritative syntax and current behavior.

### Windows source setup (developers)

Install Python 3.11+ from [python.org](https://www.python.org/downloads/windows/),
then run these commands from the extracted repository in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv\Scripts\python.exe windows\wopr.py
```

You can also use `Launch WOPR.cmd` or `windows/Launch-WOPR.ps1` once the virtual
environment exists. These do not bypass PowerShell execution policy. The direct
Python command above works without activating the environment. `--offline`
forces public feeds off for that run; `--no-browser` suppresses opening a tab.
Source runs use an installed `espeak-ng` when available; the portable package
includes its own engine. Lack of speech does not prevent telemetry/games.

### Building the portable edition

Use the **Windows portable WOPR** GitHub Actions workflow, or a Windows x64
maintainer machine with Python 3.12, CMake and Visual Studio C++ Build Tools:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe windows\build_windows.py
```

The build freezes Python/psutil, compiles checksum-pinned eSpeak NG/Sonic with a
static Windows runtime, includes speech data/licenses/corresponding source,
and smoke-tests an extracted package from a path containing spaces before
creating `dist/WOPR-Windows-x64.zip` and its SHA-256 file. Build-time upstream
downloads are separate from runtime public-feed consent. No binaries are
downloaded at launch. See `THIRD_PARTY_NOTICES.txt`.

For a source smoke test on Linux, create a virtual environment, install
`requirements-windows.txt`, and run `python windows/wopr.py --no-browser
--offline`. This exercises the portable runtime, not Windows-specific probes.
`python windows/build_windows.py --speech-only` validates the speech source
build on the current platform; it does **not** cross-compile a Windows app.

### Windows acceptance checks

Before sharing a release, verify a successful Windows CI artifact and test it
as a standard user on Windows 10/11 with Edge or Chrome:

- Extract to a directory with spaces; launch, refresh, play all three games,
  and keep the screen running for an extended session.
- Hear the offline robotic greeting and helper replies; test mute/stop,
  voice settings and rapid requests. No sound is played before user interaction.
- Check actual Task Manager metrics against the dashboard; unavailable
  services/sensors should remain unavailable, not misleadingly green.
- Verify feed consent, timestamps, offline behavior and reconnection; test
  privacy, fullscreen, theme and low-motion settings.
- Shut down and confirm the process/listener exits. No inbound/LAN access or
  administrator permission should be necessary.

No Windows CI result or audible Windows-browser test is implied merely by the
presence of the workflow. Development on the Raspberry Pi cannot certify those.
![Windows-edition wallboard preview](docs/wopr-windows-preview.png)

*Privacy-masked preview of the Windows-edition UI running against the portable
runtime on Linux. Windows-native probes and the Windows executable still need
Windows validation; the public feeds shown were fetched from their providers.*

### Privacy and uninstalling

The Windows runtime binds only to IPv4 loopback. Local stats are not sent to any
feed provider. Optional providers see the normal requesting public IP, like any
website request, but no hostname, local addresses, process list or Azure details
are added. No packet capture, network scanning or login-token access is used.
Privacy mode masks screen identifiers; it is not an authorization boundary.
Feed consent is stored in a per-user WOPR settings directory outside the served
assets, and browser preferences live in localStorage. See `SECURITY.md` for the
precise security boundaries and limitations.

To uninstall, stop WOPR and delete the extracted folder. Remove its per-user
`%LOCALAPPDATA%\WOPR\settings.json` and browser site data too if you want to reset
preferences.

![WOPR Dashboard](docs/wopr-dashboard.png)

![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-red)
![nginx](https://img.shields.io/badge/server-nginx-brightgreen)

## Features

- **Live System Telemetry** — CPU, memory, disk, network stats updated every 3 seconds
- **DEFCON Thermal Monitor** — CPU temperature mapped to DEFCON levels with throttle warnings
- **Global Threat Map** — Natural Earth GeoJSON world map with animated attack arcs, realistic CVE/malware names, and rolling strike counter
- **Playable Retro Games** — Tic-Tac-Toe vs JOSHUA (movie-accurate!), Missile Command, and Snake — all in CRT-styled pop-up modals (more to come)
- **Network Operations Radar** — Real-time RX/TX rates, active connections, with animated radar display
- **System Log Intercepts** — Live journal log feed displayed in-dashboard
- **Real SSH Attack Data** — Parses `auth.log` for actual failed login attempts
- **Interactive JOSHUA Terminal** — In-browser Linux command helper chatbot (pattern-matching, no LLM required). Covers 40+ commands and 20+ "how to" topics. War Games easter eggs included. I'll add more libraries to this as the homelab build advances.
- **JOSHUA Voice Synthesis** — JOSHUA speaks its terminal responses aloud using `espeak-ng`'s robotic voice (the same flat, synthesized tone used for WOPR-style sci-fi computer voices). Toggle on/off from the status bar.
- **Service Status Monitor** — Live status of nginx, SSH, cron, dbus, NTP, journald, network, and the WOPR stats service. I plan to add messaging/alerts to this eventually
- **CRT Aesthetic** — Scanlines, phosphor glow, pixel sprites and an embedded offline VT323 terminal font
- **Responsive** — Collapses to single-column on mobile

## Games

Three playable retro games, all in the War Games aesthetic:

- **Tic-Tac-Toe vs JOSHUA** — Play against the WOPR AI. You're X (green), JOSHUA is O (amber). Draws trigger the iconic movie quote. Just like the film's climax.
- **Missile Command** — Defend 6 cities from incoming ICBMs. Click to fire counter-missiles. Waves escalate. Very thematic.
- **Snake** — Classic 8-bit snake on a green-phosphor grid. Arrow keys to move.

Games open in CRT-styled modal popups. Close with ✕, Escape, or clicking outside. The original movie game list (Chess, Checkers, Global Thermonuclear War) remains for atmosphere — clicking "Global Thermonuclear War" still triggers the classic response.

## Architecture

```
┌──────────────┐       ┌───────────────────┐       ┌──────────────┐
│  Browser     │──────▸│  nginx            │──────▸│  index.html  │
│  (any device)│       │  :80              │       │  (dashboard) │
└──────────────┘       └───────────────────┘       └──────┬───────┘
                              │                           │
                              │ serves static             │ fetches
                              ▼                           ▼
                       /var/www/html/             /api/stats.json
                              │                         ▲
                              │                         │ writes
                       /data/ne_110m_land.json  ┌───────┴────────┐
                       (Natural Earth GeoJSON)  │ wopr-stats.sh  │
                                                │ (systemd svc)  │
                                                │ runs every 2s  │
                                                └────────────────┘
```

**Raspberry Pi edition:** no Node.js, Python, or databases at runtime — just bash,
nginx, and a browser (plus `espeak-ng` + `fcgiwrap` for voice). The portable Windows
edition bundles a separate Python-based local runtime.

## Raspberry Pi Quick Install

### Prerequisites

- Raspberry Pi (tested on Pi 5, should work on Pi 3/4/Zero 2)
- Raspberry Pi OS (Debian-based)
- nginx installed (`sudo apt install nginx`)
- `bc` package (`sudo apt install bc`)
- `espeak-ng` and `fcgiwrap` for JOSHUA's voice (`sudo apt install espeak-ng fcgiwrap`) — installer handles this automatically; voice is skipped gracefully if unavailable

### One-Line Install

```bash
git clone https://github.com/dougrichards13/nginx_WOPR.git
cd nginx_WOPR
sudo bash install.sh
```

### Manual Install

```bash
# Copy dashboard to nginx root
sudo cp src/index.html /var/www/html/index.nginx-debian.html

# Install stats gatherer
sudo cp src/wopr-stats.sh /usr/local/bin/wopr-stats.sh
sudo chmod +x /usr/local/bin/wopr-stats.sh

# Fix line endings (if transferred from Windows)
sudo sed -i 's/\r$//' /usr/local/bin/wopr-stats.sh

# Create API directory
sudo mkdir -p /var/www/html/api

# Install and start systemd service
sudo cp src/wopr-stats.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wopr-stats

# Install JOSHUA voice synthesis (optional)
sudo apt install -y espeak-ng fcgiwrap
sudo cp src/wopr-speak.cgi /usr/local/bin/wopr-speak.cgi
sudo chmod +x /usr/local/bin/wopr-speak.cgi
sudo mkdir -p /etc/nginx/snippets
sudo cp src/wopr-speak.conf /etc/nginx/snippets/wopr-speak.conf
# Add this line inside your server {} block (e.g. /etc/nginx/sites-enabled/default):
#   include snippets/wopr-speak.conf;
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable --now fcgiwrap.socket

# Verify
curl -s http://localhost/api/stats.json | head -5
curl -s -o /tmp/test.wav "http://localhost/api/speak?text=greetings+professor+falken" && file /tmp/test.wav
```

Then visit `http://<your-pi-ip>/` in a browser.

## Updating

Pull the latest and re-run the installer:

```bash
cd nginx_WOPR
git pull
sudo bash install.sh
```

## Multi-Device Deployment

This project is designed with multi-Pi homelab setups in mind. Each Pi runs its own independent WOPR instance — the dashboard reads from the local `/api/stats.json` and displays that machine's identity (hostname, IP, OS) automatically.

**To deploy to a new Pi:**

```bash
# From your workstation:
ssh user@new-pi "git clone https://github.com/dougrichards13/nginx_WOPR.git && cd nginx_WOPR && sudo bash install.sh"
```

**Planned multi-device features (future):**
- Central "War Room" dashboard aggregating all equipment nodes - still planning the hardware for the rack but I do want to experiement with gpu clusters and the Reticulum project DataSlayerMedia built on his channel
- Node discovery / fleet status overview
- Cross-node alerting (e.g. if a Pi goes offline)
- Per-node configuration (custom names, DEFCON thresholds, monitored services)

## Customization

### Changing Monitored Services

Edit `src/wopr-stats.sh` — the `svc_status()` calls near line 96 control which services are reported. Update the HTML `status-line` entries to match.

### Adjusting DEFCON Thresholds

In `src/index.html`, find the `tempToDefcon()` function and adjust the temperature breakpoints.

### Adding Cities to the Threat Map

The `cities` array in `src/index.html` holds `[name, longitude, latitude]` entries. Add your own strategic locations.

### Adding Games

Each game is a self-contained `init` function in the mini-games engine section of `src/index.html`. To add a new game: create an `initYourGame()` function that draws on `gameCanvas`, add it to the `GAMES` map, and add a `<li class="playable" data-game="yourgame">` entry to the game list.

### Changing JOSHUA's Voice

JOSHUA's speech is generated server-side by `src/wopr-speak.cgi`, which calls `espeak-ng -v en -s 175 --stdout -- "$TEXT"`. Adjust `-v` (voice, e.g. `en-us`, `en-gb`) or `-s` (words per minute) there. List available voices with `espeak-ng --voices`. Disable voice entirely per-browser via the VOICE toggle in the status bar (persisted in `localStorage`).

## Security Notes

- **The stats script runs as root** via systemd to access thermal sensors and service status. Review `src/wopr-stats.sh` before installing — it only reads system information and writes JSON to the nginx web root.
- **The voice endpoint (`/api/speak`) accepts arbitrary text** and passes it to `espeak-ng` as an argument (guarded with `--` to prevent option injection). It runs via `fcgiwrap`, not as root, and only ever produces audio output — review `src/wopr-speak.cgi` before installing.
- **Pi dashboard requests stay local.** Automatic requests use the same-host stats, speech and map endpoints; the font is embedded, with no remote font or analytics request. Windows public intelligence is separately opt-in as described above.
- **The "attacks" on the threat map are simulated** for visual effect. Real SSH brute-force attempts from `auth.log` are included in the stats JSON but are currently displayed in the log panel, not on the map.
- **No authentication.** Anyone on your network can view the dashboard. If your Pi is exposed to the internet, consider adding nginx basic auth or firewall rules.

See [SECURITY.md](SECURITY.md) for the full security policy and how to report vulnerabilities.

## Credits

- Inspired by the 1983 film *WarGames* and the WOPR/Joshua system
- Built with [Warp](https://www.warp.dev/) AI-assisted agentic development (co-authored by Warp's AI agent)
- Map data: [Natural Earth](https://www.naturalearthdata.com/) 110m land polygons (public domain)
- Font: [VT323 by Peter Hull](https://github.com/google/fonts/tree/main/ofl/vt323), embedded under SIL Open Font License 1.1; see `FONT_LICENSES.txt`

## License

MIT — see [LICENSE](LICENSE). Free to use, modify, and distribute.

---

*"Shall we play a game?"*
