import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
from flask import Flask

# Safe2 Job Page URL
URL = "https://portal.safe2.co.uk/trade/8483/ZKfVPrdTaL59/new"
NO_JOB_TEXT = "Sorry, all jobs have currently be taken in your area. We will contact you when we receive more jobs."
IGNORE_JOB_TEXT = "22 Edgefield, West Allotment, Newcastle upon Tyne, NE27 0BT, Newcastle upon Tyne, NE27 0BT"

# Email
sender_email = "tariqul33-3932@diu.edu.bd"
receiver_email = "tariqul4gb@gmail.com"
app_password = "idzb ijmt uuxk woxe"

# Telegram
bot_token = '7665169639:AAHI3Yq9pT_evTdS0YNFSOofphwB5oqU25s'


def log_event(msg):
    print(f"[{datetime.now()}] {msg}")

def send_telegram_alert():
    chat_ids = ['7411017538', '7323694401']  # Add as many chat_ids as you like
    message = "🚨 A new job has been posted on Safe2. Check your portal now: https://portal.safe2.co.uk/trade/8483/ZKfVPrdTaL59/new"

    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {'chat_id': chat_id, 'text': message}
            response = requests.post(url, data=data)
            if response.status_code == 200:
                log_event(f"📲 Telegram alert sent to {chat_id}")
            else:
                log_event(f"❌ Telegram alert failed for {chat_id}. Status: {response.status_code}")
        except Exception as e:
            log_event(f"❌ Telegram error for {chat_id}: {e}")


def send_email_notification():
    subject = "✅ New Safe2 Job Available!"
    body = "A new job has been posted on Safe2. Check your portal now: https://portal.safe2.co.uk/trade/8483/ZKfVPrdTaL59/new"

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
        full_text = soup.get_text(separator=' ', strip=True)

        if NO_JOB_TEXT not in full_text:
            if IGNORE_JOB_TEXT in full_text:
                log_event("⚠️ Ignored job detected (Watling Street). No notification sent.")
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

# Background thread for checking job
def start_job_checker():
    while True:
        check_for_job_change()
        time.sleep(30)

# Start thread
threading.Thread(target=start_job_checker).start()

# Flask web server to stay alive
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Safe2 Job Notifier is running and alive."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
