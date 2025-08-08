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

# Load environment variables
load_dotenv()

# ===== ENV =====
URL = os.getenv("SAFE2_JOB_URL")
NO_JOB_TEXT = os.getenv("NO_JOB_TEXT", "")
IGNORE_JOB_TEXT = os.getenv("IGNORE_JOB_TEXT", "")
SENDER = os.getenv("SENDER_EMAIL")
RECEIVER = os.getenv("RECEIVER_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_IDS = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]

# Ignore list (postcodes), normalized to uppercase
IGNORED_POSTCODES = {pc.strip().upper() for pc in IGNORE_JOB_TEXT.split(",") if pc.strip()}

# Simple UK postcode regex (good enough for alerts)
UK_PC_RE = r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b"

# ===== App & in-memory alert log =====
app = Flask(__name__)
recent_alerts = []   # [{'time': 'yyyy-mm-dd hh:mm:ss', 'message': '...'}]
MAX_LOG = 20

def log_event(msg):
    print(f"[{datetime.now()}] {msg}", flush=True)

def save_alert(message):
    recent_alerts.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "message": message})
    if len(recent_alerts) > MAX_LOG:
        recent_alerts.pop(0)

# ===== Notifiers =====
def send_telegram_alert(message):
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

def send_email_notification(message):
    subject = "✅ New Safe2 Job Available!"
    body = f"{message}\n\nView it here: {URL}"

    msg = MIMEMultipart()
    msg["From"] = SENDER
    msg["To"] = RECEIVER
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
        server.starttls()
        server.login(SENDER, EMAIL_PASSWORD)
        server.sendmail(SENDER, RECEIVER, msg.as_string())
        server.quit()
        log_event("📧 Email sent successfully.")
    except Exception as e:
        log_event(f"❌ Email error: {e}")

# ===== Core checker =====
def check_for_job_change():
    headers = {"User-Agent": "Mozilla/5.0 (Safe2 Job Notifier)"}
    try:
        resp = requests.get(URL, headers=headers, timeout=30)
        soup = BeautifulSoup(resp.content, "html.parser")
        full_text_raw = soup.get_text(separator=" ", strip=True)

        # If the explicit "no jobs" banner is there, do nothing
        if NO_JOB_TEXT and NO_JOB_TEXT in full_text_raw:
            log_event("🔄 Still same message. Will check again.")
            return False

        # Extract all postcodes that appear on the page
        found_pcs = {
            m.group(1).upper().replace("  ", " ").strip()
            for m in re.finditer(UK_PC_RE, full_text_raw, flags=re.I)
        }

        # If we found no postcodes but the "no jobs" banner isn't there,
        # treat it as potential new job to avoid missing anything.
        if not found_pcs:
            log_event("⚠️ No postcodes found but 'no jobs' banner missing. Sending alert just in case.")
            message = f"🚨 New job detected (no postcode parsed). Check your portal: {URL}"
            send_email_notification(message)
            send_telegram_alert(message)
            return True

        # Filter out ignored postcodes; alert if at least one non-ignored is present
        non_ignored = sorted(pc for pc in found_pcs if pc not in IGNORED_POSTCODES)

        if non_ignored:
            pcs_str = ", ".join(non_ignored)
            log_event(f"🚨 New job(s) found for postcodes: {pcs_str}")
            message = f"🚨 New job(s) found: {pcs_str}\nCheck your portal: {URL}"
            send_email_notification(message)
            send_telegram_alert(message)
            log_event("✅ Alerts sent.")
            return True
        else:
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

# Start checker reliably on Render after the first web request
@app.before_first_request
def activate_job_checker():
    threading.Thread(target=start_job_checker, daemon=True).start()

# ===== Flask routes =====
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
