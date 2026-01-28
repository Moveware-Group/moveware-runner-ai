#!/bin/bash
# Monitor script for Moveware AI Worker
# Usage: ./monitor_worker.sh

echo "=== Moveware AI Worker Monitor ==="
echo ""
echo "Recent Runs:"
echo "============"
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 "
SELECT 
  printf('Run #%d: %s [%s]', id, issue_key, status) as run_info,
  datetime(created_at, 'unixepoch', 'localtime') as created
FROM runs 
ORDER BY id DESC 
LIMIT 5;
" -header -column

echo ""
echo "Worker Status:"
echo "=============="
systemctl status moveware-ai-worker.service --no-pager -l | grep -E "Active:|Main PID:"

echo ""
echo "Recent Logs (last 20 lines):"
echo "============================"
sudo journalctl -u moveware-ai-worker.service -n 20 --no-pager

echo ""
echo "=== Live Log Tail (Ctrl+C to exit) ==="
sudo journalctl -u moveware-ai-worker.service -f
