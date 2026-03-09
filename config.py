from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import os


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass
class BotConfig:
    token: str


@dataclass
class KieConfig:
    api_key: str
    base_url: str = "https://api.kie.ai/api/v1"
    callback_url: Optional[str] = None
    model: str = "nano-banana-pro"


@dataclass
class Settings:
    bot: BotConfig
    kie: KieConfig
    db_url: str


def get_settings() -> Settings:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    kie_api_key = os.getenv("KIE_API_KEY")
    kie_callback_url = os.getenv("KIE_CALLBACK_URL")

    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "3306")
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "imgai_bot")

    db_url = (
        f"mysql+aiomysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    )

    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment")
    if not kie_api_key:
        raise RuntimeError("KIE_API_KEY is not set in environment")

    return Settings(
        bot=BotConfig(token=bot_token),
        kie=KieConfig(
            api_key=kie_api_key,
            callback_url=kie_callback_url,
        ),
        db_url=db_url,
    )

