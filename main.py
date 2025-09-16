import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# ENV
URL = os.getenv("SAFE2_JOB_URL")
NO_JOB_TEXT = os.getenv("NO_JOB_TEXT", "")
IGNORE_JOB_TEXT = os.getenv("IGNORE_JOB_TEXT", "")
ignore_keywords = [kw.strip().lower() for kw in IGNORE_JOB_TEXT.split(',') if kw.strip()]
sender_email = os.getenv("SENDER_EMAIL")
receiver_email = os.getenv("RECEIVER_EMAIL")
app_password = os.getenv("EMAIL_PASSWORD")
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_ids = os.getenv("TELEGRAM_CHAT_IDS").split(',')

# App & Alerts
app = Flask(__name__)
recent_alerts = []

def log_event(msg):
    print(f"[{datetime.now()}] {msg}")

def save_alert(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    recent_alerts.append({'time': timestamp, 'message': message})
    if len(recent_alerts) > 20:
        recent_alerts.pop(0)

def send_telegram_alert():
    message = f"🚨 A new job has been posted on Safe2. Check your portal now: {URL}"
    save_alert(message)

    for chat_id in chat_ids:
        try:
            url_telegram = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {'chat_id': chat_id.strip(), 'text': message}
            response = requests.post(url_telegram, data=data)
            if response.status_code == 200:
                log_event(f"📲 Telegram alert sent to {chat_id}")
            else:
                log_event(f"❌ Telegram alert failed for {chat_id}. Status: {response.status_code}")
        except Exception as e:
            log_event(f"❌ Telegram error for {chat_id}: {e}")

def send_email_notification():
    subject = "✅ New Safe2 Job Available!"
    body = f"A new job has been posted on Safe2. Check your portal now: {URL}"

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        log_event("📧 Email sent successfully.")
    except Exception as e:
        log_event(f"❌ Email error: {e}")

def check_for_job_change():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(URL, headers=headers)
        soup = BeautifulSoup(response.content, 'html.parser')
        full_text = soup.get_text(separator=' ', strip=True).lower()

        if NO_JOB_TEXT.lower() not in full_text:
            if any(keyword in full_text for keyword in ignore_keywords):
                log_event("⚠️ Ignored job detected. No notification sent.")
                return False

            log_event("🚨 New job found!")
            send_email_notification()
            send_telegram_alert()
            log_event("✅ New job posted. Alerts sent.")
            return True
        else:
            log_event("🔄 Still same message. Will check again.")
            return False

    except Exception as e:
        log_event(f"❌ Error checking site: {e}")
        return False

def start_job_checker():
    while True:
        check_for_job_change()
        time.sleep(30)

# Start background thread immediately (Flask 3.x safe)
threading.Thread(target=start_job_checker, daemon=True).start()

# Flask routes
@app.route("/")
def home():
    return "✅ Safe2 Job Notifier is running and alive."

@app.route("/alerts")
def alerts():
    html = """
    <html><head><title>Recent Alerts</title></head>
    <body>
    <h2>📋 Recent Job Alerts</h2>
    <ul>
        {% for alert in alerts %}
            <li><strong>{{ alert.time }}</strong>: {{ alert.message }}</li>
        {% endfor %}
    </ul>
    </body></html>
    """
    return render_template_string(html, alerts=recent_alerts)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
