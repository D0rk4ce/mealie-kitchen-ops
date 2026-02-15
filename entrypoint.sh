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
        case "$key" in
            \#*|"") continue ;;
        esac
        eval "current=\$$key"
        if [ -z "$current" ]; then
            export "$key=$value"
        fi
    done < "$ENV_FILE"
    # Re-read DATABASE in case DB_TYPE was loaded from saved env
    DATABASE=${DB_TYPE:-sqlite}
fi

echo "========================================"
echo "  KITCHENOPS LAUNCHER v${VERSION}"
echo "========================================"

# --- Script Selection ---
if [ -n "$SCRIPT_TO_RUN" ]; then
    SCRIPT="$SCRIPT_TO_RUN"
elif [ -t 0 ]; then
    echo ""
    echo "  What would you like to do?"
    echo ""
    echo "    1) 🔧 Batch Parser"
    echo "       Fix unparsed ingredients using Mealie's NLP engine."
    echo "       Requires: API only   |  Speed: Slow (days for large libraries)"
    echo ""
    echo "    2) 🧹 Library Cleaner"
    echo "       Remove junk content and broken recipes automatically."
    echo "       Requires: API only   |  Speed: Medium"
    echo ""
    echo "    3) 🏷️  Auto-Tagger"
    echo "       Tag recipes by cuisine, protein, cheese, and kitchen tools."
    echo "       Requires: DATABASE   |  Speed: Blazing fast (1000s/min)"
    echo ""
    echo "    4) 🚀 Run All"
    echo "       Execute the full suite: Tagger → Cleaner → Parser"
    echo ""
    printf "  Enter choice [1-4]: "
    read choice
    case "$choice" in
        1) SCRIPT="parser"  ;;
        2) SCRIPT="cleaner" ;;
        3) SCRIPT="tagger"  ;;
        4) SCRIPT="all"     ;;
        *)
            echo ""
            echo "  ❌ Invalid selection. Please run again and choose 1-4."
            exit 1
            ;;
    esac
    echo ""
else
    SCRIPT="parser"
fi

# ======================================
# FIRST-RUN SETUP WIZARD
# Only triggers in interactive mode when required vars are missing.
# ======================================
NEEDS_SAVE=false

