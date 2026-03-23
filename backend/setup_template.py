"""
setup_template.py — Creates the TenderAlert Pro WhatsApp message template via Meta API.

Run ONCE after getting your WABA ID from the Meta console:
  python setup_template.py --waba-id <YOUR_WABA_ID>

To find your WABA ID:
  1. Go to developers.facebook.com/apps → your app
  2. Left sidebar → WhatsApp → API Setup
  3. Copy the "WhatsApp Business Account ID" (a long number like 123456789012345)

Template created: tender_daily_alert
  Header  : TenderAlert Pro
  Body    : {{1}} new Rwanda government tenders are ready for you today.
            Tap below to get your AI-powered eligibility digest.
  Footer  : Rwanda RPPA | Umucyo Platform
  Buttons : [Get Today's Digest] [Change My Sectors] [Unsubscribe]
"""

import sys
import json
import requests

sys.path.insert(0, ".")
from config import WHATSAPP_TOKEN

TEMPLATE_NAME = "procurement_notice"
TEMPLATE_LANG = "en_US"

TEMPLATE_PAYLOAD = {
    "name": TEMPLATE_NAME,
    "language": TEMPLATE_LANG,
    "category": "UTILITY",
    "components": [
        {
            "type": "HEADER",
            "format": "TEXT",
            "text": "TenderAlert Pro",
        },
        {
            "type": "BODY",
            "text": (
                "Daily update: *{{1}} new government procurement notice(s)* have been published "
                "on Rwanda's Umucyo platform. Select an option below to manage your subscription."
            ),
            "example": {
                "body_text": [["5"]]
            },
        },
        {
            "type": "FOOTER",
            "text": "Rwanda RPPA | Umucyo Platform",
        },
        {
            "type": "BUTTONS",
            "buttons": [
                {
                    "type": "QUICK_REPLY",
                    "text": "Get Today's Digest",
                },
                {
                    "type": "QUICK_REPLY",
                    "text": "Change My Sectors",
                },
                {
                    "type": "QUICK_REPLY",
                    "text": "Unsubscribe",
                },
            ],
        },
    ],
}


def create_template(waba_id: str) -> None:
    url = f"https://graph.facebook.com/v19.0/{waba_id}/message_templates"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    print(f"Creating template '{TEMPLATE_NAME}' for WABA {waba_id}...")
    resp = requests.post(url, json=TEMPLATE_PAYLOAD, headers=headers, timeout=15)
    data = resp.json()

    if resp.status_code in (200, 201):
        print(f"SUCCESS!")
        print(f"  Template ID : {data.get('id')}")
        print(f"  Status      : {data.get('status')}")
        print()
        if data.get("status") == "APPROVED":
            print("Template is APPROVED and ready to use immediately.")
        else:
            print("Template is PENDING review — usually approved within a few minutes.")
        print()
        print("Once approved, the code is ready. Run:")
        print("  python -X utf8 main.py --test-whatsapp")
    else:
        err = data.get("error", {})
        print(f"FAILED: {err.get('code')} — {err.get('message')}")
        if err.get("code") == 100:
            print("  Tip: Check the WABA ID is correct.")
        elif err.get("code") == 80004:
            print(f"  Template '{TEMPLATE_NAME}' may already exist. Check Meta console.")


def list_templates(waba_id: str) -> None:
    url = f"https://graph.facebook.com/v19.0/{waba_id}/message_templates"
    resp = requests.get(
        url,
        params={"access_token": WHATSAPP_TOKEN, "fields": "name,status,category"},
        timeout=10,
    )
    data = resp.json()
    if "data" in data:
        print(f"Existing templates for WABA {waba_id}:")
        for t in data["data"]:
            print(f"  {t['name']:30s}  {t['status']:12s}  {t['category']}")
    else:
        print("Could not list templates:", data)


if __name__ == "__main__":
    args = sys.argv[1:]

    waba_id = None
    if "--waba-id" in args:
        idx = args.index("--waba-id")
        if idx + 1 < len(args):
            waba_id = args[idx + 1]

    if not waba_id:
        print(__doc__)
        print()
        print("Usage: python setup_template.py --waba-id <YOUR_WABA_ID>")
        print("       python setup_template.py --waba-id <ID> --list   (list existing templates)")
        sys.exit(1)

    if "--list" in args:
        list_templates(waba_id)
    else:
        create_template(waba_id)
