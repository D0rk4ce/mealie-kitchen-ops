#!/bin/sh

# Default to Tagger if not specified
SCRIPT=${SCRIPT_TO_RUN:-tagger}
DATABASE=${DB_TYPE:-sqlite}

echo "--- KITCHENOPS LAUNCHER ---"
echo "Mode: $SCRIPT | DB: $DATABASE"

# SAFETY LOCK: Prevent SQLite tagging on a live DB
if [ "$DATABASE" = "sqlite" ] && ([ "$SCRIPT" = "tagger" ] || [ "$SCRIPT" = "all" ]); then
    echo "❗ SAFETY ALERT: SQLite detected."
    echo "The Tagger requires a direct database lock and cannot run on a live Mealie instance."
    echo "Please ensure you have STOPPED your Mealie container before proceeding."
    echo ""
    read -p "Have you stopped Mealie? (y/N): " confirmed
    if [ "$confirmed" != "y" ] && [ "$confirmed" != "Y" ]; then
        echo "❌ Operation cancelled by user. Prevented potential corruption."
        exit 1
    fi
fi

case "$SCRIPT" in
  "tagger")
    echo "Starting Auto-Tagger..."
    python3 kitchen_ops_tagger.py
    ;;
  "parser")
    echo "Starting Batch Parser..."
    python3 kitchen_ops_parser.py
    ;;
  "cleaner")
    echo "Starting Library Cleaner..."
    python3 kitchen_ops_cleaner.py
    ;;
  "all")
    echo "Running Full Suite (Sequence: Tagger -> Cleaner -> Parser)..."
    python3 kitchen_ops_tagger.py
    python3 kitchen_ops_cleaner.py
    python3 kitchen_ops_parser.py
    ;;
  *)
    echo "Unknown script: $SCRIPT"
    echo "Available options: tagger, parser, cleaner, all"
    exit 1
    ;;
esac

echo "--- Operation Complete. Container Exiting. ---"
