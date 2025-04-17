from dotenv import load_dotenv
import os
import psycopg2

# Load your .env
load_dotenv()

# Get the connection string
DATABASE_URL = os.getenv("DATABASE_URL")

# Try connecting
try:
    conn = psycopg2.connect(DATABASE_URL)
    print("✅ Connected to DB!")
    conn.close()
except Exception as e:
    print("❌ Connection failed:")
    print(e)
