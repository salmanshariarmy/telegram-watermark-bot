import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

WEBAPP_URL = os.getenv("WEBAPP_URL")

MAX_FILE_SIZE = int(
    os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024))
)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not WEBAPP_URL:
    raise RuntimeError("WEBAPP_URL is missing")
