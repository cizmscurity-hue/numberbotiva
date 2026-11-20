# -*- coding: utf-8 -*-
import asyncio
import re
import httpx
from bs4 import BeautifulSoup
import time
import json
import os
import traceback
from urllib.parse import urljoin
from datetime import datetime, timedelta
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

# --- Configuration ---
YOUR_BOT_TOKEN = os.getenv("BOT_TOKEN", "9182701401:AAESHZWWv8Ggtjsu9MQ-p755NTShfz2dKc0")

ADMIN_CHAT_IDS = ["7958819352"]
INITIAL_CHAT_IDS = ["-1003942424151"]  # ✅ fixed double minus

LOGIN_URL = "https://www.ivasms.com/login"
BASE_URL = "https://www.ivasms.com/"
SMS_API_ENDPOINT = "https://www.ivasms.com/portal/sms/received/getsms"

USERNAME = os.getenv("IVASMS_USER", "imodumicheal519@gmail.com")
PASSWORD = os.getenv("IVASMS_PASS", "Aliumicheal23")

POLLING_INTERVAL_SECONDS = 2
STATE_FILE = "processed_sms_ids.json"
CHAT_IDS_FILE = "chat_ids.json"

INLINE_BUTTONS = [
    InlineKeyboardButton("📱 NUMBER CHANNEL", url="https://t.me/mrafrixtech"),
    InlineKeyboardButton("BACKUP CHANNEL", url="https://t.me/auroratechinc"),
    InlineKeyboardButton("OTP GROUP", url="https://t.me/afrixotpgc"),
    InlineKeyboardButton("CONTACT DEV", url="https://t.me/jaden_afrix"),
]

# ... COUNTRY_FLAGS, SERVICE_KEYWORDS, SERVICE_EMOJIS tetap sama ...

# --- Utility (dipindah ke atas agar pasti tersedia) ---
def escape_markdown(text):
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

