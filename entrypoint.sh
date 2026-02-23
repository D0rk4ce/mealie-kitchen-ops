#!/bin/sh

# Dynamically fetch the latest release tag from GitHub, fallback to 'latest'
VERSION=$(python3 -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('https://api.github.com/repos/D0rk4ce/mealie-kitchen-ops/releases').read())[0]['tag_name'])" 2>/dev/null || echo "latest")
ENV_FILE="config/.env"

# Graceful exit on Ctrl+C or termination
trap 'echo ""; echo "  ⛔ Interrupted. Exiting gracefully."; exit 130' INT TERM

# --- Help / Version Flags ---
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "KitchenOps v${VERSION} — Automation Suite for Mealie"
    echo ""
    echo "Usage: Set the SCRIPT_TO_RUN environment variable to choose a tool,"
    echo "       or run interactively to get a selection menu."
    echo ""
    echo "  SCRIPT_TO_RUN=tagger   Auto-tag recipes by cuisine, protein, etc. (API)"
    echo "  SCRIPT_TO_RUN=parser   Fix unparsed ingredients via NLP (API)"
    echo "  SCRIPT_TO_RUN=cleaner  Remove junk / broken recipes (API)"
    echo "  SCRIPT_TO_RUN=all      Run Tagger → Cleaner → Parser in sequence"
    echo ""
    echo "Common Environment Variables:"
    echo "  DRY_RUN=true           Simulate changes without writing (default: true)"
    echo "  MEALIE_URL             Your Mealie instance URL"
    echo "  MEALIE_API_TOKEN       API token from Mealie User Profile"
    echo "  MAX_WORKERS            Number of parallel threads to use (default: 4)"
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

# --- Auto-detect .env files (item 9) ---
load_env_file() {
    _file="$1"
    if [ -f "$_file" ]; then
        while IFS='=' read -r key value; do
            case "$key" in
                \#*|"") continue ;;
            esac
            eval "current=\$$key"
            if [ -z "$current" ]; then
                export "$key=$value"
            fi
        done < "$_file"
    fi
}

ENV_LOADED=""
if [ -f ".env" ]; then
    load_env_file ".env"
    ENV_LOADED=".env"
fi
if [ -f "$ENV_FILE" ]; then
    load_env_file "$ENV_FILE"
    if [ -z "$ENV_LOADED" ]; then
        ENV_LOADED="$ENV_FILE"
    else
        ENV_LOADED="$ENV_LOADED + $ENV_FILE"
    fi
fi

echo "========================================"
echo "  KITCHENOPS LAUNCHER v${VERSION}"
echo "========================================"
if [ -n "$ENV_LOADED" ]; then
    echo "  Loaded: $ENV_LOADED"
fi

# --- Script Selection ---
show_menu() {
    echo ""
    echo "  What would you like to do?"
    echo ""
    echo "    1) 🔧 Batch Parser"
    echo "       Fix unparsed ingredients using Mealie's NLP engine."
    echo "       • Requires: API Token"
    echo "       • Speed:    Slow (API) | ⚡ Fast (DB Accelerator)"
    echo ""
    echo "    2) 🧹 Library Cleaner"
    echo "       Remove junk content and broken recipes automatically."
    echo "       • Requires: API Token"
    echo "       • Speed:    Medium (API) | ⚡ Instant (DB Accelerator)"
    echo ""
    echo "    3) 🏷️  Auto-Tagger"
    echo "       Tag recipes by cuisine, protein, cheese, and kitchen tools."
    echo "       • Requires: API Token"
    echo "       • Speed:    ⚡ Fast (Parallel API)"
    echo ""
    echo "    4) 🚀 Run All"
    echo "       Execute the full suite: Tagger → Cleaner → Parser"
    echo ""
    echo "    0) ❌ Exit"
    echo ""
    printf "  Enter choice [0-4]: "
}

if [ -n "$SCRIPT_TO_RUN" ]; then
    SCRIPT="$SCRIPT_TO_RUN"