if [ -t 0 ]; then

    # -----------------------------------------------------------
    # MEALIE API SETTINGS (needed by Parser, Cleaner, and "all")
    # -----------------------------------------------------------
    if [ "$SCRIPT" = "parser" ] || [ "$SCRIPT" = "cleaner" ] || [ "$SCRIPT" = "all" ]; then

        if [ -z "$MEALIE_URL" ] || [ -z "$MEALIE_API_TOKEN" ]; then
            echo "  ──────────────────────────────────────"
            echo "  ⚙️  First-Run Setup — API Connection"
            echo "  ──────────────────────────────────────"
            echo ""
        fi

        if [ -z "$MEALIE_URL" ]; then
            echo "  Your Mealie URL is the address you use to access Mealie"
            echo "  in your browser. Include the port if applicable."
            echo ""
            echo "  Examples:"
            echo "    • http://192.168.1.100:9000"
            echo "    • http://mealie.local:9000"
            echo "    • https://mealie.yourdomain.com"
            echo ""
            printf "  Mealie URL: "
            read input_url
            if [ -n "$input_url" ]; then
                export MEALIE_URL="$input_url"
                NEEDS_SAVE=true
            else
                echo "  ❌ Mealie URL is required. Exiting."
                exit 1
            fi
            echo ""
        fi

        if [ -z "$MEALIE_API_TOKEN" ]; then
            echo "  An API token lets KitchenOps talk to Mealie on your behalf."
            echo ""
            echo "  To create one:"
            echo "    1. Log in to Mealie as an admin user"
            echo "    2. Click your profile icon (top-right)"
            echo "    3. Go to 'API Tokens'"
            echo "    4. Create a new token and copy it"
            echo ""
            printf "  API Token: "
            read input_token
            if [ -n "$input_token" ]; then
                export MEALIE_API_TOKEN="$input_token"
                NEEDS_SAVE=true
            else
                echo "  ❌ API Token is required. Exiting."
                exit 1
            fi
            echo ""
        fi
    fi

    # -----------------------------------------------------------
    # DATABASE SETTINGS (only for Tagger or "all")
    # -----------------------------------------------------------
    if [ "$SCRIPT" = "tagger" ] || [ "$SCRIPT" = "all" ]; then

        # Also need API settings if running "all"
        if [ "$SCRIPT" = "all" ]; then
            # API settings were already handled above
            :
        fi

        # Need Mealie URL for tagger info display even though it uses DB
        if [ -z "$MEALIE_URL" ] && [ "$SCRIPT" = "tagger" ]; then
            echo "  ──────────────────────────────────────"
            echo "  ⚙️  First-Run Setup"
            echo "  ──────────────────────────────────────"
            echo ""
        fi

        if [ -z "$DB_TYPE" ]; then
            echo "  ──────────────────────────────────────"
            echo "  🗄️  Database Setup — Tagger Only"
            echo "  ──────────────────────────────────────"
            echo ""
            echo "  The Auto-Tagger connects directly to Mealie's database"
            echo "  for maximum speed. Which database does your Mealie use?"
            echo ""
            echo "    sqlite   — Default for most installs. Uses a .db file."
            echo "    postgres — Used by larger or production setups."
            echo ""
            echo "  Tip: Check your Mealie docker-compose.yml — if you see"
            echo "       a 'postgres' service, you're using Postgres."
            echo ""
            printf "  Database type [sqlite/postgres] (default: sqlite): "
            read input_db
            input_db=${input_db:-sqlite}
            export DB_TYPE="$input_db"
            DATABASE="$input_db"
            NEEDS_SAVE=true
            echo ""
        fi

        if [ "$DATABASE" = "sqlite" ]; then
            if [ -z "$SQLITE_PATH" ]; then
                echo "  📂 SQLite Setup"
                echo ""
                echo "  KitchenOps needs the path to Mealie's SQLite database file."
                echo "  This is the file inside your Docker volume, typically at:"
                echo ""
                echo "    /app/data/mealie.db"
                echo ""
                echo "  Make sure you mount your Mealie data directory with:"
                echo "    -v /path/to/mealie/data:/app/data"
                echo ""
                printf "  SQLite DB path (default: /app/data/mealie.db): "
                read input_sqlpath
                input_sqlpath=${input_sqlpath:-/app/data/mealie.db}
                export SQLITE_PATH="$input_sqlpath"
                NEEDS_SAVE=true
                echo ""
            fi
        fi

        if [ "$DATABASE" = "postgres" ]; then
            echo "  🐘 Postgres Connection Setup"
            echo ""
            echo "  ┌─────────────────────────────────────────────────┐"
            echo "  │  Where to find your Postgres credentials:       │"
            echo "  │                                                 │"
            echo "  │  • docker-compose.yml → look for POSTGRES_*     │"
            echo "  │  • /root/mealie.creds (community script)        │"
            echo "  │  • ~/mealie/mealie.creds (home dir install)     │"
            echo "  │  • Your .env file used with Mealie              │"
            echo "  └─────────────────────────────────────────────────┘"
            echo ""

            if [ -z "$POSTGRES_HOST" ]; then
                echo "  The hostname or IP of your Postgres server."
                echo "  If Mealie and Postgres run on the same Docker network,"
                echo "  use the service name (e.g. 'postgres' or 'db')."
                echo ""
                printf "  Postgres Host (e.g. 192.168.1.100 or 'postgres'): "
                read input_pghost
                if [ -n "$input_pghost" ]; then
                    export POSTGRES_HOST="$input_pghost"
                    NEEDS_SAVE=true
                else
                    echo "  ❌ Postgres host is required. Exiting."
                    exit 1
                fi
                echo ""
            fi

            if [ -z "$POSTGRES_PORT" ]; then
                printf "  Postgres Port (default: 5432): "
                read input_pgport
                input_pgport=${input_pgport:-5432}
                export POSTGRES_PORT="$input_pgport"
                NEEDS_SAVE=true
            fi

            if [ -z "$POSTGRES_DB" ]; then
                printf "  Database Name (default: mealie): "
                read input_pgdb
                input_pgdb=${input_pgdb:-mealie}
                export POSTGRES_DB="$input_pgdb"
                NEEDS_SAVE=true
            fi

            if [ -z "$POSTGRES_USER" ]; then
                printf "  Username (default: mealie): "
                read input_pguser
                input_pguser=${input_pguser:-mealie}
                export POSTGRES_USER="$input_pguser"
                NEEDS_SAVE=true
            fi

            if [ -z "$POSTGRES_PASSWORD" ]; then
                echo ""
                echo "  Tip: Your password is usually in one of these locations:"
                echo "    • docker-compose.yml → POSTGRES_PASSWORD"
                echo "    • /root/mealie.creds"
                echo "    • ~/mealie/mealie.creds"
                echo ""
                printf "  Password: "
                read input_pgpass
                if [ -n "$input_pgpass" ]; then
                    export POSTGRES_PASSWORD="$input_pgpass"
                    NEEDS_SAVE=true
                else
                    echo "  ❌ Postgres password is required. Exiting."
                    exit 1
                fi
            fi

            echo ""
            echo "  ⚠️  Reminder: Postgres must allow external connections."
            echo "  If you get 'connection refused', check on the DB server:"
            echo "    • postgresql.conf → listen_addresses = '*'"
            echo "    • pg_hba.conf    → host all all YOUR_SUBNET/24 md5"
            echo "  Then: sudo systemctl restart postgresql"
            echo ""
        fi
    fi

    # --- Save settings for next time ---
    if [ "$NEEDS_SAVE" = "true" ]; then
        echo "  💾 Saving settings to config/.env..."
        echo "     (Mount -v \$(pwd)/config:/app/config and these load automatically)"
        {
            echo "# KitchenOps — Auto-generated settings"
            echo "# Saved on $(date '+%Y-%m-%d %H:%M:%S')"
            [ -n "$MEALIE_URL" ] && echo "MEALIE_URL=$MEALIE_URL"
            [ -n "$MEALIE_API_TOKEN" ] && echo "MEALIE_API_TOKEN=$MEALIE_API_TOKEN"
            [ -n "$DRY_RUN" ] && echo "DRY_RUN=$DRY_RUN"
            [ -n "$DB_TYPE" ] && echo "DB_TYPE=$DB_TYPE"
            [ -n "$SQLITE_PATH" ] && echo "SQLITE_PATH=$SQLITE_PATH"
            [ -n "$POSTGRES_HOST" ] && echo "POSTGRES_HOST=$POSTGRES_HOST"
            [ -n "$POSTGRES_PORT" ] && echo "POSTGRES_PORT=$POSTGRES_PORT"
            [ -n "$POSTGRES_DB" ] && echo "POSTGRES_DB=$POSTGRES_DB"
            [ -n "$POSTGRES_USER" ] && echo "POSTGRES_USER=$POSTGRES_USER"
            [ -n "$POSTGRES_PASSWORD" ] && echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD"
        } > "$ENV_FILE"
        echo "  ✅ Done! Your settings are saved for next time."
        echo ""
    fi
