import os
import psycopg2
from dotenv import load_dotenv

# Load your .env
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # SQL call with fully explicit type casts
    sql = """
    SELECT create_appointment_with_conflict_check(
        %s::TEXT,
        %s::TEXT,
        %s::INTEGER,
        %s::INTEGER,
        %s::INTEGER,
        %s::TIME
    );
    """

    values = (
        "Test User",            # patient_name
        "test@example.com",     # patient_email
        1,                      # doctor_id
        21,                     # day
        4,                      # month
        "12:00:00"              # time
    )

    cur.execute(sql, values)
    result = cur.fetchone()
    print("✅ Function Output:", result)

    conn.close()
except Exception as e:
    print("❌ Error testing function:")
    print(e)
