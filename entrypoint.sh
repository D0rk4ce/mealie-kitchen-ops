#!/bin/sh

# Default to Tagger if not specified
SCRIPT=${SCRIPT_TO_RUN:-tagger}

echo "--- KITCHENOPS LAUNCHER ---"
echo "Target: $SCRIPT"

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
