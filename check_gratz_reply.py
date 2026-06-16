"""
監控 Liz Lee (LizL@gratzpilates.com) 是否回覆 Gratz Order #34344
有新信就傳 LINE 通知。每小時執行，搜尋最近 90 分鐘內的來信。
"""
import os
import base64
import re
import requests
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GMAIL_CLIENT_ID     = os.environ["GMAIL_CLIENT_ID"]
GMAIL_CLIENT_SECRET = os.environ["GMAIL_CLIENT_SECRET"]
GMAIL_REFRESH_TOKEN = os.environ["GMAIL_REFRESH_TOKEN"]
LINE_TOKEN          = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID        = os.environ["LINE_USER_ID"]

SENDER_EMAIL = "LizL@gratzpilates.com"
SUBJECT_KEYWORD = "Gratz Order #34344"
CHECK_MINUTES = 90  # 搜尋最近 90 分鐘，確保不會因排程誤差漏掉


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
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    except Exception:
        return ""


def get_text_from_payload(payload):
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return decode_body(data) if data else ""
    for part in payload.get("parts", []):
        text = get_text_from_payload(part)
        if text:
            return text
    return ""


def send_line(text):
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"},
        json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": text}]},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"LINE 傳送失敗: {resp.text}")


def main():
    service = get_gmail_service()
    since_ts = int((datetime.now(timezone.utc) - timedelta(minutes=CHECK_MINUTES)).timestamp())

    query = f"from:{SENDER_EMAIL} subject:{SUBJECT_KEYWORD} after:{since_ts}"
    result = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
    messages = result.get("messages", [])

    if not messages:
        print("無新回信")
        return

    for msg in messages:
        detail = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        subject = headers.get("Subject", "(無主旨)")
        body = get_text_from_payload(detail["payload"])
        # 只取正文第一段（去掉引用的舊信）
        body_clean = body.split("________________________________")[0].strip()
        snippet = re.sub(r'\s+', ' ', body_clean)[:200]

        now_tw = datetime.now(timezone(timedelta(hours=8))).strftime('%m/%d %H:%M')
        message = (
            f"📧 Gratz 來信了！({now_tw})\n"
            f"寄件人：Liz Lee\n"
            f"主旨：{subject}\n\n"
            f"{snippet}"
        )
        send_line(message)
        print(f"已傳送通知：{subject}")


if __name__ == "__main__":
    main()
