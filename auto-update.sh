#!/bin/bash
# Auto-update script for ai_class_chatgame
# Called by cron to check for GitHub updates

PROJECT_DIR="/opt/ai_class_chatgame"
CONTAINER_NAME="ai-class-chatgame"
IMAGE_NAME="ai-class-chatgame:latest"
LOG_FILE="/var/log/ai-chatgame-update.log"
ENV_FILE="${PROJECT_DIR}/.env"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking for updates..." >> "$LOG_FILE"

cd "$PROJECT_DIR" || exit 1

# Save current HEAD
CURRENT_HASH=$(git rev-parse HEAD)

# Fetch latest
git fetch origin main 2>&1 >> "$LOG_FILE"

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    echo "  No updates found." >> "$LOG_FILE"
    exit 0
fi

echo "  Update detected: $LOCAL_HASH -> $REMOTE_HASH" >> "$LOG_FILE"

# Pull latest code
git pull origin main 2>&1 >> "$LOG_FILE"

# Build new image
docker build -t "$IMAGE_NAME" "$PROJECT_DIR" 2>&1 >> "$LOG_FILE"
BUILD_EXIT=$?
if [ $BUILD_EXIT -ne 0 ]; then
    echo "  Build FAILED (exit $BUILD_EXIT), aborting redeploy." >> "$LOG_FILE"
    exit 1
fi

# Stop and remove old container
docker rm -f "$CONTAINER_NAME" 2>> "$LOG_FILE" || true

# Start new container
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --env-file "$ENV_FILE" \
    -p 80:8080 \
    "$IMAGE_NAME" 2>&1 >> "$LOG_FILE"

# Verify
sleep 2
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/healthz 2>/dev/null)
echo "  Health check: $HEALTH" >> "$LOG_FILE"
echo "  Update complete." >> "$LOG_FILE"
