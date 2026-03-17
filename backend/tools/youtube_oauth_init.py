from pathlib import Path
import json

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

CLIENT_SECRET_FILE = Path("credentials/youtube_client_secret.json")
TOKEN_FILE = Path("credentials/youtube_token.json")

def main():
    if not CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(f"Не найден файл: {CLIENT_SECRET_FILE.resolve()}")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_FILE),
        SCOPES,
    )

    creds = flow.run_local_server(port=0)

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    print("Готово.")
    print("Токен сохранён в:", TOKEN_FILE.resolve())

if __name__ == "__main__":
    main()