#!/bin/bash
# WOPR SYSTEM INTELLIGENCE GATHERER v2
# Generates real-time Pi5 stats + auth.log attack data as JSON

OUTPUT_DIR="/var/www/html/api"
OUTPUT_FILE="$OUTPUT_DIR/stats.json"
INTERVAL=2

mkdir -p "$OUTPUT_DIR"

while true; do

  HOSTNAME=$(hostname)
  OS=$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2)

  # Uptime
  UPTIME_SEC=$(awk '{print int($1)}' /proc/uptime)
  UPTIME_DAYS=$((UPTIME_SEC / 86400))
  UPTIME_HRS=$(( (UPTIME_SEC % 86400) / 3600 ))
  UPTIME_MIN=$(( (UPTIME_SEC % 3600) / 60 ))
  UPTIME_STR="${UPTIME_DAYS}d ${UPTIME_HRS}h ${UPTIME_MIN}m"

  # CPU temp
  CPU_TEMP_RAW=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
  CPU_TEMP_C=$(echo "scale=1; $CPU_TEMP_RAW / 1000" | bc)

  # CPU freq & cores
  CPU_FREQ_RAW=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || echo 0)
  CPU_FREQ_MHZ=$(( CPU_FREQ_RAW / 1000 ))
  CPU_CORES=$(nproc 2>/dev/null || echo 4)

  # CPU usage - increased sampling window to 0.5s
  read -r CPU_LINE < /proc/stat
  CPU_VALS=($CPU_LINE)
  IDLE1=${CPU_VALS[4]}
  TOTAL1=0
  for v in "${CPU_VALS[@]:1}"; do TOTAL1=$((TOTAL1 + v)); done
  sleep 0.5
  read -r CPU_LINE < /proc/stat
  CPU_VALS=($CPU_LINE)
  IDLE2=${CPU_VALS[4]}
  TOTAL2=0
  for v in "${CPU_VALS[@]:1}"; do TOTAL2=$((TOTAL2 + v)); done
  IDLE_DELTA=$((IDLE2 - IDLE1))
  TOTAL_DELTA=$((TOTAL2 - TOTAL1))
  if [ "$TOTAL_DELTA" -gt 0 ]; then
    CPU_USAGE=$(echo "scale=1; (1 - $IDLE_DELTA / $TOTAL_DELTA) * 100" | bc)
  else
    CPU_USAGE="0.0"
  fi

  LOAD_1=$(awk '{print $1}' /proc/loadavg)
  LOAD_5=$(awk '{print $2}' /proc/loadavg)
  LOAD_15=$(awk '{print $3}' /proc/loadavg)

  # Memory
  MEM_TOTAL=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  MEM_AVAIL=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
  MEM_USED=$((MEM_TOTAL - MEM_AVAIL))
  MEM_PCT=$(echo "scale=1; $MEM_USED * 100 / $MEM_TOTAL" | bc 2>/dev/null || echo "0")

  # Disk
  DISK_INFO=$(df -BG / | tail -1)
  DISK_TOTAL=$(echo "$DISK_INFO" | awk '{gsub("G",""); print $2}')
  DISK_USED=$(echo "$DISK_INFO" | awk '{gsub("G",""); print $3}')
  DISK_FREE=$(echo "$DISK_INFO" | awk '{gsub("G",""); print $4}')
  DISK_PCT=$(echo "$DISK_INFO" | awk '{gsub("%",""); print $5}')

  # Network
  IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
  IFACE=$(ip route 2>/dev/null | awk '/default/ {print $5; exit}')
  if [ -n "$IFACE" ]; then
    RX_BYTES=$(cat /sys/class/net/$IFACE/statistics/rx_bytes 2>/dev/null || echo 0)
    TX_BYTES=$(cat /sys/class/net/$IFACE/statistics/tx_bytes 2>/dev/null || echo 0)
    RX_MB=$(echo "scale=1; $RX_BYTES / 1048576" | bc)
    TX_MB=$(echo "scale=1; $TX_BYTES / 1048576" | bc)
    # Network rate (KB/s) - compare to previous reading
    PREV_RX=$(cat /tmp/wopr_prev_rx 2>/dev/null || echo "$RX_BYTES")
    PREV_TX=$(cat /tmp/wopr_prev_tx 2>/dev/null || echo "$TX_BYTES")
    echo "$RX_BYTES" > /tmp/wopr_prev_rx
    echo "$TX_BYTES" > /tmp/wopr_prev_tx
    RX_RATE=$(echo "scale=1; ($RX_BYTES - $PREV_RX) / $INTERVAL / 1024" | bc 2>/dev/null || echo "0")
    TX_RATE=$(echo "scale=1; ($TX_BYTES - $PREV_TX) / $INTERVAL / 1024" | bc 2>/dev/null || echo "0")
  else
    IFACE="unknown"; RX_MB="0"; TX_MB="0"; RX_RATE="0"; TX_RATE="0"
  fi

  # Active connections
  CONN_COUNT=$(ss -tun state established 2>/dev/null | tail -n +2 | wc -l)

  # Processes
  PROC_COUNT=$(ps aux --no-heading 2>/dev/null | wc -l)

  # Services
  svc_status() { systemctl is-active "$1" 2>/dev/null || echo "inactive"; }
  SVC_NGINX=$(svc_status nginx)
  SVC_SSH=$(svc_status ssh)
  SVC_CRON=$(svc_status cron)
  SVC_DBUS=$(svc_status dbus)
  SVC_NTP=$(svc_status systemd-timesyncd)
  SVC_JOURNAL=$(svc_status systemd-journald)
  SVC_NETWORK=$(svc_status NetworkManager 2>/dev/null || svc_status systemd-networkd 2>/dev/null || echo "active")
  SVC_WOPR=$(svc_status wopr-stats)

  # GPU temp
  GPU_TEMP=$(vcgencmd measure_temp 2>/dev/null | grep -oP '[0-9.]+' || echo "$CPU_TEMP_C")

  # Throttle status
  THROTTLE=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2 || echo "0x0")

  # System log entries - clean parsing, strip problematic chars
  LOG_ENTRIES=""
  while IFS= read -r line; do
    ts=$(echo "$line" | awk '{print $1}')
    # Get message portion after hostname/service, strip quotes and backslashes
    msg=$(echo "$line" | cut -d' ' -f5- | tr -d '"\\\t' | cut -c1-100)
    [ -z "$msg" ] && continue
    [ -n "$LOG_ENTRIES" ] && LOG_ENTRIES="${LOG_ENTRIES},"
    LOG_ENTRIES="${LOG_ENTRIES}{\"time\":\"${ts}\",\"msg\":\"${msg}\"}"
  done < <(journalctl --no-pager -n 15 -o short-iso -p 6 2>/dev/null | grep -v "^--" | tail -15)

  # Auth failures (real attacks!) - parse failed SSH logins
  AUTH_ENTRIES=""
  if [ -r /var/log/auth.log ]; then
    while IFS= read -r line; do
      ts=$(echo "$line" | awk '{print $1" "$2" "$3}')
      user=$(echo "$line" | grep -oP 'for (?:invalid user )?\K\w+' || echo "unknown")
      ip=$(echo "$line" | grep -oP 'from \K[0-9.]+' || echo "0.0.0.0")
      port=$(echo "$line" | grep -oP 'port \K[0-9]+' || echo "0")
      [ -n "$AUTH_ENTRIES" ] && AUTH_ENTRIES="${AUTH_ENTRIES},"
      AUTH_ENTRIES="${AUTH_ENTRIES}{\"time\":\"${ts}\",\"user\":\"${user}\",\"ip\":\"${ip}\",\"port\":\"${port}\"}"
    done < <(grep "Failed password" /var/log/auth.log 2>/dev/null | tail -20)
  fi

  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  cat > "${OUTPUT_FILE}.tmp" << ENDJSON
{
  "hostname": "$HOSTNAME",
  "os": "$OS",
  "timestamp": "$TIMESTAMP",
  "uptime": "$UPTIME_STR",
  "uptime_seconds": $UPTIME_SEC,
  "cpu": {
    "usage_percent": $CPU_USAGE,
    "temp_c": $CPU_TEMP_C,
    "gpu_temp_c": $GPU_TEMP,
    "freq_mhz": $CPU_FREQ_MHZ,
    "cores": $CPU_CORES,
    "load_1m": $LOAD_1,
    "load_5m": $LOAD_5,
    "load_15m": $LOAD_15,
    "throttled": "$THROTTLE"
  },
  "memory": {
    "total_mb": $MEM_TOTAL,
    "used_mb": $MEM_USED,
    "available_mb": $MEM_AVAIL,
    "percent": $MEM_PCT
  },
  "disk": {
    "total_gb": $DISK_TOTAL,
    "used_gb": $DISK_USED,
    "free_gb": $DISK_FREE,
    "percent": $DISK_PCT
  },
  "network": {
    "ip": "$IP_ADDR",
    "interface": "$IFACE",
    "rx_mb": $RX_MB,
    "tx_mb": $TX_MB,
    "rx_rate_kbs": $RX_RATE,
    "tx_rate_kbs": $TX_RATE,
    "connections": $CONN_COUNT
  },
  "processes": $PROC_COUNT,
  "services": {
    "nginx": "$SVC_NGINX",
    "ssh": "$SVC_SSH",
    "cron": "$SVC_CRON",
    "dbus": "$SVC_DBUS",
    "ntp": "$SVC_NTP",
    "journald": "$SVC_JOURNAL",
    "network": "$SVC_NETWORK",
    "wopr_stats": "$SVC_WOPR"
  },
  "log_entries": [$LOG_ENTRIES],
  "auth_failures": [$AUTH_ENTRIES]
}
ENDJSON

  mv "${OUTPUT_FILE}.tmp" "$OUTPUT_FILE"
  sleep $INTERVAL
done
