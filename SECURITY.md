# Security Policy

WOPR is an entertainment dashboard and read-only system viewer, **not a security
product, intrusion detector or management console**. Its simulated effects and
public advisories do not establish that a machine is attacked, safe or vulnerable.
No software is vulnerability-free; the controls below reduce exposure rather
than promise immunity.

## Windows portable edition

### Exposure and authorization

- The embedded HTTP server binds only to IPv4 loopback and selects an available
  local port. There is no supported LAN bind mode, inbound firewall rule or
  administrator requirement.
- It serves an explicit asset allowlist, not a filesystem directory tree.
  Runtime source, preferences, speech source archives, logs and arbitrary files
  are not web-accessible.
- Host/Origin checks and browser fetch-metadata checks reject cross-site use and
  DNS-rebinding hostnames. No permissive CORS is enabled.
- Speech, feed configuration and shutdown require a per-process unpredictable
  token and same-origin requests. This is protection against other websites,
  **not against malicious local processes**: software running as the user can
  obtain the token just as their browser can.
- Requests, speech text, synthesis concurrency and worker resources are bounded.
  Speech passes text on stdin to a fixed local executable without shell parsing.
  No terminal-command or arbitrary-URL execution route exists.
- The Windows server applies CSP and other browser security headers. Displayed
  terminal, feed and log text must not be treated as HTML.

### Data collection and permissions

Local CPU, memory, disk, adapter, process and connection-count data is collected
read-only. Process summaries contain bounded names and resource use, not command
lines, environment variables, usernames or credentials. Aggregate connection
metrics are not packet capture or remote endpoint intelligence.

Windows services and Defender/firewall status are best-effort read-only probes,
not enforcement. Access denied or unsupported data is unavailable; WOPR does not
elevate, change security settings, install drivers, open ports, scan networks,
submit samples or contact suspect hosts. No Azure authentication, token-cache
inspection or automatic cloud-account query occurs.

The helper is an offline reference. It cannot execute pasted commands. Users
must independently review any examples before running them in a real terminal,
particularly cloud actions that could change resources or cost money. Do not
paste secrets into the helper; terminal text remains visible in that tab.

### Outbound requests and preferences

Public feeds are opt-in. Only fixed HTTPS public-data endpoints are fetched,
with size/time limits, independent caching and backoff. No local measurements
or identifiers are included. As with ordinary HTTPS, feed operators can see the
request's public source IP and standard request metadata.

Sources are SANS ISC, CISA, NOAA SWPC and USGS. Their failure or staleness is
displayed separately from local telemetry. A public cyber alert is not a
machine-health diagnosis. No local-IP reputation lookup or geolocation request
is performed.

Portable speech is local eSpeak NG. A browser speech fallback must select only
voices marked local, with visible feedback if none are available. A browser or
OS voice implementation's behavior is outside WOPR's control; bundled eSpeak is
the fully local preferred path.

The Windows page does not require remote fonts, scripts or analytics. Per-user
feed consent is stored outside served assets; browser appearance/voice/privacy
preferences use localStorage. Local telemetry is not intentionally persisted or
uploaded. Privacy mode masks identifiers on the display; it does not remove data
from a same-user process or its authorized local API. Browser/site preferences
are origin-specific, so a changed random port may start a fresh browser
preference set.

### Distribution

Builds pin dependencies and verify upstream speech source checksums. Speech
sources, build instructions and third-party notices accompany portable
packages. Unsigned builds may be blocked by SmartScreen or corporate policy;
do not disable security controls or bypass organizational restrictions.

Closing a browser tab does not stop the server. Use shutdown or Ctrl+C in its
console. Stop it before deleting the portable folder. Windows launchers do not
change execution policy or create startup tasks.

## Raspberry Pi/Nginx edition

The Pi deployment has a different trust model: Nginx may listen on the LAN, and
there is **no built-in authentication**. Anyone who can reach it can view its
stats and use its CGI speech endpoint. Keep it on trusted networks; use firewall
rules, TLS and authentication before exposing it more widely. Windows runtime
Host/token/CSP controls do not automatically apply to the existing Pi CGI.

`src/wopr-stats.sh` runs as root via systemd, reads `/proc`, sensors, service
state and log excerpts, and writes JSON under the web root. Those excerpts may
contain hostnames, addresses and failed-login details. Review it before
installation. It does not accept user commands or alter firewall/service
configuration during collection.

`src/wopr-speak.cgi` runs through fcgiwrap, not as root. It accepts bounded text
and produces WAV output using eSpeak NG. It is not a general command endpoint,
but concurrent use can consume CPU; add Nginx rate limits/authentication when
appropriate.

The dashboard stores voice/display preferences in localStorage. The cyber-map
arcs are simulation. Pi logs and actual failed-SSH records are distinct from
those effects.

## Verification and reporting

Run the unit suite and HTTP/security tests, and the Windows packaged smoke test
before distributing artifacts. Test cross-site/Host rejection, missing tokens,
unavailable sensors, injection text, feed failures, offline voice and shutdown.
Windows executable/browser testing is required; passing Linux tests alone does
not establish Windows compatibility.

Report security problems privately through the repository host's security
reporting facility when available or contact the maintainer privately. Do not
include credentials, private logs or exploit details in a public issue.