fi

echo "  Script : $SCRIPT"
echo "  DB     : $DATABASE"
echo "  Dry Run: ${DRY_RUN:-true}"
echo "========================================"

# SAFETY LOCK: Prevent SQLite tagging on a live DB
if [ "$DATABASE" = "sqlite" ] && ([ "$SCRIPT" = "tagger" ] || [ "$SCRIPT" = "all" ]); then
    echo ""
    echo "  ❗ SAFETY ALERT: SQLite Mode"
    echo ""
    echo "  SQLite locks the database file during writes."
    echo "  Running the Tagger while Mealie is active WILL"
    echo "  corrupt your database."
    echo ""
    echo "  Please stop Mealie first:  docker stop mealie"
    echo "  You can restart it after:  docker start mealie"
    echo ""
    printf "  Have you stopped Mealie? (y/N): "
    read confirmed
    if [ "$confirmed" != "y" ] && [ "$confirmed" != "Y" ]; then
        echo "  ❌ Cancelled. Your database is safe."
        exit 1
    fi
    echo ""
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
    echo "  ❌ Unknown script: $SCRIPT"
    echo ""
    echo "  Available options: tagger, parser, cleaner, all"
    echo "  Run with --help for more info."
    exit 1
    ;;
esac

echo ""
echo "--- Operation Complete. Container Exiting. ---"
