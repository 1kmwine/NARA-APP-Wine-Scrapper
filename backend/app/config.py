from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    db_host: str
    db_port: int
    db_username: str
    db_password: str
    db_database: str
    naver_client_id: str
    naver_client_secret: str
    github_token: str
    naver_cookie: str


def get_settings() -> Settings:
    return Settings(
        db_host=os.environ["DB_HOST"],
        db_port=int(os.environ.get("DB_PORT", "3306")),
        db_username=os.environ["DB_USERNAME"],
        db_password=os.environ["DB_PASSWORD"],
        db_database=os.environ["DB_DATABASE"],
        naver_client_id=os.environ["NAVER_CLIENT_ID"],
        naver_client_secret=os.environ["NAVER_CLIENT_SECRET"],
        github_token=os.environ["GITHUB_TOKEN"],
        naver_cookie=os.environ["NAVER_COOKIE"],
    )
