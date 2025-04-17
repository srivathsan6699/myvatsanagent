import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Updated sample appointment data with only day and month
sample_data = [
    ("John Doe", "john@example.com", "Dr. Srivathsan", 18, 4, "10:00:00"),
    ("Priya Sharma", "priya@example.com", "Dr. Suresh", 19, 4, "11:30:00"),
    ("Liam Brown", "liam@example.com", "Dr. Srivathsan", 20, 4, "14:00:00")
]

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    for patient in sample_data:
        patient_name, patient_email, doctor_name, day, month, time = patient

        # Fetch doctor_id using the doctor_name
        cur.execute("SELECT doctor_id FROM doctors WHERE name = %s;", (doctor_name,))
        result = cur.fetchone()

        if result:
            doctor_id = result[0]
            cur.execute("""
                INSERT INTO appointmentss (
                    patient_name, patient_email, doctor_id,
                    appointment_day, appointment_month, appointment_time
                ) VALUES (%s, %s, %s, %s, %s, %s);
            """, (patient_name, patient_email, doctor_id, day, month, time))
        else:
            print(f"❌ Doctor '{doctor_name}' not found. Skipping...")

    conn.commit()
    print("✅ Sample appointments inserted!")
    conn.close()
except Exception as e:
    print("❌ Failed to insert data:")
    print(e)
