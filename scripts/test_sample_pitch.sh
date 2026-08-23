#!/bin/bash
# Test the sample pitch through the Virtual Judge pipeline

set -e

JUDGE_URL="${JUDGE_URL:-http://localhost:8000}"
# Supply your own recording. Nothing ships with the repo: audio_recordings/ is
# gitignored because it holds real people pitching.
#   PITCH_AUDIO=/path/to/pitch.mp3 ./scripts/test_sample_pitch.sh
PITCH_AUDIO="${PITCH_AUDIO:-audio_recordings/sample_pitch.mp3}"

echo "🎙️  Virtual Judge — Sample Pitch Test"
echo "======================================"
echo ""

# Check if server is running
echo "Checking server health..."
HEALTH=$(curl -s "$JUDGE_URL/api/health")
if [[ $? -ne 0 ]]; then
    echo "❌ Virtual Judge server not running. Start with: npm run dev"
    exit 1
fi
echo "✓ Server is up"
echo ""

# Get available rubrics
echo "Available rubrics:"
curl -s "$JUDGE_URL/api/rubrics" | grep -o '"name":"[^"]*"' | head -3
echo ""

# Create an event
echo "Creating test event..."
EVENT=$(curl -s -X POST "$JUDGE_URL/api/events" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sample Pitch Test",
    "description": "Testing with the ContextCraft sample pitch"
  }')
EVENT_ID=$(echo $EVENT | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
echo "✓ Event created: $EVENT_ID"
echo ""

# Create a submission
echo "Creating submission for ContextCraft..."
SUB=$(curl -s -X POST "$JUDGE_URL/api/submissions" \
  -H "Content-Type: application/json" \
  -d "{
    \"team_name\": \"ContextCraft\",
    \"event_id\": \"$EVENT_ID\"
  }")
SUB_ID=$(echo $SUB | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
echo "✓ Submission created: $SUB_ID"
echo ""

# Upload the pitch audio
echo "Uploading pitch audio..."
if [[ ! -f "$PITCH_AUDIO" ]]; then
    echo "❌ Audio file not found at $PITCH_AUDIO"
    echo ""
    echo "   No sample audio ships with this repo. Record a short pitch, drop it"
    echo "   anywhere, and point the script at it:"
    echo ""
    echo "     PITCH_AUDIO=/path/to/pitch.mp3 ./scripts/test_sample_pitch.sh"
    exit 1
fi

curl -s -X POST "$JUDGE_URL/api/submissions/$SUB_ID/audio" \
  -F "audio=@$PITCH_AUDIO" > /dev/null
echo "✓ Audio uploaded"
echo ""

# Run the judging pipeline
echo "Running judging pipeline (transcribe → score → speak)..."
echo "⏳ This takes ~30 seconds..."
echo ""

RESULT=$(curl -s -X POST "$JUDGE_URL/api/submissions/$SUB_ID/judge")

# Parse and display results
SCORE=$(echo $RESULT | grep -o '"overall_score":[0-9.]*' | cut -d':' -f2)
echo "Results:"
echo "--------"
echo "Overall Score: $SCORE"
echo ""

# Show category scores
echo "Scores by category:"
echo $RESULT | grep -o '"[^"]*":\s*[0-9]*' | grep -v 'id\|event\|submission' | head -10
echo ""

echo "✓ Pitch judged successfully!"
echo ""
echo "Next steps:"
echo "  - Visit http://localhost:8000 to see the full review"
echo "  - Try uploading other pitches to the same event"
echo "  - Run: curl -X POST http://localhost:8000/api/events/$EVENT_ID/finalist to find top 3"
