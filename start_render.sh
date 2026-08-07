#!/bin/bash
set -e

echo "Starting Twin deployment sequence..."

# 1. Initialize the PostgreSQL Database Schema
# We use Python and asyncpg (which is already installed in your pyproject.toml) to execute schema.sql
echo "Injecting database schema..."
python -c "
import asyncio, asyncpg, os

async def init_db():
    conn_str = os.environ.get('TWIN_DATABASE_URL')
    if not conn_str:
        print('TWIN_DATABASE_URL not found, skipping db init')
        return
        
    try:
        conn = await asyncpg.connect(conn_str)
        with open('schema.sql', 'r') as f:
            await conn.execute(f.read())
        await conn.close()
        print('Schema successfully applied.')
    except Exception as e:
        print(f'Error applying schema: {e}')

asyncio.run(init_db())
"

# 2. Launch the Worker in the background
echo "Starting Background Worker..."
python -m twin.runtime.worker &

# 3. Launch the API in the foreground
# Render automatically injects the \$PORT environment variable for the web service
echo "Starting FastAPI Server..."
uvicorn twin.runtime.api:build_default_app --factory --host 0.0.0.0 --port ${PORT:-8000}
