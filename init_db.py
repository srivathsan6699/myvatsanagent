import os
import psycopg2
from dotenv import load_dotenv

# Load your .env file
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# SQL to create the new doctors table
create_doctorss_table_sql = """
CREATE TABLE IF NOT EXISTS doctorss (
    doctor_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    specialty VARCHAR(100)
);
"""

# SQL to create the new appointments table with foreign key reference to doctors
create_appointmentss_table_sql = """
CREATE TABLE IF NOT EXISTS appointmentss (
    appointment_id SERIAL PRIMARY KEY,
    patient_name VARCHAR(100) NOT NULL,
    patient_email VARCHAR(100),
    doctor_id INTEGER NOT NULL REFERENCES doctors(doctor_id),
    appointment_day INTEGER NOT NULL CHECK (appointment_day BETWEEN 1 AND 31),
    appointment_month INTEGER NOT NULL CHECK (appointment_month BETWEEN 1 AND 12),
    appointment_time TIME NOT NULL
);
"""

# Connect and create both tables
try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(create_doctorss_table_sql)
    cur.execute(create_appointmentss_table_sql)
    conn.commit()
    print("✅ Tables created!")
    conn.close()
except Exception as e:
    print("❌ Failed to create tables:")
    print(e)
