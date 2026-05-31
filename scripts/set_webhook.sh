#!/usr/bin/env sh
# scripts/set_webhook.sh
#
# Manually re-register the Telegram webhook against the currently running
# ngrok tunnel. Run this if the webhook-setter container already exited and
# you need to re-point Telegram (e.g. after a compose restart without --build).
#
# Usage:
#   chmod +x scripts/set_webhook.sh
#   ./scripts/set_webhook.sh
#
# Requires: curl, jq
# Reads: TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from .env

set -e

# Load .env from repo root
ENV_FILE="$(dirname "$0")/../.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE"
  exit 1
fi
# shellcheck disable=SC1090
. "$ENV_FILE"

echo "Querying ngrok for public URL..."
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url // empty')

if [ -z "$NGROK_URL" ]; then
  echo "ERROR: Could not get ngrok URL. Is ngrok running? (docker compose up OR ngrok http 8000)"
  exit 1
fi

WEBHOOK_URL="${NGROK_URL}/telegram/webhook"
echo "ngrok tunnel : $NGROK_URL"
echo "Webhook URL  : $WEBHOOK_URL"

RESPONSE=$(curl -s -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"${WEBHOOK_URL}\", \"secret_token\": \"${TELEGRAM_WEBHOOK_SECRET}\"}")

echo "Telegram response: $RESPONSE"
echo "$RESPONSE" | jq -e '.ok == true' > /dev/null && echo "Webhook registered!" || echo "WARNING: Telegram returned an error."
