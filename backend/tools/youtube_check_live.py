from pathlib import Path
import json

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
TOKEN_FILE = Path("credentials/youtube_token.json")


def main():
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"Не найден токен: {TOKEN_FILE.resolve()}")

    creds_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)

    youtube = build("youtube", "v3", credentials=creds)

    response = youtube.liveBroadcasts().list(
        part="id,snippet,status",
        mine=True,
        maxResults=50
    ).execute()

    items = response.get("items", [])
    if not items:
        print("Вообще не найдено ни одной трансляции у этого аккаунта.")
        return

    print("НАЙДЕННЫЕ ТРАНСЛЯЦИИ:")
    print("-" * 60)

    live_broadcast = None

    for item in items:
        broadcast_id = item.get("id")
        snippet = item.get("snippet", {})
        status = item.get("status", {})

        title = snippet.get("title")
        live_chat_id = snippet.get("liveChatId")
        life_cycle_status = status.get("lifeCycleStatus")
        privacy_status = status.get("privacyStatus")

        print(f"broadcast_id: {broadcast_id}")
        print(f"title: {title}")
        print(f"lifeCycleStatus: {life_cycle_status}")
        print(f"privacyStatus: {privacy_status}")
        print(f"liveChatId: {live_chat_id}")
        print("-" * 60)

        if life_cycle_status == "live":
            live_broadcast = item

    if not live_broadcast:
        print("Сейчас активный LIVE эфир не найден.")
        return

    snippet = live_broadcast.get("snippet", {})
    print("АКТИВНЫЙ ЭФИР НАЙДЕН")
    print("broadcast_id:", live_broadcast.get("id"))
    print("title:", snippet.get("title"))
    print("liveChatId:", snippet.get("liveChatId"))


if __name__ == "__main__":
    main()