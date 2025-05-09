#!/bin/bash

# Default API URL (change if deployed)
API_URL="https://agent-backend-production-b7ed.up.railway.app:4242/onboard-agent-chat"

# Prompt user for input
read -p "💬 Ask the agent: " user_input

# Make the request and extract the message
curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"$user_input\"}" \
  | jq -r '.message'
