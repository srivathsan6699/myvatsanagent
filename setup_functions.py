import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

with open("functions.sql", "r") as file:
    sql_code = file.read()

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(sql_code)
    conn.commit()
    print("✅ Function loaded successfully!")
    conn.close()
except Exception as e:
    print("❌ Failed to load function:")
    print(e)
