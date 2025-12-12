import os
import sys
import csv
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv # type: ignore
import time
import traceback
import random

# =========================
# Config and setup
# =========================

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_NAME = os.getenv("FROM_NAME", "Shoeb")
MAX_EMAILS_PER_RUN = int(os.getenv("MAX_EMAILS_PER_RUN", 30))

# tracking + random delay configs
VERCEL_PIXEL_BASE = os.getenv("VERCEL_PIXEL_BASE", "https://your-vercel-app.vercel.app/api/pixel")
DELAY_MIN_SECONDS = int(os.getenv("DELAY_MIN_SECONDS", 7))
DELAY_MAX_SECONDS = int(os.getenv("DELAY_MAX_SECONDS", 22))

DB_PATH = "emails.db"

RESEND_MAIN_AFTER_DAYS = 2
FOLLOWUP_AFTER_DAYS = 4
MAX_FOLLOWUPS = 4  # you can adjust this


# =========================
# Simple progress bar
# =========================

def progress_bar(current, total, prefix=""):
    if total == 0:
        return
    bar_length = 40
    fraction = current / total
    filled_length = int(bar_length * fraction)
    bar = "#" * filled_length + "-" * (bar_length - filled_length)
    percent = int(fraction * 100)
    sys.stdout.write(f"\r{prefix} [{bar}] {percent}% ({current}/{total})")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")


# =========================
# Human-like delay
# =========================

def human_delay():
    delay = random.randint(DELAY_MIN_SECONDS, DELAY_MAX_SECONDS)
    time.sleep(delay)


# =========================
# Database helpers
# =========================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            domain_name TEXT NOT NULL,
            first_name TEXT,
            vertical TEXT,
            template_index INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'new',
            opened INTEGER NOT NULL DEFAULT 0,
            replied INTEGER NOT NULL DEFAULT 0,
            last_email_sent_at TEXT,
            followup_count INTEGER NOT NULL DEFAULT 0,
            tracking_id TEXT
        );
    """)
    conn.commit()
    conn.close()


def add_lead(email, domain_name, first_name=None, vertical=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    tracking_id = f"{email}-{int(datetime.utcnow().timestamp())}"
    if vertical is None or vertical.strip() == "":
        vertical = detect_vertical(domain_name)
    template_index = 0  # will rotate among 0,1,2
    try:
        c.execute("""
            INSERT INTO leads (email, domain_name, first_name, vertical, template_index, tracking_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (email, domain_name, first_name, vertical, template_index, tracking_id))
        conn.commit()
    except Exception as e:
        print(f"Error inserting lead {email}: {e}")
    finally:
        conn.close()


def get_leads_for_initial_send(limit):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, email, domain_name, first_name, vertical, template_index, tracking_id
        FROM leads
        WHERE status = 'new'
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_leads_for_followup(limit):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, email, domain_name, first_name, vertical, status, opened, replied,
               last_email_sent_at, followup_count, tracking_id
        FROM leads
        WHERE replied = 0
          AND status IN ('initial_sent', 'followup')
          AND followup_count < ?
        LIMIT ?
    """, (MAX_FOLLOWUPS, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def get_all_leads():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT email, domain_name, vertical, opened, replied, followup_count, last_email_sent_at, status
        FROM leads
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def update_after_send(lead_id, new_status, followup_increment=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    try:
        if followup_increment:
            c.execute("""
                UPDATE leads
                SET status = ?, last_email_sent_at = ?, followup_count = followup_count + 1
                WHERE id = ?
            """, (new_status, now_str, lead_id))
        else:
            c.execute("""
                UPDATE leads
                SET status = ?, last_email_sent_at = ?
                WHERE id = ?
            """, (new_status, now_str, lead_id))
        conn.commit()
    except Exception as e:
        print(f"Error updating lead {lead_id}: {e}")
    finally:
        conn.close()


def bump_template_index(lead_id, current_index):
    new_index = (current_index + 1) % 3
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            UPDATE leads
            SET template_index = ?
            WHERE id = ?
        """, (new_index, lead_id))
        conn.commit()
    except Exception as e:
        print(f"Error updating template_index for {lead_id}: {e}")
    finally:
        conn.close()


def mark_opened(tracking_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            UPDATE leads
            SET opened = 1
            WHERE tracking_id = ?
        """, (tracking_id,))
        conn.commit()
    except Exception as e:
        print(f"Error marking opened for tracking_id {tracking_id}: {e}")
    finally:
        conn.close()


def mark_replied(email):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            UPDATE leads
            SET replied = 1, status = 'replied'
            WHERE email = ?
        """, (email,))
        conn.commit()
    except Exception as e:
        print(f"Error marking replied for {email}: {e}")
    finally:
        conn.close()


