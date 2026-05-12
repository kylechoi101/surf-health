#!/usr/bin/env bash
# Run tomorrow at 14:00 PST to refresh beach card photos with Surfline cam stills
# and ship a new EAS production build with the cleaner pictures.
#
# This script:
#  1. Fetches a Surfline cam still for every parent beach that has one within 5km
#  2. Commits the bundled photos + manifest
#  3. Pushes to main (triggers Vercel/Render auto-redeploy of web/backend, irrelevant for mobile)
#  4. Triggers EAS production build (iOS + Android, cloud)
#  5. After build finishes, submits both to App Store Connect / Play Console
#
# Manual usage:
#   bash scripts/v1_1_photo_release.sh
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/v1_1_photo_release_$(date +%Y%m%d_%H%M%S).log"

echo "[$(date)] start" | tee -a "$LOG"

# Step 1: fetch public-domain photos from Wikimedia Commons
backend/.venv/bin/python scripts/fetch_beach_photos_commons.py 2>&1 | tee -a "$LOG"

# Step 2 + 3: commit + push
git add mobile/assets/beach-photos-cams/ mobile/lib/bundledBeachPhotos.ts mobile/lib/beachPhotoAttributions.ts
if git diff --staged --quiet; then
  echo "[$(date)] no photo changes — skipping commit" | tee -a "$LOG"
else
  git commit -m "feat(mobile): bundle Wikimedia Commons beach photos for v1.1

Auto-fetched on $(date -u +%Y-%m-%dT%H:%MZ) via fetch_beach_photos_commons.py.
All photos sourced from Wikimedia Commons under CC / public-domain licenses;
per-image author + license metadata in beachPhotoAttributions.ts is displayed
as the attribution overlay on each card." 2>&1 | tee -a "$LOG"
  git push origin main 2>&1 | tee -a "$LOG"
fi

# Step 4: trigger EAS build
cd mobile
npx eas build --platform all --profile production --non-interactive 2>&1 | tee -a "$LOG"

# Step 5: poll for completion then submit
echo "[$(date)] waiting for builds…" | tee -a "$LOG"
for i in $(seq 1 60); do
  status=$(npx eas build:list --limit 2 --json 2>/dev/null | python3 -c "
import json, sys, re
m = re.search(r'\[.*\]', sys.stdin.read(), re.DOTALL)
data = json.loads(m.group(0)) if m else []
done = sum(1 for b in data[:2] if b.get('status') == 'FINISHED')
fail = sum(1 for b in data[:2] if b.get('status') in ('ERRORED','CANCELED'))
print(f'done={done} fail={fail}')
" 2>/dev/null)
  echo "[$(date)] poll $i: $status" | tee -a "$LOG"
  if echo "$status" | grep -q "fail=[12]"; then
    echo "[$(date)] build failed; aborting submit" | tee -a "$LOG"
    exit 1
  fi
  if echo "$status" | grep -q "done=2"; then
    echo "[$(date)] both builds finished" | tee -a "$LOG"
    break
  fi
  sleep 60
done

npx eas submit --platform all --profile production --latest --non-interactive 2>&1 | tee -a "$LOG"

echo "[$(date)] done — check App Store Connect + Play Console" | tee -a "$LOG"
