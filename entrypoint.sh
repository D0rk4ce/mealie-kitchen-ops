#!/bin/sh

# Default to Tagger if not specified
SCRIPT=${SCRIPT_TO_RUN:-parser}
DATABASE=${DB_TYPE:-sqlite}
VERSION="1.0.0"

# --- Help Flag ---
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "KitchenOps v${VERSION} — Automation Suite for Mealie"
    echo ""
    echo "Usage: Set the SCRIPT_TO_RUN environment variable to choose a tool."
    echo ""
    echo "  SCRIPT_TO_RUN=tagger   Auto-tag recipes by cuisine, protein, etc. (DB)"
    echo "  SCRIPT_TO_RUN=parser   Fix unparsed ingredients via NLP (API)"
    echo "  SCRIPT_TO_RUN=cleaner  Remove junk / broken recipes (API)"
    echo "  SCRIPT_TO_RUN=all      Run Tagger → Cleaner → Parser in sequence"
    echo ""
    echo "Common Environment Variables:"
    echo "  DRY_RUN=true           Simulate changes without writing (default: true)"
    echo "  DB_TYPE=sqlite         Database backend: sqlite or postgres"
    echo "  MEALIE_URL             Your Mealie instance URL"
    echo "  MEALIE_API_TOKEN       API token from Mealie User Profile"
    echo ""
    echo "For the full list, see: https://github.com/D0rk4ce/mealie-kitchen-ops"
    exit 0
fi

if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "KitchenOps v${VERSION}"
    exit 0
fi

echo "========================================"
echo "  KITCHENOPS LAUNCHER v${VERSION}"
echo "========================================"
echo "  Script : $SCRIPT"
echo "  DB     : $DATABASE"
echo "  Dry Run: ${DRY_RUN:-true}"
echo "========================================"

# SAFETY LOCK: Prevent SQLite tagging on a live DB
if [ "$DATABASE" = "sqlite" ] && ([ "$SCRIPT" = "tagger" ] || [ "$SCRIPT" = "all" ]); then
    echo ""
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
    echo "Running Full Suite (Sequence: Tagger → Cleaner → Parser)..."
    python3 kitchen_ops_tagger.py
    python3 kitchen_ops_cleaner.py
    python3 kitchen_ops_parser.py
    ;;
  *)
    echo "❌ Unknown script: $SCRIPT"
    echo ""
    echo "Available options: tagger, parser, cleaner, all"
    echo "Run with --help for more info."
    exit 1
    ;;
esac

echo ""
echo "--- Operation Complete. Container Exiting. ---"
