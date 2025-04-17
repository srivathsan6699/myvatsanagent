import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Updated doctor seed data based on the revamped logic
doctors = [
    ("Dr. Srivathsan", "General Practitioner"),
    ("Dr. Suresh", "Cardiologist")
]

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    for doc in doctors:
        cur.execute("""
            INSERT INTO doctorss (name, specialty)
            VALUES (%s, %s);
        """, doc)

    conn.commit()
    print("✅ Sample doctors inserted!")
    conn.close()
except Exception as e:
    print("❌ Failed to insert doctors:")
    print(e)
