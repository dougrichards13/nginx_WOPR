# Security Policy

## Overview

WOPR Dashboard is a local-network system monitoring tool. It consists of:

1. **A static HTML dashboard** (client-side only JavaScript)
2. **A bash stats script** that runs as a systemd service with root privileges
3. **nginx** serving static files

## Threat Model

This project is designed for **trusted local networks** (homelabs, home networks). It is NOT designed to be exposed to the public internet without additional hardening.

### What the stats script does (and doesn't do)

The `wopr-stats.sh` script runs as root and **only performs read operations**:

- Reads CPU temperature from `/sys/class/thermal/`
- Reads CPU frequency from `/sys/devices/system/cpu/`
- Reads memory/disk/network stats from `/proc/` and standard utilities (`df`, `ss`, `ps`)
- Reads service status via `systemctl is-active`
- Reads system logs via `journalctl` (last 15 entries)
- Reads auth.log for failed SSH login attempts
- Writes a single JSON file to `/var/www/html/api/stats.json`

It does **not**:
- Open any network connections
- Execute user-provided input
- Modify system configuration
- Install packages or download files

### What the dashboard does (and doesn't do)

The HTML/JavaScript dashboard:
- Fetches `/api/stats.json` from the same host (relative URL)
- Loads Google Fonts from `fonts.googleapis.com` (the only external request)
- All threat map animations are client-side simulations
- The JOSHUA terminal is a local pattern-matching engine with no network calls

It does **not**:
- Send any data to external servers
- Use cookies, localStorage, or tracking
- Load any third-party JavaScript libraries
- Accept or process any form data beyond the local JOSHUA input

## Known Considerations

1. **No authentication**: The dashboard is accessible to anyone who can reach your Pi on the network. Add nginx basic auth if needed:
   ```
   sudo apt install apache2-utils
   sudo htpasswd -c /etc/nginx/.htpasswd admin
   ```
   Then add to your nginx site config:
   ```
   auth_basic "WOPR Access";
   auth_basic_user_file /etc/nginx/.htpasswd;
   ```

2. **Stats JSON is world-readable**: The JSON file includes your Pi's hostname, IP address, running services, and log excerpts. This is by design for the dashboard but could be an information disclosure concern on untrusted networks.

3. **Root execution**: The stats script requires root for thermal sensor and service status access. Review the script before installing.

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public issue** for security vulnerabilities
2. Email the maintainer or use GitHub's private vulnerability reporting feature
3. Include steps to reproduce, impact assessment, and suggested fix if possible

We will respond within 72 hours and aim to release a fix within 7 days for critical issues.

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest  | ✅        |
| Older   | ❌        |

We recommend always running the latest version.
