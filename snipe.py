import os
import json
import requests
import time
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
import asyncio

# CONFIG
TELEGRAM_TOKEN = "TOKEN" # Enter the token from @BotFather bot in id:token format
TELEGRAM_CHAT_ID = "ID" # Get it in @GetAnyTelegramIdBot bot (YOUR TELEGRAM ACCOUNT ID)
CATEGORY = "Featured"
LIMIT = 28
LOOP_DELAY = 5  # seconds
SEEN_FILE = "seen_items.json"

SEARCH_URL = f"https://ecsr.io/apisite/catalog/v1/search/items?category={CATEGORY}&limit={LIMIT}&sortType=0"
DETAILS_URL = "https://ecsr.io/apisite/catalog/v1/catalog/items/details"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/json"
}

seen_items = set()

if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, "r") as f:
        try:
            seen_items = set(json.load(f))
        except json.JSONDecodeError:
            seen_items = set()


def get_session_and_csrf():
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        resp = session.post(DETAILS_URL, json={"items": []})
        resp.raise_for_status()
    except requests.HTTPError:
        pass

    csrf_token = resp.headers.get("x-csrf-token")
    if not csrf_token:
        print("❌ Failed to get CSRF token")
        return None, None

    session.headers["x-csrf-token"] = csrf_token
    return session, csrf_token


def fetch_asset_ids(session):
    resp = session.get(SEARCH_URL)
    resp.raise_for_status()
    data = resp.json()
    return [{"itemType": item["itemType"], "id": item["id"]} for item in data["data"]]


def fetch_item_details(session, items):
    if not items:
        return []

    payload = {"items": items}
    resp = session.post(DETAILS_URL, json=payload)

    if resp.status_code == 403:
        print("⚠ 403 Forbidden → refreshing CSRF token...")
        new_session, new_csrf = get_session_and_csrf()
        if new_session:
            session.headers.update(new_session.headers)
            resp = session.post(DETAILS_URL, json=payload)
            if resp.status_code == 403:
                print("❌ Still forbidden after CSRF refresh.")
                return []
        else:
            return []

    resp.raise_for_status()
    return resp.json().get("data", [])


def format_item_message(item):
    name = item["name"]
    item_id = item["id"]
    price_value = item.get("price") or item.get("priceTickets") or 0
    price = "Free" if price_value == 0 else price_value
    creator = item["creatorName"]

    color = "🟢" if price_value == 0 else "🔴"

    restrictions_list = item.get("itemRestrictions", [])
    if restrictions_list == ["Limited"]:
        restrictions_str = "Yes"
    elif restrictions_list == ["LimitedUnique"]:
        restrictions_str = "Yes, Unique"
    else:
        restrictions_str = "No"

    offsale = item.get("offsaleDeadline")
    offsale_str = f"\n⏰ Offsale Deadline: {offsale}" if offsale else ""

    return (
        f"{color} *{name}*\n"
        f"🆔 ID: {item_id}\n"
        f"💰 Price: {price}\n"
        f"👤 Creator: {creator}\n"
        f"📛 Limited: {restrictions_str}\n"
        f"🔗 [Link](https://ecsr.io/catalog/{item_id}/123)"
        f"{offsale_str}"
    )


async def send_telegram_message(bot, message):
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message,
        parse_mode=ParseMode.MARKDOWN,
    )


async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    session, csrf_token = get_session_and_csrf()
    if not session:
        print("❌ Cannot continue without session/CSRF")
        return

    last_refresh = time.time()
    REFRESH_INTERVAL = 90  # seconds

    while True:
        try:
            if time.time() - last_refresh >= REFRESH_INTERVAL:
                print("🔄 Refreshing CSRF token...")
                session, csrf_token = get_session_and_csrf()
                if not session:
                    print("❌ Failed to refresh CSRF token. Retrying next loop...")
                else:
                    print("✅ CSRF token refreshed.")
                last_refresh = time.time()

            print(f"🚀 Fetching asset IDs at {datetime.now()}...")
            assets = fetch_asset_ids(session)
            new_assets = [a for a in assets if a["id"] not in seen_items]

            if not new_assets:
                print("No new items found.")
            else:
                print(f"✅ Found {len(new_assets)} new items. Fetching details...")
                details = fetch_item_details(session, new_assets)

                if not details:
                    print("❌ No details returned. Likely session/CSRF issue.")
                else:
                    for item in details:
                        msg = format_item_message(item)
                        await send_telegram_message(bot, msg)
                        seen_items.add(item["id"])
                        with open(SEEN_FILE, "w") as f:
                            json.dump(list(seen_items), f)
                        print(f"Sent: {item['name']}")

        except requests.HTTPError as e:
            print(f"❌ HTTP error: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")

        await asyncio.sleep(LOOP_DELAY)


if __name__ == "__main__":
    asyncio.run(main())
