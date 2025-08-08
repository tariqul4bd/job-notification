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

# ---------------- env ----------------
load_dotenv()

URL = os.getenv("SAFE2_JOB_URL")
NO_JOB_TEXT = os.getenv("NO_JOB_TEXT", "")
IGNORE_JOB_TEXT = os.getenv("IGNORE_JOB_TEXT", "")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_IDS = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]

# Normalize ignored postcodes (case-insensitive)
IGNORED_POSTCODES = {pc.strip().upper() for pc in IGNORE_JOB_TEXT.split(",") if pc.strip()}

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

# ---------------- core checker ----------------
def check_for_job_change():
    headers = {"User-Agent": "Mozilla/5.0 (Safe2 Job Notifier)"}
    try:
        resp = requests.get(URL, headers=headers, timeout=30)
        soup = BeautifulSoup(resp.content, "html.parser")
        full_text_raw = soup.get_text(separator=" ", strip=True)

        # If explicit "no jobs" banner is present, nothing to do
        if NO_JOB_TEXT and NO_JOB_TEXT in full_text_raw:
            log_event("🔄 Still same message. Will check again.")
            return False

        # Extract all postcodes from the page
        found_pcs = {
            m.group(1).upper().replace("  ", " ").strip()
            for m in re.finditer(UK_PC_RE, full_text_raw, flags=re.I)
        }
        log_event(f"🔎 Postcodes on page: {', '.join(sorted(found_pcs)) or 'none'}")

        # If no postcodes parsed but "no jobs" text is also missing, alert just in case
        if not found_pcs:
            message = f"🚨 New job detected (no postcode parsed). Check your portal: {URL}"
            log_event("⚠️ No postcodes parsed; sending cautious alert.")
            send_email_notification(message)
            send_telegram_alert(message)
            return True

        # Only suppress if *all* postcodes are ignored.
        non_ignored = sorted(pc for pc in found_pcs if pc not in IGNORED_POSTCODES)
        if non_ignored:
            pcs_str = ", ".join(non_ignored)
            message = f"🚨 New job(s) found: {pcs_str}\nCheck your portal: {URL}"
            log_event(f"🚨 New job(s) found for postcodes: {pcs_str}")
            send_email_notification(message)
            send_telegram_alert(message)
            log_event("✅ Alerts sent.")
            return True

        log_event(f"⚠️ Only ignored postcodes present: {', '.join(sorted(found_pcs))}. No notification sent.")
        return False

    except Exception as e:
        log_event(f"❌ Error checking site: {e}")
        return False

def start_job_checker():
    log_event("✅ Job checker loop started.")
    while True:
        check_for_job_change()
        time.sleep(30)

# Start the checker immediately (Flask 3.x friendly)
threading.Thread(target=start_job_checker, daemon=True).start()

# ---------------- routes ----------------
@app.route("/")
def home():
    return "✅ Safe2 Job Notifier is running and alive."

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
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
