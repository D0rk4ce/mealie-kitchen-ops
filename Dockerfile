# Use a lightweight Python base (Alpine Linux)
FROM python:3.11-alpine

# --- SYSTEM DEPENDENCIES ---
# We install BOTH clients so this image is "Universal".
# Users can switch between SQLite and Postgres via .env without rebuilding.
# - postgresql-client: Provides the 'psql' CLI tool used by the Tagger.
# - sqlite: Provides SQLite libraries for the Python runtime.
RUN apk add --no-cache postgresql-client sqlite

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Scripts & Launcher
COPY kitchen_ops_*.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Run the Launcher
ENTRYPOINT ["./entrypoint.sh"]
