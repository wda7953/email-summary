"""
每天 9:00 / 16:00 台灣時間讀取 Gmail，摘要後傳送至 LINE
"""
import os
import json
import requests
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import re

# ── 環境變數 ──────────────────────────────────────────────
GMAIL_CLIENT_ID     = os.environ["GMAIL_CLIENT_ID"]
GMAIL_CLIENT_SECRET = os.environ["GMAIL_CLIENT_SECRET"]
GMAIL_REFRESH_TOKEN = os.environ["GMAIL_REFRESH_TOKEN"]
LINE_TOKEN          = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID        = os.environ["LINE_USER_ID"]

# ── Gmail 初始化 ──────────────────────────────────────────
def get_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=GMAIL_REFRESH_TOKEN,
        client_id=GMAIL_CLIENT_ID,
        client_secret=GMAIL_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds)

def decode_body(data):
    """解碼 base64url 郵件內容"""
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    except Exception:
        return ""

def get_text_from_payload(payload):
    """從 payload 遞迴取得純文字"""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return decode_body(data) if data else ""
    for part in payload.get("parts", []):
        text = get_text_from_payload(part)
        if text:
            return text
    return ""

def shorten_sender(sender):
    """只保留名稱或信箱前半段，去掉角括號"""
    # "王小明 <abc@gmail.com>" → "王小明"
    # "<abc@gmail.com>" → "abc@gmail.com"
    m = re.match(r'^"?([^"<]+)"?\s*<', sender)
    if m:
        name = m.group(1).strip()
        if name:
            return name
    m2 = re.search(r'<([^>]+)>', sender)
    if m2:
        return m2.group(1)
    return sender.strip()

def fetch_recent_emails(service, hours=7):
    """取得最近 hours 小時內的郵件"""
    since = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
    query = f"in:inbox after:{since}"

    result = service.users().messages().list(
        userId="me", q=query, maxResults=30
    ).execute()

    messages = result.get("messages", [])
    emails = []

    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        subject = headers.get("Subject", "(無主旨)")
        sender  = headers.get("From", "未知寄件者")
        labels  = detail.get("labelIds", [])

        # 判斷來源：有 Outlook 標籤的是從 Outlook 轉寄來的
        source = "Outlook" if any("Outlook" in l for l in labels) else "Gmail"

        body = get_text_from_payload(detail["payload"])
        snippet = re.sub(r'\s+', ' ', body).strip()[:40]

        emails.append({
            "source": source,
            "sender": shorten_sender(sender),
            "subject": subject,
            "snippet": snippet,
        })

    return emails

# ── LINE 傳送 ─────────────────────────────────────────────
def send_line_message(text):
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_TOKEN}",
        },
        json={
            "to": LINE_USER_ID,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=10,
    )

# ── 主程式 ────────────────────────────────────────────────
def format_section(title, mails, timestamp):
    """格式化單一來源的郵件區塊"""
    blocks = [f"【{title}】 {timestamp}｜共 {len(mails)} 封"]
    for i, e in enumerate(mails, 1):
        block = f"\n({i})     {e['sender']}\n<{e['subject']}>"
        if e.get("snippet"):
            block += f"\n|{e['snippet'][:30]}|"
        blocks.append(block)
    return "\n".join(blocks)


def main():
    service = get_gmail_service()
    now_tw = datetime.now(timezone(timedelta(hours=8)))
    emails = fetch_recent_emails(service, hours=24)

    timestamp = now_tw.strftime('%m/%d %H:%M')

    if not emails:
        send_line_message(f"📭 {timestamp} 郵件摘要\n沒有新郵件。")
        return

    gmail_mails   = [e for e in emails if e["source"] == "Gmail"]
    outlook_mails = [e for e in emails if e["source"] == "Outlook"]

    sections = []
    if gmail_mails:
        sections.append(format_section("Gmail", gmail_mails, timestamp))
    if outlook_mails:
        sections.append(format_section("Outlook", outlook_mails, timestamp))

    send_line_message("\n\n".join(sections))
    print(f"已傳送 {len(emails)} 封郵件摘要至 LINE")

if __name__ == "__main__":
    main()
