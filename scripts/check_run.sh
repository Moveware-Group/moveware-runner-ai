#!/bin/bash
# Quick script to check the most recent run
RUN_ID=${1:-$(sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 "SELECT id FROM runs ORDER BY id DESC LIMIT 1;")}

echo "=== Run #$RUN_ID Details ==="
echo ""
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 <<EOF
.mode column
.headers on
SELECT 
  id,
  issue_key,
  status,
  branch,
  pr_url,
  datetime(created_at, 'unixepoch', 'localtime') as created,
  datetime(updated_at, 'unixepoch', 'localtime') as updated
FROM runs WHERE id = $RUN_ID;
EOF

echo ""
echo "=== Event Timeline ==="
echo ""
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 <<EOF
.mode column
.headers on
SELECT 
  datetime(ts, 'unixepoch', 'localtime') as timestamp,
  level,
  message
FROM events 
WHERE run_id = $RUN_ID
ORDER BY ts;
EOF
