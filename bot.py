import os
import psycopg2
import re
import smtplib
from email.mime.text import MIMEText
import google.generativeai as genai
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

# -----------------------------------------------------------------------------
# Per-chat session data in memory
# -----------------------------------------------------------------------------
user_sessions = {}

# -----------------------------------------------------------------------------
# Booking States
# -----------------------------------------------------------------------------
BOOKING_STATES = [
    "idle",
    "booking_init",
    "select_doctor",
    "select_day",
    "select_month",
    "select_time",
    "get_name",
    "get_email"
]

# -----------------------------------------------------------------------------
# Symptom-based recommendation:
#   If the user says "I have a fever," we might recommend the general practitioner
# -----------------------------------------------------------------------------
SYMPTOM_MAP = {
    # Common GP-related symptoms
    "fever": "general practitioner",
    "flu": "general practitioner",
    "cough": "general practitioner",
    "cold": "general practitioner",
    # Cardiology-related
    "heart": "cardiologist",
    "cardiac": "cardiologist",
    "chest pain": "cardiologist"
}

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def is_valid_email(email: str) -> bool:
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def get_doctors():
    """
    Retrieves the list of doctors from the 'doctorss' table:
      (doctor_id, name, specialty)
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT doctor_id, name, specialty FROM doctorss;")
        doctors = cur.fetchall()
        conn.close()
        return doctors
    except Exception as e:
        print("❌ DB Doctors Fetch Error:", e)
        return []

def is_slot_available(doctor_id, day, month, time_):
    """
    Checks the DB to see if the given doctor, date, and time slot are free.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM appointmentss
            WHERE doctor_id = %s AND appointment_day = %s AND appointment_month = %s AND appointment_time = %s;
        """, (doctor_id, day, month, time_))
        count = cur.fetchone()[0]
        conn.close()
        return count == 0
    except Exception as e:
        print("❌ Availability Check Error:", e)
        return False

def create_appointment(data):
    """
    Inserts a new appointment into the 'appointmentss' table.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO appointmentss (
                patient_name, patient_email, doctor_id,
                appointment_day, appointment_month, appointment_time
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING appointment_id;
        """, (
            data["patient_name"],
            data["patient_email"],
            data["doctor_id"],
            data["appointment_day"],
            data["appointment_month"],
            data["appointment_time"]
        ))
        appointment_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        return appointment_id
    except Exception as e:
        print("❌ DB Appointment Insert Error:", e)
        return None

def send_confirmation_email(email, name, doctor, day, month, time_):
    """
    Sends a confirmation email to the patient with the booking details.
    """
    subject = "Appointment Confirmation - Srivathsan Healthcare"
    body = f"""
Hi {name},

Your appointment with {doctor} is confirmed for {day}/{month} at {time_}.

Thank you for choosing Srivathsan Healthcare!
    """
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = email
    try:
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print("❌ Email Sending Error:", e)
        return False

def initialize_session(chat_id):
    """
    Retrieves or initializes user session data for the given chat_id.
    """
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {
            "state": "idle",
            "booking_data": {
                "doctor_id": None,
                "doctor_name": None,
                "appointment_day": None,
                "appointment_month": None,
                "appointment_time": None,
                "patient_name": None,
                "patient_email": None
            },
            # Keep track of the last few messages for more context with Gemini
            "context": []
        }
    return user_sessions[chat_id]

def format_doctor_list():
    """
    Returns a nicely formatted list of doctors and specialties.
    """
    docs = get_doctors()
    if not docs:
        return "No doctors are available at the moment."
    lines = [f"- {doc[1]} ({doc[2]})" for doc in docs]
    return "\n".join(lines)

# -----------------------------------------------------------------------------
# Fuzzy Doctor Matching
# -----------------------------------------------------------------------------
def fuzzy_match_doctor(user_input: str):
    """
    Tries to fuzzy match a doctor name (e.g. "Srivathsan?" or "Suresh!!")
    against the known list of doctors from the DB.

    Returns: (doc_id, doc_name) or None if no match found.
    """
    user_input_clean = re.sub(r"[^a-zA-Z0-9\s]", "", user_input).lower().strip()
    doctors = get_doctors()
    best_match = None
    best_score = 0

    for doc_id, name, specialty in doctors:
        # Clean up the doctor name too
        doc_name_clean = re.sub(r"[^a-zA-Z0-9\s]", "", name).lower().strip()
        # A simple approach: count how many words from user_input match doc_name
        # Or you can use difflib for a more robust approach
        matches = 0
        for token in user_input_clean.split():
            if token in doc_name_clean.split():
                matches += 1
        score = matches / max(len(user_input_clean.split()), 1)

        if score > best_score:
            best_score = score
            best_match = (doc_id, name)

    # If we are above a threshold, we say it matched
    if best_score > 0.4:  # adjust threshold as needed
        return best_match
    return None

# -----------------------------------------------------------------------------
# Symptom Checking for Automatic Doctor Recommendation
# -----------------------------------------------------------------------------
def recommend_doctor_for_symptoms(user_input: str):
    """
    If the user mentions certain symptoms, we can recommend a doctor.
    E.g. 'I have a fever' -> recommends general practitioner.
    Returns: 'general practitioner' or 'cardiologist' or None if not sure.
    """
    user_input_lower = user_input.lower()
    matched_specialties = []

    for symptom, specialty in SYMPTOM_MAP.items():
        if symptom in user_input_lower:
            matched_specialties.append(specialty)

    # If we find multiple specialties, just pick the first or you can handle logic
    if matched_specialties:
        return matched_specialties[0]
    return None

def get_doctor_by_specialty(specialty: str):
    """
    Returns the first doctor in the DB that matches the specialty (rough match).
    E.g. 'general practitioner' or 'cardiologist'.
    If none found, return None.
    """
    doctors = get_doctors()
    for doc_id, name, spec in doctors:
        if spec.lower().startswith(specialty.lower()):
            return (doc_id, name)
    return None

# -----------------------------------------------------------------------------
# Gemini Free-Form Response
# -----------------------------------------------------------------------------
async def send_gemini_response(chat_id, user_input, context, bot):
    """
    Calls Gemini to respond in a natural, friendly style.
    We pass it some context and the user’s prompt.
    """
    full_prompt = (
        "You are a friendly, empathetic, and extremely human-like admin assistant for Srivathsan Healthcare.\n"
        "Respond to the user in a warm, conversational tone.So "
        "whenever you naturally talk about appointment "
        "like for example if youre asking them a question "
        "like would you like to book an appointment or something"
        " related to appoint. always say like if you wanna go ahead "
        "and book an appointment say the word appointment and i'll take you through the process. whatever kind of things beacuse sometimes when naturally you might say do you want to book an appoint ment the user might say yes so dont let them say yes if the say yes or okay or whaetver like a confirming word ask them to enter the word appointment to take them through the booking process. Whatever conversations youre making keep it in the space of health care admin you can have conversation with them naturally but always keep it in the space of an healthcare admin and always try to drive the conversation in booking an appointment by asking them to say the word appointment be strict about it and also youve been trained make appointment only you can do any other actions apart from naturaly having conversation.. driving them towards appointment when having conversation and also you could give some general medical advice and prompt them towards bookgin an appoint by asking them say the word appointment if you find that they might have some serious problem by the converssations you have with them and make sure to keep the conversation neat and clean noo too much talking and not too less talking be a nice admin and also if they are typing some random things and that has the word appointment dont jump into the booking flow if you see just one word appointment then you go with the booking flow and also one more thing youre basically based on edinburgh so make sure the terminolies and everything are the same accordingly\n\n"
    )
    if context:
        # We embed the last few lines of conversation as context
        full_prompt += "\n".join(context) + "\n"
    full_prompt += f"User: {user_input}\nAssistant:"
    try:
        model = genai.GenerativeModel("models/gemini-2.0-flash")
        response = model.generate_content(full_prompt)
        text = response.text.strip() if response.text else "I'm sorry, I didn't catch that."
    except Exception as e:
        print("❌ Gemini response error:", e)
        text = "I’m here to help, but something went wrong. Could you please rephrase that?"
    await bot.send_message(chat_id=chat_id, text=text)

# -----------------------------------------------------------------------------
# Booking Flow (State Machine)
# -----------------------------------------------------------------------------
async def process_booking_flow(chat_id, msg, update, context_obj):
    session = user_sessions[chat_id]
    state = session["state"]
    booking = session["booking_data"]

    # 1) If we are idle but see a booking intent, move to booking_init
    if state == "idle" and any(word in msg.lower() for word in ["book", "appointment", "consultation", "schedule"]):
        session["state"] = "booking_init"

        # Also check if the user mentioned a symptom
        # => Offer a recommended doctor if we can detect one
        recommended_specialty = recommend_doctor_for_symptoms(msg)
        if recommended_specialty:
            doc = get_doctor_by_specialty(recommended_specialty)
            if doc:
                (doc_id, doc_name) = doc
                booking["doctor_id"] = doc_id
                booking["doctor_name"] = doc_name
                session["state"] = "select_day"
                response_text = (
                    f"I’m so sorry you’re not feeling well. Based on your symptoms, I’d recommend seeing {doc_name}. "
                    "Let's get you scheduled! Which day of this month would work for you (1-31)?"
                )
                await context_obj.bot.send_message(chat_id=chat_id, text=response_text)
                return
            # If we recommended a specialty but no doc is found, just go normal flow
        # Normal flow if no symptom-based recommendation
        doctor_list = format_doctor_list()
        response_text = (
            "Sure, let’s book an appointment! Here are our available doctors:\n"
            + doctor_list
            + "\n\nWho would you like to consult with? Or let me know if you have symptoms so I can recommend someone."
        )
        await context_obj.bot.send_message(chat_id=chat_id, text=response_text)
        return

    # If user is in "booking_init" or "select_doctor" state, we try to figure out which doctor they want
    if state in ["booking_init", "select_doctor"]:
        best_match = fuzzy_match_doctor(msg)
        if best_match:
            doc_id, doc_name = best_match
            booking["doctor_id"] = doc_id
            booking["doctor_name"] = doc_name
            session["state"] = "select_day"
            await context_obj.bot.send_message(
                chat_id=chat_id,
                text=f"Great choice! I’ve got you down for {doc_name}. Which day of this month works for you (1-31)?"
            )
        else:
            # Could also check for symptom-based rec again
            recommended_specialty = recommend_doctor_for_symptoms(msg)
            if recommended_specialty:
                doc = get_doctor_by_specialty(recommended_specialty)
                if doc:
                    (doc_id, doc_name) = doc
                    booking["doctor_id"] = doc_id
                    booking["doctor_name"] = doc_name
                    session["state"] = "select_day"
                    await context_obj.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"I’m so sorry to hear that you’re not well. "
                            f"For those symptoms, {doc_name} would be a good fit. "
                            "What day of the month suits you?"
                        )
                    )
                    return
            # If still no match, prompt the user politely
            session["state"] = "select_doctor"
            doc_list = format_doctor_list()
            await context_obj.bot.send_message(
                chat_id=chat_id,
                text=(
                    "I’m not entirely sure which doctor you want. Could you clarify? "
                    f"Here’s a quick reminder of who’s available:\n{doc_list}\n\n"
                    "Kindly mention just their name"
                )
            )
        return

    # Next states: collecting date/time
    if state == "select_day":
        if msg.isdigit() and 1 <= int(msg) <= 31:
            booking["appointment_day"] = int(msg)
            session["state"] = "select_month"
            await context_obj.bot.send_message(
                chat_id=chat_id,
                text="Great! Which month number would you prefer? (1-12)"
            )
        else:
            await context_obj.bot.send_message(
                chat_id=chat_id,
                text="Hmm, that doesn't seem like a valid day (1-31). Could you try again?"
            )
        return

    if state == "select_month":
        if msg.isdigit() and 1 <= int(msg) <= 12:
            booking["appointment_month"] = int(msg)
            session["state"] = "select_time"
            await context_obj.bot.send_message(
                chat_id=chat_id,
                text="Fantastic. What time slot do you prefer? (Format: HH:MM:SS, e.g. 09:30:00)"
            )
        else:
            await context_obj.bot.send_message(
                chat_id=chat_id,
                text="That doesn’t seem like a valid month (1-12). Could you try again?"
            )
        return

    if state == "select_time":
        # Validate the time format
        if re.match(r"^\d{2}:\d{2}:\d{2}$", msg):
            booking["appointment_time"] = msg
            # Check if slot is available
            if is_slot_available(
                booking["doctor_id"],
                booking["appointment_day"],
                booking["appointment_month"],
                booking["appointment_time"]
            ):
                session["state"] = "get_name"
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text="That slot is free! Could I get your name?"
                )
            else:
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text="I’m sorry, that time slot’s already taken. Could you give me another time in HH:MM:SS?"
                )
        else:
            await context_obj.bot.send_message(
                chat_id=chat_id,
                text="Time must be in HH:MM:SS format (e.g., 14:30:00). Could you try again?"
            )
        return

    if state == "get_name":
        booking["patient_name"] = msg.strip()
        session["state"] = "get_email"
        await context_obj.bot.send_message(
            chat_id=chat_id,
            text=(
                f"Thanks, {booking['patient_name']}! Finally, could I get your email address "
                "so I can send you a confirmation?"
            )
        )
        return

    if state == "get_email":
        if is_valid_email(msg):
            booking["patient_email"] = msg.strip()
            # Create appointment in the DB
            app_id = create_appointment(booking)
            if app_id:
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text="Awesome news: your appointment is confirmed"
                )
                emailed = send_confirmation_email(
                    booking["patient_email"],
                    booking["patient_name"],
                    booking["doctor_name"],
                    booking["appointment_day"],
                    booking["appointment_month"],
                    booking["appointment_time"]
                )
                if emailed:
                    await context_obj.bot.send_message(
                        chat_id=chat_id,
                        text="I’ve just sent you a confirmation email. Hope you feel better soon!"
                    )
                else:
                    await context_obj.bot.send_message(
                        chat_id=chat_id,
                        text="We booked the appointment, but I couldn’t send the confirmation email. Sorry about that!"
                    )
            else:
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text="There was an error saving your appointment. Maybe try again in a moment?"
                )
            # Reset session
            session["state"] = "idle"
            session["booking_data"] = {
                "doctor_id": None,
                "doctor_name": None,
                "appointment_day": None,
                "appointment_month": None,
                "appointment_time": None,
                "patient_name": None,
                "patient_email": None
            }
        else:
            await context_obj.bot.send_message(
                chat_id=chat_id,
                text="That doesn’t look like a valid email. Could you try typing it again?"
            )
        return


# -----------------------------------------------------------------------------
# Main Bot Handler
# -----------------------------------------------------------------------------
async def handle_message(update: Update, context_obj: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = update.message.text.strip()

    # ✅ Reset session if user types "reset"
    if msg.lower() == "reset":
        user_sessions[chat_id] = {
            "state": "idle",
            "booking_data": {
                "doctor_id": None,
                "doctor_name": None,
                "appointment_day": None,
                "appointment_month": None,
                "appointment_time": None,
                "patient_name": None,
                "patient_email": None
            },
            "context": []
        }
        await context_obj.bot.send_message(chat_id=chat_id, text="🔄 Chat has been reset")
        return




    session = initialize_session(chat_id)
    # Keep track of conversation context for a more personal Gemini fallback
    session["context"].append(f"User: {msg}")
    if len(session["context"]) > 10:
        session["context"] = session["context"][-10:]

    # If we're in the middle of a booking flow, handle that first
    if session["state"] != "idle":
        await process_booking_flow(chat_id, msg, update, context_obj)
        return

    # If the user message suggests they want to book an appointment but we are idle
    if any(word in msg.lower() for word in ["book", "appointment", "consultation", "schedule"]):
        await process_booking_flow(chat_id, msg, update, context_obj)
        return

    # If the user has a health complaint or symptom but hasn't explicitly asked to book
    recommended_specialty = recommend_doctor_for_symptoms(msg)
    if recommended_specialty:
        doc = get_doctor_by_specialty(recommended_specialty)
        if doc:
            doc_id, doc_name = doc
            # Suggest a doctor in a human-like manner
            text = (
                f"I'm really sorry you're experiencing that. You might consider seeing {doc_name}, "
                "who specializes in that area. If you would like to book an appointment now, just type the word 'Appointment'?"
            )
            session["context"].append(f"Assistant: {text}")
            await context_obj.bot.send_message(chat_id=chat_id, text=text)
            return

    # If it's just casual chat or something else, let Gemini handle it
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]
    if any(greet in msg.lower() for greet in greetings):
        # Offer a friendly greeting with a prompt
        text = (
            "Hey there! Welcome to Srivathsan Healthcare. How can I help you today? If you’d like to book an appointment or "
            "ask about symptoms, I’m here for you."
        )
        session["context"].append(f"Assistant: {text}")
        await context_obj.bot.send_message(chat_id=chat_id, text=text)
        return

    # Fallback to Gemini for free-flowing conversation
    await send_gemini_response(chat_id, msg, session["context"], context_obj.bot)
    session["context"].append("Assistant: [Gemini response]")


# -----------------------------------------------------------------------------
# Run the Bot
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Srivathsan Healthcare Assistant is now running...")
    app.run_polling()