# =========================
# Vertical detection
# =========================

def detect_vertical(domain_name):
    dn = domain_name.lower()
    if any(word in dn for word in ["bed", "sleep", "mattress", "pillow"]):
        return "sleep"
    if any(word in dn for word in ["ai", "tech", "cloud", "data", "bot"]):
        return "ai"
    return "local"  # default catch-all


# =========================
# Email signature with LinkedIn + X
# =========================

def social_signature_html():
    linkedin_url = os.getenv("LINKEDIN_URL", "https://www.linkedin.com/in/yourprofile")
    x_url = os.getenv("X_URL", "https://x.com/yourhandle")

    # simple icon-like links (emoji placeholders)
    return f"""
    <p style="margin-top: 16px;">
      Best regards,<br>
      {FROM_NAME}<br>
      <a href="{linkedin_url}" style="text-decoration:none; margin-right:8px;">🔗 LinkedIn</a>
      <a href="{x_url}" style="text-decoration:none;">✖ X</a>
    </p>
    """


# =========================
# Tracking pixel
# =========================

def build_tracking_pixel(tracking_id):
    tracking_url = f"{VERCEL_PIXEL_BASE}?tid={tracking_id}"
    return f'<img src="{tracking_url}" width="1" height="1" style="display:none;" alt="" />'


# =========================
# Email templates
# =========================

# --- Sleep vertical templates ---

