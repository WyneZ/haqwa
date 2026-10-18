#!/usr/bin/env bash
# Usage: ./smoke_preview.sh https://preview---haqwa-1020226488566.asia-southeast1.run.app
set -u
U="${1:?pass the service URL}"
ok=0; fail=0
check() { if eval "$2"; then echo "PASS  $1"; ok=$((ok+1)); else echo "FAIL  $1"; fail=$((fail+1)); fi; }
check "GET /api/v1/scenarios is 200" '[ "$(curl -s -o /dev/null -w "%{http_code}" "$U/api/v1/scenarios")" = 200 ]'
check "scenarios JSON is non-empty" 'curl -s "$U/api/v1/scenarios" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d else 1)"'
check "SPA index is served" 'curl -s "$U/" | grep -q "<div id=\"root\""'
JS=$(curl -s "$U/" | grep -o "assets/index-[^\"]*\.js" | head -1)
check "frontend bundle loads" '[ -n "$JS" ] && [ "$(curl -s -o /dev/null -w "%{http_code}" "$U/$JS")" = 200 ]'
echo "---- $ok passed, $fail failed"
[ "$fail" = 0 ]
