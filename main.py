import os
import re
import time
import smtplib
import threading
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template_string
from dotenv import load_dotenv
from threading import Thread


# ---------------- env ----------------

# Load environment variables
load_dotenv()

# Other settings
CHECK_INTERVAL = 30  # ✅ Add this line

URL = os.getenv("SAFE2_JOB_URL")
NO_JOB_TEXT = os.getenv("NO_JOB_TEXT", "")
IGNORE_JOB_TEXT = os.getenv("IGNORE_JOB_TEXT", "")
IGNORE_SERVICES = os.getenv("IGNORE_SERVICES", "")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_IDS = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]


# Normalize ignored postcodes (case-insensitive)
IGNORED_POSTCODES = {pc.strip().upper() for pc in IGNORE_JOB_TEXT.split(",") if pc.strip()}
IGNORE_SERVICES = {pc.strip().upper() for pc in os.getenv("IGNORE_SERVICES", "").split(",") if pc.strip()}

# Simple UK postcode regex (good enough for alerts)
UK_PC_RE = r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b"

# ---------------- app & log ----------------
app = Flask(__name__)
recent_alerts = []   # [{'time': '...', 'message': '...'}]
MAX_LOG = 20

def log_event(msg: str):
    print(f"[{datetime.now()}] {msg}", flush=True)

def save_alert(message: str):
    recent_alerts.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    })
    if len(recent_alerts) > MAX_LOG:
        recent_alerts.pop(0)

# ---------------- notifiers ----------------
def send_telegram_alert(message: str):
    save_alert(message)
    for chat_id in CHAT_IDS:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": chat_id, "text": message},
                timeout=15,
            )
            if resp.status_code == 200:
                log_event(f"📲 Telegram alert sent to {chat_id}")
            else:
                log_event(f"❌ Telegram alert failed ({resp.status_code}) for {chat_id}")
        except Exception as e:
            log_event(f"❌ Telegram error for {chat_id}: {e}")

def send_email_notification(message: str):
    subject = "✅ New Safe2 Job Available!"
    body = f"{message}\n\nView it here: {URL}"

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
        server.starttls()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        log_event("📧 Email sent successfully.")
    except Exception as e:
        log_event(f"❌ Email error: {e}")


# ✅ GLOBAL toggle
# ---------------- global job state ----------------
active_jobs = set()
is_paused = False
# ---------------- core checker ----------------
def check_for_job_change():
    global active_jobs
    headers = {"User-Agent": "Mozilla/5.0 (Safe2 Job Notifier)"}

    try:
        resp = requests.get(URL, headers=headers, timeout=30)
        soup = BeautifulSoup(resp.content, "html.parser")

        full_text_raw = soup.get_text(separator=" ", strip=True).upper()

        if NO_JOB_TEXT and NO_JOB_TEXT.upper() in full_text_raw:
            if active_jobs:
                log_event("✅ Jobs cleared (picked up).")
                active_jobs.clear()
            return False

        # 🔴 Ignore jobs by service name (e.g., EPC)
        if any(service in full_text_raw for service in IGNORE_SERVICES):
            log_event(f"❌ Ignored job based on service: matched one of {IGNORE_SERVICES}")
            return False



        # ✅ Extract postcodes
        found_pcs = {
            m.group(1).upper().replace("  ", " ").strip()
            for m in re.finditer(UK_PC_RE, full_text_raw, flags=re.I)
        }

        non_ignored = sorted(pc for pc in found_pcs if pc not in IGNORED_POSTCODES)

        if non_ignored:
            new_jobs = set(non_ignored)

            if new_jobs != active_jobs:
                log_event(f"🚨 New or changed jobs: {', '.join(new_jobs)}")
                active_jobs = new_jobs  # store current jobs
            else:
                log_event(f"🔁 Re-alerting same job(s): {', '.join(active_jobs)}")

            message = f"🚨 Safe2 Job(s): {', '.join(active_jobs)}\nCheck portal: {URL}"
            send_email_notification(message)
            send_telegram_alert(message)
            return True
        else:
            if active_jobs:
                log_event("✅ Previously found jobs now cleared.")
                active_jobs.clear()
            log_event("⚠️ No valid jobs to notify.")
            return False

    except Exception as e:
        log_event(f"❌ Error checking site: {e}")
        return False











@app.route("/app")
def toggle_bot():
    global is_paused
    is_paused = not is_paused
    state = "paused" if is_paused else "running"
    return f"<h2>✅ Job checker is now <b>{state.upper()}</b>.</h2><a href='/alerts'>🔙 View Alerts</a>"



@app.route("/alerts")
def alerts():
    html = """
    <html><head><title>Recent Alerts</title></head>
    <body style="font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif">
      <h2>📋 Recent Job Alerts</h2>
      <ul>
        {% for a in alerts %}
          <li><strong>{{ a.time }}</strong>: {{ a.message }}</li>
        {% endfor %}
      </ul>
      {% if not alerts %}<p>No alerts yet.</p>{% endif %}
    </body></html>
    """
    return render_template_string(html, alerts=recent_alerts)

# ---------------- run ----------------
def start_job_checker():
    global is_paused
    log_event("✅ Job checker loop started.")
    while True:
        if not is_paused:
            check_for_job_change()
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    Thread(target=start_job_checker, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)


