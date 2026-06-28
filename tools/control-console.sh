#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTROL_DIR="$ROOT_DIR/.control"
API_PID_FILE="$CONTROL_DIR/control-api.pid"
UI_PID_FILE="$CONTROL_DIR/control-ui.pid"
LANGGRAPH_PID_FILE="$CONTROL_DIR/langgraph-dev.pid"
API_LOG_FILE="$CONTROL_DIR/control-api.log"
UI_LOG_FILE="$CONTROL_DIR/control-ui.log"
LANGGRAPH_LOG_FILE="$CONTROL_DIR/langgraph-dev.log"

ACTION="${1:-}"
if [[ -z "$ACTION" ]]; then
  ACTION="status"
else
  shift
fi

API_HOST="127.0.0.1"
API_PORT="8765"
UI_HOST="127.0.0.1"
UI_PORT="5173"
LANGGRAPH_HOST="127.0.0.1"
LANGGRAPH_PORT="2024"

usage() {
  cat <<'EOF'
Usage:
  tools/control-console.sh start [options]
  tools/control-console.sh stop [options]
  tools/control-console.sh restart [options]
  tools/control-console.sh status

Options:
  --api-host HOST         Control API host. Default: 127.0.0.1
  --api-port PORT         Control API port. Default: 8765
  --ui-host HOST          Web UI host. Default: 127.0.0.1
  --ui-port PORT          Web UI port. Default: 5173
  --langgraph-host HOST   LangGraph dev host. Default: 127.0.0.1
  --langgraph-port PORT   LangGraph dev port. Default: 2024
  -h, --help              Show this help.

Examples:
  tools/control-console.sh start
  tools/control-console.sh restart --api-port 8766 --ui-port 5174
  tools/control-console.sh stop
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-host)
      API_HOST="${2:?missing value for --api-host}"
      shift 2
      ;;
    --api-port)
      API_PORT="${2:?missing value for --api-port}"
      shift 2
      ;;
    --ui-host)
      UI_HOST="${2:?missing value for --ui-host}"
      shift 2
      ;;
    --ui-port)
      UI_PORT="${2:?missing value for --ui-port}"
      shift 2
      ;;
    --langgraph-host)
      LANGGRAPH_HOST="${2:?missing value for --langgraph-host}"
      shift 2
      ;;
    --langgraph-port)
      LANGGRAPH_PORT="${2:?missing value for --langgraph-port}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$CONTROL_DIR"

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

listening_pid() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true
}

pid_command() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null || true
}

command_matches() {
  local pid="$1"
  local expected="$2"
  local command
  command="$(pid_command "$pid")"
  [[ "$command" == *"$expected"* ]]
}

pid_value() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && cat "$pid_file" || true
}

start_process() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  local work_dir="$4"
  local port="$5"
  shift 5

  if is_running "$pid_file"; then
    echo "$name already running: PID $(pid_value "$pid_file")"
    return
  fi

  rm -f "$pid_file"
  local existing_pid
  existing_pid="$(listening_pid "$port")"
  if [[ -n "$existing_pid" ]]; then
    echo "$name already listening on port $port: PID $existing_pid"
    echo "$name command: $(pid_command "$existing_pid")"
    return
  fi

  "$ROOT_DIR/.venv/bin/python3" - "$work_dir" "$log_file" "$pid_file" "$@" <<'PY'
import subprocess
import sys
from pathlib import Path

work_dir, log_file, pid_file, *command = sys.argv[1:]
Path(log_file).parent.mkdir(parents=True, exist_ok=True)
log = open(log_file, "ab", buffering=0)
process = subprocess.Popen(
    command,
    cwd=work_dir,
    stdout=log,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    start_new_session=True,
)
Path(pid_file).write_text(str(process.pid), encoding="utf-8")
PY
  echo "$name started: PID $(pid_value "$pid_file")"
  echo "$name log: $log_file"
}