elif [ -t 0 ]; then
    show_menu
    read choice
    case "$choice" in
        1) SCRIPT="parser"  ;;
        2) SCRIPT="cleaner" ;;
        3) SCRIPT="tagger"  ;;
        4) SCRIPT="all"     ;;
        0)
            echo "  Goodbye!"
            exit 0
            ;;
        *)
            echo ""
            echo "  ❌ Invalid selection. Please run again and choose 0-4."
            exit 1
            ;;
    esac
    echo ""
else
    SCRIPT="parser"
fi

# --- Failsafe: Wait for Mealie ---
wait_for_mealie() {
    echo "  ⏳ Verifying Mealie API is online..."
    echo "     (URL: $MEALIE_URL)"
    
    count=0
    while [ $count -lt 15 ]; do
        STATUS=$(python3 -c "import urllib.request, sys; print('UP') if urllib.request.urlopen(sys.argv[1], timeout=2).getcode() else print('DOWN')" "$MEALIE_URL" 2>/dev/null || echo "DOWN")
        if [ "$STATUS" = "UP" ]; then
            echo "     ✅ Mealie is online!"
            return 0
        fi
        printf "."
        sleep 2
        count=$((count + 1))
    done
    
    echo ""
    echo "  ❌ Timed out waiting for Mealie. Ensure your container is running."
    return 1
}

# ======================================
# FIRST-RUN SETUP WIZARD
# ======================================
NEEDS_SAVE=false

if [ -t 0 ]; then
    # All tools now require the API Connection
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

    # --- Dry Run Prompt (always ask) ---
    echo "  ──────────────────────────────────────"
    echo "  🛡️  Safety Mode"
    echo "  ──────────────────────────────────────"
    echo ""
    echo "  Dry Run mode lets you preview what KitchenOps would do"
    echo "  without making any actual changes."
    echo ""
    printf "  Enable Dry Run? (Y/n): "
    read input_dry
    case "$input_dry" in
        n|N|no|NO) export DRY_RUN="false" ;;
        *)         export DRY_RUN="true"  ;;
    esac
    echo ""

    # --- Save settings for next time ---
    if [ "$NEEDS_SAVE" = "true" ]; then
        echo "  💾 Saving settings to config/.env..."
        echo "     (Mount -v \$(pwd)/config:/app/config and these load automatically)"
        mkdir -p "$(dirname "$ENV_FILE")"
        {
            echo "# KitchenOps — Auto-generated settings"
            echo "# Saved on $(date '+%Y-%m-%d %H:%M:%S')"
            [ -n "$MEALIE_URL" ] && echo "MEALIE_URL=$MEALIE_URL"
            [ -n "$MEALIE_API_TOKEN" ] && echo "MEALIE_API_TOKEN=$MEALIE_API_TOKEN"
            [ -n "$DRY_RUN" ] && echo "DRY_RUN=$DRY_RUN"
            
            # Preserve existing DB variables if they were set externally for accelerators
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

# ======================================
# DRY RUN / LIVE MODE BANNER (item 5)
# ======================================
DRY_RUN_ACTUAL=${DRY_RUN:-true}
echo ""
if [ "$DRY_RUN_ACTUAL" = "true" ]; then
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║  🛡️  DRY RUN MODE                    ║"
    echo "  ║  No changes will be made.            ║"
    echo "  ║  Set DRY_RUN=false to go live.       ║"
    echo "  ╚══════════════════════════════════════╝"
else
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║  🔴 LIVE MODE                        ║"
    echo "  ║  Changes WILL be applied!            ║"
    echo "  ╚══════════════════════════════════════╝"
fi
echo ""

# ======================================
# PRE-FLIGHT CONFIRMATION (item 1)
# ======================================
SCRIPT_LABEL=""
case "$SCRIPT" in
    "parser")  SCRIPT_LABEL="🔧 Batch Parser" ;;
    "cleaner") SCRIPT_LABEL="🧹 Library Cleaner" ;;
    "tagger")  SCRIPT_LABEL="🏷️  Auto-Tagger (API)" ;;
    "all")     SCRIPT_LABEL="🚀 Full Suite (Tagger → Cleaner → Parser)" ;;
esac