def sleep_template_1(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        I wanted to share a domain that feels like a natural fit for a sleep or bedding brand:
      </p>
      <p style="font-size:18px; font-weight:bold; margin:16px 0;">
        {domain_name}
      </p>
      <p>
        It's memorable, easy to say, and clearly connected to beds and sleep products. Names like this
        tend to convert better in ads and feel more trustworthy to customers.
      </p>
      <p>
        I'm the current owner and considering selling it to a brand that can really use it.
        Would you be open to seeing a simple price range for {domain_name}?
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


def sleep_template_2(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        Quick note: I own the domain <strong>{domain_name}</strong> and thought it could be interesting for
        a brand in the sleep, bedding, or home comfort niche.
      </p>
      <p>
        The name is clean, brandable, and intuitive — which helps with word-of-mouth, ads, and long-term branding.
      </p>
      <p>
        If it's not relevant for you right now, no worries at all. If it might be, I can send over
        a price range and we can see if it fits your plans.
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


def sleep_template_3(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        Reaching out because I own <strong>{domain_name}</strong>, which I see as a strong brand asset for anyone
        in the bed or sleep space.
      </p>
      <p>
        Short, relevant domains like this are getting harder to find, especially ones that directly match
        the product category.
      </p>
      <p>
        Are you open to a quick, no-pressure chat about this? I can share a realistic price range
        and you can decide if it's worth considering.
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


# --- AI vertical templates ---

def ai_template_1(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        I'm reaching out because I own the domain <strong>{domain_name}</strong>, which feels like a strong fit
        for an AI, SaaS, or automation product.
      </p>
      <p>
        It's short, brandable, and clearly positioned around technology — ideal for marketing, investor decks,
        and long-term branding.
      </p>
      <p>
        I'm open to selling it to the right team. Would you be interested in seeing a simple price range
        for {domain_name}?
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


def ai_template_2(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        Quick message: I own <strong>{domain_name}</strong> and thought it could be a meaningful upgrade
        or launch name for an AI/tech product.
      </p>
      <p>
        A strong domain often makes a difference in perceived credibility, especially when you’re pitching
        customers or partners.
      </p>
      <p>
        If it's not a fit, no problem. If it is, I'm happy to share a price range and next steps.
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


def ai_template_3(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        I won't take much of your time — I own <strong>{domain_name}</strong>, a name that aligns well with
        AI and modern software products.
      </p>
      <p>
        Names like this can be hard to secure later, once a product has already grown.
      </p>
      <p>
        Would you like me to send over a quick price range so you can see if it’s worth exploring?
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


# --- Local/service vertical templates ---

def local_template_1(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        I came across your business and wanted to share a domain I own that could fit your market:
      </p>
      <p style="font-size:18px; font-weight:bold; margin:16px 0;">
        {domain_name}
      </p>
      <p>
        It's clear, easy to remember, and directly ties into your type of service — which helps with trust
        and local search.
      </p>
      <p>
        I'm considering selling it to a business that can put it to good use. Would you be open to seeing
        a simple price range?
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


def local_template_2(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        Quick message about the domain <strong>{domain_name}</strong> that I own. It's a straightforward,
        descriptive name that can help customers instantly understand what you offer.
      </p>
      <p>
        Domains like this often perform better in ads and word-of-mouth, especially for local or service businesses.
      </p>
      <p>
        If it's not on your roadmap, no worries. If you’re curious, I can send a price range and we can go from there.
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


def local_template_3(first_name, domain_name, pixel):
    if not first_name:
        first_name = "Hi"
    sig = social_signature_html()
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        Reaching out regarding <strong>{domain_name}</strong>, a domain I own that I think could serve as a strong
        brand or campaign name for your type of business.
      </p>
      <p>
        It’s the kind of name that’s easy to recall and straightforward to promote.
      </p>
      <p>
        Would you like me to share a quick price range so you can decide if it’s worth considering?
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """


def get_initial_template_html(vertical, template_index, first_name, domain_name, tracking_id):
    pixel = build_tracking_pixel(tracking_id)

    if vertical == "sleep":
        templates = [sleep_template_1, sleep_template_2, sleep_template_3]
    elif vertical == "ai":
        templates = [ai_template_1, ai_template_2, ai_template_3]
    else:
        templates = [local_template_1, local_template_2, local_template_3]

    func = templates[template_index % 3]
    return func(first_name, domain_name, pixel)


# =========================
# Subject lines
# =========================

def initial_subject(domain_name, vertical):
    if vertical == "sleep":
        return f"Quick question about {domain_name}"
    if vertical == "ai":
        return f"Could {domain_name} work for your product?"
    return f"About the domain {domain_name}"


def followup_subject(domain_name, follow_number):
    if follow_number == 1:
        return f"Following up on {domain_name}"
    elif follow_number == 2:
        return f"Still considering {domain_name}?"
    else:
        return f"{domain_name} — should I close this out?"


def followup_email_html(first_name, domain_name, tracking_id, follow_number):
    if not first_name:
        first_name = "Hi"
    pixel = build_tracking_pixel(tracking_id)
    sig = social_signature_html()

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.6;">
      <p>{first_name},</p>
      <p>
        Just a quick follow-up regarding the domain <strong>{domain_name}</strong> that I reached out about earlier.
      </p>
      <p>
        If the timing or fit isn’t right, no problem at all — just let me know and I’ll close the loop on my side.
        If it could be useful for your plans, I can share a simple price range and we can see if it makes sense.
      </p>
      <p>
        Would you like me to send over the price range for <strong>{domain_name}</strong>?
      </p>
      {sig}
      {pixel}
    </body>
    </html>
    """
    return html


# =========================
# Email sending
# =========================

def send_email(to_email, subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{FROM_NAME} <{SMTP_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    mime_html = MIMEText(html_body, "html")
    msg.attach(mime_html)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
    except smtplib.SMTPException as e:
        print(f"\nSMTP error sending to {to_email}: {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"\nUnexpected error sending to {to_email}: {e}")
        traceback.print_exc()
        raise


# =========================
# CSV import
# =========================

def import_from_csv(csv_path):
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}")
        return

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        total = len(rows)

        if total == 0:
            print("CSV is empty or no rows found.")
            return

        print(f"Importing {total} leads from {csv_path}...")
        for i, row in enumerate(rows, start=1):
            email = row.get("email", "").strip()
            domain_name = row.get("domain_name", "").strip()
            first_name = row.get("first_name", "").strip() or None
            vertical = row.get("vertical", "").strip() or None

            if not email or not domain_name:
                print(f"Skipping row {i}: missing email or domain_name.")
            else:
                add_lead(email, domain_name, first_name, vertical)

            progress_bar(i, total, prefix="Import progress")
        print("Import completed.")


# =========================
# Core actions
# =========================

def action_send_initial():
    leads = get_leads_for_initial_send(MAX_EMAILS_PER_RUN)
    total = len(leads)
    print(f"Found {total} leads for initial send.")

    for idx, lead in enumerate(leads, start=1):
        (lead_id, email, domain_name, first_name,
         vertical, template_index, tracking_id) = lead
        try:
            subject = initial_subject(domain_name, vertical)
            html = get_initial_template_html(vertical, template_index, first_name, domain_name, tracking_id)
            send_email(email, subject, html)
            update_after_send(lead_id, "initial_sent")
            bump_template_index(lead_id, template_index)
            progress_bar(idx, total, prefix="Sending initial emails")
            print(f"\nSent initial email to {email} ({vertical}, template {template_index + 1})")
            human_delay()
        except Exception:
            print(f"Failed to send initial email to {email}. Continuing with next.")


def action_run_followups():
    leads = get_leads_for_followup(MAX_EMAILS_PER_RUN)
    total = len(leads)
    print(f"Found {total} leads for followup processing.")
    now = datetime.utcnow()

    for idx, lead in enumerate(leads, start=1):
        (lead_id, email, domain_name, first_name, vertical,
         status, opened, replied, last_email_sent_at,
         followup_count, tracking_id) = lead

        try:
            if not last_email_sent_at:
                last_dt = now - timedelta(days=10)
            else:
                last_dt = datetime.fromisoformat(last_email_sent_at)

            days_since = (now - last_dt).days

            if replied:
                progress_bar(idx, total, prefix="Followups")
                continue

            if not opened:
                if days_since >= RESEND_MAIN_AFTER_DAYS:
                    subject = initial_subject(domain_name, vertical)
                    html = get_initial_template_html(vertical, 0, first_name, domain_name, tracking_id)
                    send_email(email, subject, html)
                    update_after_send(lead_id, "initial_sent", followup_increment=True)
                    print(f"\nResent main email to {email} (no open yet) for {domain_name}")
                    human_delay()
                progress_bar(idx, total, prefix="Followups")
                continue

            if opened and not replied:
                if days_since >= FOLLOWUP_AFTER_DAYS:
                    subject = followup_subject(domain_name, followup_count + 1)
                    html = followup_email_html(first_name, domain_name, tracking_id, followup_count + 1)
                    send_email(email, subject, html)
                    update_after_send(lead_id, "followup", followup_increment=True)
                    print(f"\nSent follow-up #{followup_count + 1} to {email} for {domain_name}")
                    human_delay()

            progress_bar(idx, total, prefix="Followups")

        except Exception:
            print(f"\nError processing followup for {email}. Continuing with next.")
            traceback.print_exc()
            progress_bar(idx, total, prefix="Followups")


# =========================
# Reporting
# =========================

def action_generate_report():
    leads = get_all_leads()
    total = len(leads)
    if total == 0:
        print("No leads found in database.")
        return

    opened_count = sum(1 for l in leads if l[3] == 1)
    replied_count = sum(1 for l in leads if l[4] == 1)
    total_followups = sum(l[5] for l in leads)
    not_opened = total - opened_count

    open_rate = (opened_count / total) * 100 if total else 0
    reply_rate = (replied_count / total) * 100 if total else 0

    print("\n========= Outreach Report =========")
    print(f"Total leads: {total}")
    print(f"Opened: {opened_count} ({open_rate:.1f}%)")
    print(f"Replied: {replied_count} ({reply_rate:.1f}%)")
    print(f"Total follow-ups sent: {total_followups}")
    print(f"Not opened: {not_opened}")
    print("===================================\n")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_filename = f"report_{timestamp}.csv"

    with open(report_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "domain_name", "vertical", "opened", "replied",
                         "followup_count", "last_email_sent_at", "status"])
        for row in leads:
            writer.writerow(row)

    print(f"Detailed report saved to: {report_filename}")
    print("\nSample rows:")
    for row in leads[:5]:
        email, domain, vertical, opened, replied, followup_count, last_sent, status = row
        print("--------------------------------------")
        print(f"Email: {email}")
        print(f"Domain: {domain}")
        print(f"Vertical: {vertical}")
        print(f"Opened: {'YES' if opened else 'NO'}")
        print(f"Replied: {'YES' if replied else 'NO'}")
        print(f"Followups Sent: {followup_count}")
        print(f"Last Email Sent: {last_sent}")
        print(f"Status: {status}")
    print("--------------------------------------")


# =========================
# Seed example leads
# =========================

def seed_example():
    example_leads = [
        ("buyer1@example.com", "BedOrder.com", "Rahul", "sleep"),
        ("buyer2@example.com", "SmartBedAI.com", "Anita", "ai"),
        ("buyer3@example.com", "CityFurnitureStore.com", None, "local"),
    ]
    for email, domain, first_name, vertical in example_leads:
        add_lead(email, domain, first_name, vertical)
    print("Seeded example leads.")


# =========================
# CLI
# =========================

def print_usage():
    print("Usage:")
    print("  python email_automation.py init_db")
    print("  python email_automation.py import_csv leads.csv")
    print("  python email_automation.py seed_example")
    print("  python email_automation.py send_initial")
    print("  python email_automation.py run_followups")
    print("  python email_automation.py report")


if __name__ == "__main__":
    init_db()

    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "init_db":
        print("Database initialized.")
    elif cmd == "import_csv":
        if len(sys.argv) < 3:
            print("Please provide CSV path.")
        else:
            import_from_csv(sys.argv[2])
    elif cmd == "seed_example":
        seed_example()
    elif cmd == "send_initial":
        action_send_initial()
    elif cmd == "run_followups":
        action_run_followups()
    elif cmd == "report":
        action_generate_report()
    else:
        print_usage()
