#!/usr/bin/env bash
echo "--- redis processes ---"
pgrep -af redis-server || echo "(none)"
echo "--- listening ports relevant to bench ---"
ss -tlnp 2>/dev/null | grep -E ':(11000|13000|6379|8000|9000)'
