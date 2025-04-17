CREATE OR REPLACE FUNCTION create_appointment_with_conflict_check(
    p_patient_name TEXT,
    p_patient_email TEXT,
    p_doctor_id INTEGER,
    p_day INTEGER,
    p_month INTEGER,
    p_time TIME
)
RETURNS INTEGER AS $$
DECLARE
    existing_count INTEGER;
    new_appointment_id INTEGER;
BEGIN
    -- Check for conflicts
    SELECT COUNT(*) INTO existing_count
    FROM appointmentss
    WHERE doctor_id = p_doctor_id
      AND appointment_day = p_day
      AND appointment_month = p_month
      AND appointment_time = p_time;

    IF existing_count > 0 THEN
        -- Conflict found
        RETURN NULL;
    ELSE
        -- Insert and return ID
        INSERT INTO appointmentss (
            patient_name, patient_email, doctor_id,
            appointment_day, appointment_month, appointment_time
        )
        VALUES (
            p_patient_name, p_patient_email, p_doctor_id,
            p_day, p_month, p_time
        )
        RETURNING appointment_id INTO new_appointment_id;

        RETURN new_appointment_id;
    END IF;
END;
$$ LANGUAGE plpgsql;