stop_process() {
  local name="$1"
  local pid_file="$2"
  local port="$3"
  local expected_command="$4"
  local pid=""

  if ! is_running "$pid_file"; then
    rm -f "$pid_file"
    pid="$(listening_pid "$port")"
    if [[ -z "$pid" ]]; then
      echo "$name not running"
      return
    fi
    if ! command_matches "$pid" "$expected_command"; then
      echo "$name port $port is used by another process, not stopping: PID $pid"
      echo "$name command: $(pid_command "$pid")"
      return
    fi
  else
    pid="$(cat "$pid_file")"
  fi

  kill "$pid" 2>/dev/null || true
  for _ in {1..30}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "$name stopped"
      return
    fi
    sleep 0.2
  done

  kill -9 "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  echo "$name killed"
}

status_process() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  local port="$4"
  if is_running "$pid_file"; then
    echo "$name: running, PID $(pid_value "$pid_file"), log $log_file"
    return
  fi

  local existing_pid
  existing_pid="$(listening_pid "$port")"
  if [[ -n "$existing_pid" ]]; then
    echo "$name: running on port $port, PID $existing_pid, not managed by pid file"
    echo "$name command: $(pid_command "$existing_pid")"
    return
  fi

  echo "$name: stopped"
}

start_all() {
  local api_bin="$ROOT_DIR/.venv/bin/productv2"
  local ui_bin="$ROOT_DIR/web/node_modules/.bin/vite"
  local langgraph_bin="$ROOT_DIR/.venv/bin/langgraph"
  if [[ ! -x "$api_bin" ]]; then
    echo "Missing executable: $api_bin. Run uv sync first." >&2
    exit 1
  fi
  if [[ ! -x "$langgraph_bin" ]]; then
    echo "Missing executable: $langgraph_bin. Run uv sync --group dev first." >&2
    exit 1
  fi
  if [[ ! -x "$ui_bin" ]]; then
    echo "Missing executable: $ui_bin. Run npm install in web/ first." >&2
    exit 1
  fi

  start_process \
    "langgraph-dev" \
    "$LANGGRAPH_PID_FILE" \
    "$LANGGRAPH_LOG_FILE" \
    "$ROOT_DIR" \
    "$LANGGRAPH_PORT" \
    "$langgraph_bin" dev --host "$LANGGRAPH_HOST" --port "$LANGGRAPH_PORT" --allow-blocking --no-browser

  start_process \
    "control-api" \
    "$API_PID_FILE" \
    "$API_LOG_FILE" \
    "$ROOT_DIR" \
    "$API_PORT" \
    "$api_bin" control-api --host "$API_HOST" --port "$API_PORT"

  start_process \
    "control-ui" \
    "$UI_PID_FILE" \
    "$UI_LOG_FILE" \
    "$ROOT_DIR/web" \
    "$UI_PORT" \
    "$ui_bin" --host "$UI_HOST" --port "$UI_PORT"

  echo "LangGraph API: http://$LANGGRAPH_HOST:$LANGGRAPH_PORT"
  echo "Control API: http://$API_HOST:$API_PORT"
  echo "Web UI:      http://$UI_HOST:$UI_PORT"
}

stop_all() {
  stop_process "control-ui" "$UI_PID_FILE" "$UI_PORT" "vite"
  stop_process "control-api" "$API_PID_FILE" "$API_PORT" "productv2 control-api"
  stop_process "langgraph-dev" "$LANGGRAPH_PID_FILE" "$LANGGRAPH_PORT" "langgraph dev"
}

status_all() {
  status_process "langgraph-dev" "$LANGGRAPH_PID_FILE" "$LANGGRAPH_LOG_FILE" "$LANGGRAPH_PORT"
  status_process "control-api" "$API_PID_FILE" "$API_LOG_FILE" "$API_PORT"
  status_process "control-ui" "$UI_PID_FILE" "$UI_LOG_FILE" "$UI_PORT"
}

case "$ACTION" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_all
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    usage >&2
    exit 2
    ;;
esac
