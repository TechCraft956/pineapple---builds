#!/usr/bin/env bash
# Run the Decision Engine pipeline end to end in this workspace:
# intake -> scanner -> engine -> (feed writer needs FEED_URL/FEED_API_TOKEN).
set -e
cd "$(dirname "$0")/.."
python3 context_intake.py
python3 source_scanner.py
python3 decision_engine.py
echo ""
echo "Feed writer (needs a running feed service + token):"
echo "  FEED_URL=http://127.0.0.1:8100 FEED_API_TOKEN=<token> \\"
echo "    python3 writers/decision_brief_writer.py decision_brief.json"
