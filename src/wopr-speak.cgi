#!/bin/bash
# ============================================================
# WOPR JOSHUA Voice Synthesis — CGI endpoint
# Served by nginx via fcgiwrap at /api/speak
#
# Request:  GET /api/speak?text=<urlencoded text>
# Response: audio/wav speech of the text, synthesized with espeak-ng
#           (the same WOPR/WarGames-style robotic voice PiAI uses)
# ============================================================

urldecode() {
    local data="${1//+/ }"
    printf '%b' "${data//%/\\x}"
}

TEXT=""
IFS='&' read -ra PARAMS <<< "${QUERY_STRING:-}"
for p in "${PARAMS[@]}"; do
    case "$p" in
        text=*) TEXT=$(urldecode "${p#text=}") ;;
    esac
done

# Keep only printable/whitespace characters and cap length to avoid abuse
TEXT=$(printf '%s' "$TEXT" | tr -cd '[:print:][:space:]' | cut -c1-500)

if [ -z "$TEXT" ] || ! command -v espeak-ng &>/dev/null; then
    printf 'Status: 400 Bad Request\r\n'
    printf 'Content-Type: text/plain\r\n'
    printf '\r\n'
    printf 'missing text parameter or espeak-ng unavailable\n'
    exit 0
fi

printf 'Content-Type: audio/wav\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'

# "--" guards against $TEXT being interpreted as an espeak-ng option
espeak-ng -v en -s 175 --stdout -- "$TEXT"