def load_chat_ids():
    if not os.path.exists(CHAT_IDS_FILE):
        with open(CHAT_IDS_FILE, 'w') as f:
            json.dump(INITIAL_CHAT_IDS, f)
        return INITIAL_CHAT_IDS
    try:
        with open(CHAT_IDS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return INITIAL_CHAT_IDS

def save_chat_ids(chat_ids):
    with open(CHAT_IDS_FILE, 'w') as f:
        json.dump(chat_ids, f, indent=4)

def load_processed_ids():
    if not os.path.exists(STATE_FILE):
        return set()
    try:
        with open(STATE_FILE, 'r') as f:
            return set(json.load(f))
    except (json.JSONDecodeError, FileNotFoundError):
        return set()

def save_processed_id(sms_id):
    ids = load_processed_ids()
    ids.add(sms_id)
    with open(STATE_FILE, 'w') as f:
        json.dump(list(ids), f)

# --- Telegram Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    keyboard = [[btn] for btn in INLINE_BUTTONS]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if str(user_id) in ADMIN_CHAT_IDS:
        await update.message.reply_text(
            "Welcome Admin!\nCommands:\n/add_chat <chat_id>\n/remove_chat <chat_id>\n/list_chats",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("Sorry, you are not authorized.", reply_markup=reply_markup)

async def add_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Only admins can use this.")
        return
    try:
        new_chat_id = context.args[0]
        chat_ids = load_chat_ids()
        if new_chat_id not in chat_ids:
            chat_ids.append(new_chat_id)
            save_chat_ids(chat_ids)
            await update.message.reply_text(f"✅ Added {new_chat_id}.")
        else:
            await update.message.reply_text(f"⚠️ {new_chat_id} already in list.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Use: /add_chat <chat_id>")

async def remove_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Only admins can use this.")
        return
    try:
        cid = context.args[0]
        chat_ids = load_chat_ids()
        if cid in chat_ids:
            chat_ids.remove(cid)
            save_chat_ids(chat_ids)
            await update.message.reply_text(f"✅ Removed {cid}.")
        else:
            await update.message.reply_text(f"🤔 {cid} not found.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Use: /remove_chat <chat_id>")

async def list_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Only admins can use this.")
        return
    chat_ids = load_chat_ids()
    if chat_ids:
        message = "📜 Registered chat IDs:\n" + "\n".join(f"- `{escape_markdown(str(c))}`" for c in chat_ids)
        try:
            await update.message.reply_text(message, parse_mode='MarkdownV2')
        except Exception:
            await update.message.reply_text("📜 Chat IDs:\n" + "\n".join(map(str, chat_ids)))
    else:
        await update.message.reply_text("No chat IDs registered.")

# --- Core ---
async def fetch_sms_from_api(client: httpx.AsyncClient, headers: dict, csrf_token: str):
    all_messages = []
    try:
        today = datetime.utcnow()
        start_date = today - timedelta(days=1)
        from_date_str = start_date.strftime('%m/%d/%Y')
        to_date_str = today.strftime('%m/%d/%Y')

        first_payload = {'from': from_date_str, 'to': to_date_str, '_token': csrf_token}
        summary_response = await client.post(SMS_API_ENDPOINT, headers=headers, data=first_payload)
        summary_response.raise_for_status()
        summary_soup = BeautifulSoup(summary_response.text, 'html.parser')
        group_divs = summary_soup.find_all('div', {'class': 'pointer'})
        if not group_divs:
            return []

        # ✅ Fixed regex
        pattern = re.compile(r"getDetials\('(.+?)'\)")
        group_ids = []
        for div in group_divs:
            m = pattern.search(div.get('onclick', ''))
            if m:
                group_ids.append(m.group(1))

        numbers_url = urljoin(BASE_URL, "portal/sms/received/getsms/number")
        sms_url = urljoin(BASE_URL, "portal/sms/received/getsms/number/sms")

        for group_id in group_ids:
            numbers_payload = {'start': from_date_str, 'end': to_date_str, 'range': group_id, '_token': csrf_token}
            numbers_response = await client.post(numbers_url, headers=headers, data=numbers_payload)
            numbers_soup = BeautifulSoup(numbers_response.text, 'html.parser')
            number_divs = numbers_soup.select("div[onclick*='getDetialsNumber']")
            if not number_divs:
                continue
            phone_numbers = [div.text.strip() for div in number_divs]

            for phone_number in phone_numbers:
                sms_payload = {'start': from_date_str, 'end': to_date_str, 'Number': phone_number,
                               'Range': group_id, '_token': csrf_token}
                sms_response = await client.post(sms_url, headers=headers, data=sms_payload)
                sms_soup = BeautifulSoup(sms_response.text, 'html.parser')
                for card in sms_soup.find_all('div', class_='card-body'):
                    sms_text_p = card.find('p', class_='mb-0')
                    if not sms_text_p:
                        continue
                    sms_text = sms_text_p.get_text(separator='\n').strip()
                    date_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

                    country_name_match = re.match(r'([a-zA-Z\s]+)', group_id)
                    country_name = country_name_match.group(1).strip() if country_name_match else group_id.strip()

                    service = "Unknown"
                    lower_sms = sms_text.lower()
                    for svc, kws in SERVICE_KEYWORDS.items():
                        if any(k in lower_sms for k in kws):
                            service = svc
                            break

                    # ✅ Prioritas pola OTP
                    code_match = (
                        re.search(r'\b(\d{3}-\d{3})\b', sms_text)
                        or re.search(r'(?:code|otp|pin)[^\d]{0,10}(\d{4,8})', lower_sms)
                        or re.search(r'\b(\d{4,8})\b', sms_text)
                    )
                    code = code_match.group(1) if code_match else "N/A"

                    unique_id = f"{phone_number}-{hash(sms_text)}-{date_str}"
                    flag = COUNTRY_FLAGS.get(country_name, "🏴‍☠️")

                    all_messages.append({
                        "id": unique_id, "time": date_str, "number": phone_number,
                        "country": country_name, "flag": flag, "service": service,
                        "code": code, "full_sms": sms_text
                    })
        return all_messages
    except httpx.RequestError as e:
        print(f"❌ Network issue: {e}")
        return []
    except Exception as e:
        print(f"❌ Error in fetch: {e}")
        traceback.print_exc()
        return []

async def send_telegram_message(context: ContextTypes.DEFAULT_TYPE, chat_id: str, message_data: dict):
    try:
        time_str = message_data.get("time", "N/A")
        number_str = message_data.get("number", "N/A")
        country_name = message_data.get("country", "N/A")
        flag_emoji = message_data.get("flag", "🏴‍☠️")
        service_name = message_data.get("service", "N/A")
        code_str = message_data.get("code", "N/A")
        full_sms_text = message_data.get("full_sms", "N/A")
        service_emoji = SERVICE_EMOJIS.get(service_name, "❓")

        full_message = (
            f"🔔 *You have successfully received OTP*\n\n"
            f"📞 *Number:* `{escape_markdown(number_str)}`\n"
            f"🔑 *Code:* `{escape_markdown(code_str)}`\n"
            f"🏆 *Service:* {service_emoji} {escape_markdown(service_name)}\n"
            f"🌎 *Country:* {escape_markdown(country_name)} {flag_emoji}\n"
            f"⏳ *Time:* `{escape_markdown(time_str)}`\n\n"
            f"💬 *Message:*\n"
            rf"\`\`\`\n{full_sms_text}\n\`\`\`"
        )

        keyboard = [[btn] for btn in INLINE_BUTTONS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id, text=full_message,
            parse_mode='MarkdownV2', reply_markup=reply_markup
        )
    except Exception as e:
        print(f"❌ Error sending to {chat_id}: {e}")

# --- Job ---
async def check_sms_job(context: ContextTypes.DEFAULT_TYPE):
    print(f"\n--- [{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Checking ---")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            print("ℹ️ Logging in...")
            login_page_res = await client.get(LOGIN_URL, headers=headers)
            soup = BeautifulSoup(login_page_res.text, 'html.parser')
            token_input = soup.find('input', {'name': '_token'})
            login_data = {'email': USERNAME, 'password': PASSWORD}
            if token_input:
                login_data['_token'] = token_input['value']

            login_res = await client.post(LOGIN_URL, data=login_data, headers=headers)

            # ✅ Cek login lebih robust
            dashboard_soup = BeautifulSoup(login_res.text, 'html.parser')
            csrf_meta = dashboard_soup.find('meta', {'name': 'csrf-token'})
            if not csrf_meta:
                print("❌ Login failed or CSRF token not found.")
                return

            print("✅ Login OK")
            csrf_token = csrf_meta.get('content')
            headers['Referer'] = str(login_res.url)

            messages = await fetch_sms_from_api(client, headers, csrf_token)
            if not messages:
                print("✔️ No new messages.")
                return

            processed_ids = load_processed_ids()
            chat_ids_to_send = load_chat_ids()
            new_count = 0

            for msg in reversed(messages):
                if msg["id"] not in processed_ids:
                    new_count += 1
                    print(f"✔️ New SMS from {msg['number']}")
                    for cid in chat_ids_to_send:
                        await send_telegram_message(context, cid, msg)
                    save_processed_id(msg["id"])

            if new_count:
                print(f"✅ Sent {new_count} new messages.")

        except httpx.RequestError as e:
            print(f"❌ Network: {e}")
        except Exception as e:
            print(f"❌ Main process error: {e}")
            traceback.print_exc()

# --- Entry ---
def main():
    print("🚀 Bot starting...")
    if not ADMIN_CHAT_IDS:
        print("🔴 ADMIN_CHAT_IDS is empty!")
        return

    application = Application.builder().token(YOUR_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("add_chat", add_chat_command))
    application.add_handler(CommandHandler("remove_chat", remove_chat_command))
    application.add_handler(CommandHandler("list_chats", list_chats_command))

    try:
        jq = application.job_queue
        if jq is not None:
            jq.run_repeating(check_sms_job, interval=POLLING_INTERVAL_SECONDS, first=1)
            print(f"✅ Polling every {POLLING_INTERVAL_SECONDS}s.")
        else:
            print("❌ JobQueue not available. Install: pip install 'python-telegram-bot[job-queue]'")
    except Exception as e:
        print(f"❌ JobQueue setup error: {e}")
        traceback.print_exc()

    print("🤖 Bot online.")
    application.run_polling()

if __name__ == "__main__":
    main()