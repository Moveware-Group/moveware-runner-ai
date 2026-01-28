#!/bin/bash
# Check detailed status of a specific run
# Usage: ./check_run_status.sh <run_id>

if [ -z "$1" ]; then
    echo "Usage: $0 <run_id>"
    echo ""
    echo "Recent runs:"
    sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 "
    SELECT id, issue_key, status 
    FROM runs 
    ORDER BY id DESC 
    LIMIT 10;
    " -header -column
    exit 1
fi

RUN_ID=$1
DB_PATH="/srv/ai/state/moveware_ai.sqlite3"

echo "=== Run #$RUN_ID Details ==="
echo ""

# Run info
sudo sqlite3 $DB_PATH "
SELECT 
  'Run ID:' as field, id as value
  FROM runs WHERE id = $RUN_ID
UNION ALL
SELECT 'Issue Key:', issue_key FROM runs WHERE id = $RUN_ID
UNION ALL
SELECT 'Status:', status FROM runs WHERE id = $RUN_ID
UNION ALL
SELECT 'Attempts:', attempts FROM runs WHERE id = $RUN_ID
UNION ALL
SELECT 'Branch:', branch FROM runs WHERE id = $RUN_ID
UNION ALL
SELECT 'PR URL:', pr_url FROM runs WHERE id = $RUN_ID
UNION ALL
SELECT 'Created:', datetime(created_at, 'unixepoch', 'localtime') FROM runs WHERE id = $RUN_ID
UNION ALL
SELECT 'Updated:', datetime(updated_at, 'unixepoch', 'localtime') FROM runs WHERE id = $RUN_ID
UNION ALL
SELECT 'Last Error:', last_error FROM runs WHERE id = $RUN_ID;
" -noheader -column

echo ""
echo "=== Event Timeline ==="
echo ""

sudo sqlite3 $DB_PATH "
SELECT 
  datetime(ts, 'unixepoch', 'localtime') as timestamp,
  printf('[%s]', level) as level,
  message
FROM events 
WHERE run_id = $RUN_ID
ORDER BY ts;
" -header -column

echo ""
echo "=== Event Details (with metadata) ==="
echo ""

sudo sqlite3 $DB_PATH "
SELECT 
  datetime(ts, 'unixepoch', 'localtime') as timestamp,
  level,
  message,
  meta_json
FROM events 
WHERE run_id = $RUN_ID
ORDER BY ts;
" -header -column
