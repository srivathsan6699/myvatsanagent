import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    print("📋 Appointments in the system:\n")

    cur.execute("""
        SELECT a.appointment_id, a.patient_name, a.patient_email, 
               d.name AS doctor_name, d.specialty,
               a.appointment_day, a.appointment_month, a.appointment_time
        FROM appointmentss a
        JOIN doctorss d ON a.doctor_id = d.doctor_id
        ORDER BY a.appointment_day, a.appointment_time;
    """)
    
    rows = cur.fetchall()
    for row in rows:
        print(row)

    conn.close()
except Exception as e:
    print("❌ Error reading appointments:")
    print(e)
