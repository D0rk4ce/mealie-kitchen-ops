#!/bin/sh

DATABASE=${DB_TYPE:-sqlite}
VERSION="1.0.0"
ENV_FILE="/app/config/.env"

# --- Help / Version Flags ---
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "KitchenOps v${VERSION} — Automation Suite for Mealie"
    echo ""
    echo "Usage: Set the SCRIPT_TO_RUN environment variable to choose a tool,"
    echo "       or run interactively to get a selection menu."
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
    echo "Tip: On first run with 'docker run -it', KitchenOps will walk you through"
    echo "     setup and save your settings to config/.env for next time."
    echo ""
    echo "For the full list, see: https://github.com/D0rk4ce/mealie-kitchen-ops"
    exit 0
fi

if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "KitchenOps v${VERSION}"
    exit 0
fi

# --- Load saved env if it exists (only fill in blanks) ---
if [ -f "$ENV_FILE" ]; then
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        case "$key" in
            \#*|"") continue ;;
        esac
        # Only set if not already in environment
        eval "current=\$$key"
        if [ -z "$current" ]; then
            export "$key=$value"
        fi
    done < "$ENV_FILE"
fi

echo "========================================"
echo "  KITCHENOPS LAUNCHER v${VERSION}"
echo "========================================"

# --- Script Selection ---
if [ -n "$SCRIPT_TO_RUN" ]; then
    SCRIPT="$SCRIPT_TO_RUN"
elif [ -t 0 ]; then
    # Interactive terminal — show selection menu
    echo ""
    echo "  Select a tool to run:"
    echo ""
    echo "    1) 🔧 Batch Parser    Fix unparsed ingredients (API, safe)"
    echo "    2) 🧹 Library Cleaner Remove junk & broken recipes (API, safe)"
    echo "    3) 🏷️  Auto-Tagger    Tag by cuisine, protein, tools (DB, advanced)"
    echo "    4) 🚀 Run All         Tagger → Cleaner → Parser (full suite)"
    echo ""
    printf "  Enter choice [1-4]: "
    read choice
    case "$choice" in
        1) SCRIPT="parser"  ;;
        2) SCRIPT="cleaner" ;;
        3) SCRIPT="tagger"  ;;
        4) SCRIPT="all"     ;;
        *)
            echo "❌ Invalid selection. Exiting."
            exit 1
            ;;
    esac
else
    # Non-interactive (piped/cron) — safe default
    SCRIPT="parser"
fi

# --- First-Run Setup Wizard ---
# Only runs in interactive mode when required vars are missing
NEEDS_SAVE=false

if [ -t 0 ]; then
    # API-based tools need MEALIE_URL and MEALIE_API_TOKEN
    if [ "$SCRIPT" = "parser" ] || [ "$SCRIPT" = "cleaner" ] || [ "$SCRIPT" = "all" ]; then
        if [ -z "$MEALIE_URL" ]; then
            echo ""
            echo "  ⚙️  First-Run Setup"
            echo "  ─────────────────────"
            printf "  Mealie URL (e.g. http://192.168.1.100:9000): "
            read input_url
            if [ -n "$input_url" ]; then
                export MEALIE_URL="$input_url"
                NEEDS_SAVE=true
            fi
        fi

        if [ -z "$MEALIE_API_TOKEN" ]; then
            printf "  Mealie API Token (from User Profile → API Tokens): "
            read input_token
            if [ -n "$input_token" ]; then
                export MEALIE_API_TOKEN="$input_token"
                NEEDS_SAVE=true
            fi
        fi
    fi

    # Tagger needs database settings
    if [ "$SCRIPT" = "tagger" ] || [ "$SCRIPT" = "all" ]; then
        if [ -z "$DB_TYPE" ]; then
            printf "  Database type [sqlite/postgres] (default: sqlite): "
            read input_db
            input_db=${input_db:-sqlite}
            export DB_TYPE="$input_db"
            DATABASE="$input_db"
            NEEDS_SAVE=true
        fi

        if [ "$DATABASE" = "postgres" ]; then
            if [ -z "$POSTGRES_HOST" ]; then
                printf "  Postgres Host (e.g. 192.168.1.100): "
                read input_pghost
                [ -n "$input_pghost" ] && export POSTGRES_HOST="$input_pghost" && NEEDS_SAVE=true
            fi
            if [ -z "$POSTGRES_PORT" ]; then
                printf "  Postgres Port (default: 5432): "
                read input_pgport
                input_pgport=${input_pgport:-5432}
                export POSTGRES_PORT="$input_pgport"
                NEEDS_SAVE=true
            fi
            if [ -z "$POSTGRES_DB" ]; then
                printf "  Postgres Database (default: mealie): "
                read input_pgdb
                input_pgdb=${input_pgdb:-mealie}
                export POSTGRES_DB="$input_pgdb"
                NEEDS_SAVE=true
            fi
            if [ -z "$POSTGRES_USER" ]; then
                printf "  Postgres User (default: mealie): "
                read input_pguser
                input_pguser=${input_pguser:-mealie}
                export POSTGRES_USER="$input_pguser"
                NEEDS_SAVE=true
            fi
            if [ -z "$POSTGRES_PASSWORD" ]; then
                printf "  Postgres Password: "
                read input_pgpass
                [ -n "$input_pgpass" ] && export POSTGRES_PASSWORD="$input_pgpass" && NEEDS_SAVE=true
            fi
        elif [ "$DATABASE" = "sqlite" ]; then
            if [ -z "$SQLITE_PATH" ]; then
                printf "  SQLite DB path (default: /app/data/mealie.db): "
                read input_sqlpath
                input_sqlpath=${input_sqlpath:-/app/data/mealie.db}
                export SQLITE_PATH="$input_sqlpath"
                NEEDS_SAVE=true
            fi
        fi
    fi

    # Save settings for next time
    if [ "$NEEDS_SAVE" = "true" ]; then
        echo ""
        echo "  💾 Saving settings to config/.env for next time..."
        {
            echo "# KitchenOps — Auto-generated settings"
            echo "# Saved on $(date '+%Y-%m-%d %H:%M:%S')"
            [ -n "$MEALIE_URL" ] && echo "MEALIE_URL=$MEALIE_URL"
            [ -n "$MEALIE_API_TOKEN" ] && echo "MEALIE_API_TOKEN=$MEALIE_API_TOKEN"
            [ -n "$DB_TYPE" ] && echo "DB_TYPE=$DB_TYPE"
            [ -n "$SQLITE_PATH" ] && echo "SQLITE_PATH=$SQLITE_PATH"
            [ -n "$POSTGRES_HOST" ] && echo "POSTGRES_HOST=$POSTGRES_HOST"
            [ -n "$POSTGRES_PORT" ] && echo "POSTGRES_PORT=$POSTGRES_PORT"
            [ -n "$POSTGRES_DB" ] && echo "POSTGRES_DB=$POSTGRES_DB"
            [ -n "$POSTGRES_USER" ] && echo "POSTGRES_USER=$POSTGRES_USER"
            [ -n "$POSTGRES_PASSWORD" ] && echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD"
        } > "$ENV_FILE"
        echo "  ✅ Saved! Mount config/ next time and these will be loaded automatically."
    fi
fi

echo ""
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
