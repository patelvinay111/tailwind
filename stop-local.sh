#!/usr/bin/env bash
# Stop the local app + Cloudflare tunnel started by start-local.sh.
pkill -f "uvicorn main:app" 2>/dev/null && echo "✓ stopped app" || echo "app not running"
pkill -f "cloudflared tunnel" 2>/dev/null && echo "✓ stopped tunnel" || echo "tunnel not running"
