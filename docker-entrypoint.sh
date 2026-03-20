#!/bin/sh
set -eu

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

: "${MCP_TRANSPORT:=http}"
: "${MCP_HOST:=0.0.0.0}"
: "${MCP_PORT:=8000}"
: "${MCP_PATH:=}"

set -- python mcp_server.py --transport "$MCP_TRANSPORT" --host "$MCP_HOST" --port "$MCP_PORT"
if [ -n "$MCP_PATH" ]; then
  set -- "$@" --path "$MCP_PATH"
fi

exec "$@"