echo "  ── Pre-Flight Summary ──────────────────"
echo ""
echo "    Tool     : $SCRIPT_LABEL"
[ -n "$MEALIE_URL" ] && echo "    Mealie   : $MEALIE_URL"
echo "    Dry Run  : $DRY_RUN_ACTUAL"
echo ""

# Final go/no-go
if [ -t 0 ]; then
    printf "  Proceed? (Y/n): "
    read go
    case "$go" in
        n|N|no|NO)
            echo "  ❌ Cancelled."
            exit 0
            ;;
    esac
    echo ""
fi

# Make sure Mealie is online before we hit it with API requests
if ! wait_for_mealie; then
    exit 1
fi

echo "========================================"

# ======================================
# RUN SCRIPT
# ======================================
run_script() {
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
        echo ""
        
        # 1. Tagger (API)
        python3 kitchen_ops_tagger.py
        
        # 2. Cleaner (API)
        python3 kitchen_ops_cleaner.py
        
        # 3. Parser (API)
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
}

# Execute
START_TIME=$(date +%s)
run_script
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

# Format elapsed time
if [ $ELAPSED -ge 86400 ]; then
    DAYS=$((ELAPSED / 86400))
    HOURS=$(( (ELAPSED % 86400) / 3600 ))
    MINS=$(( (ELAPSED % 3600) / 60 ))
    ELAPSED_STR="${DAYS}d ${HOURS}h ${MINS}m"
elif [ $ELAPSED -ge 3600 ]; then
    HOURS=$((ELAPSED / 3600))
    MINS=$(( (ELAPSED % 3600) / 60 ))
    ELAPSED_STR="${HOURS}h ${MINS}m"
elif [ $ELAPSED -ge 60 ]; then
    MINS=$((ELAPSED / 60))
    SECS=$((ELAPSED % 60))
    ELAPSED_STR="${MINS}m ${SECS}s"
else
    ELAPSED_STR="${ELAPSED}s"
fi

echo ""
echo "  ⏱️  Elapsed: $ELAPSED_STR"
echo ""

# "Run again?" loop — only in interactive mode
if [ -t 0 ]; then
    while true; do
        printf "  Run another tool? (y/N): "
        read again
        case "$again" in
            y|Y|yes|YES)
                show_menu
                read choice
                case "$choice" in
                    1) SCRIPT="parser"  ;;
                    2) SCRIPT="cleaner" ;;
                    3) SCRIPT="tagger"  ;;
                    4) SCRIPT="all"     ;;
                    0) echo "  Goodbye!"; exit 0 ;;
                    *) echo "  ❌ Invalid. Exiting."; exit 1 ;;
                esac
                echo ""
                printf "  Dry Run? (y/N): "
                read dr
                case "$dr" in
                    y|Y|yes|YES) export DRY_RUN="true"  ;;
                    *)           export DRY_RUN="false" ;;
                esac
                echo ""
                
                if ! wait_for_mealie; then exit 1; fi
                
                START_TIME=$(date +%s)
                run_script
                END_TIME=$(date +%s)
                ELAPSED=$((END_TIME - START_TIME))
                
                if [ $ELAPSED -ge 86400 ]; then
                    DAYS=$((ELAPSED / 86400))
                    HOURS=$(( (ELAPSED % 86400) / 3600 ))
                    MINS=$(( (ELAPSED % 3600) / 60 ))
                    ELAPSED_STR="${DAYS}d ${HOURS}h ${MINS}m"
                elif [ $ELAPSED -ge 3600 ]; then
                    HOURS=$((ELAPSED / 3600))
                    MINS=$(( (ELAPSED % 3600) / 60 ))
                    ELAPSED_STR="${HOURS}h ${MINS}m"
                elif [ $ELAPSED -ge 60 ]; then
                    MINS=$((ELAPSED / 60))
                    SECS=$((ELAPSED % 60))
                    ELAPSED_STR="${MINS}m ${SECS}s"
                else
                    ELAPSED_STR="${ELAPSED}s"
                fi
                echo ""
                echo "  ⏱️  Elapsed: $ELAPSED_STR"
                echo ""
                ;;
            *)
                break
                ;;
        esac
    done
fi

echo "--- KitchenOps Complete. Goodbye! ---"