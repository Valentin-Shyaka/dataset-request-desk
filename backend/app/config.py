import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    token_ttl_minutes: int
    cookie_secure: bool
    bcrypt_rounds: int


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql+psycopg://drd:drd@localhost:5432/drd"),
        jwt_secret=os.environ.get("JWT_SECRET", "dev-only-insecure-secret-change-me-0123456789"),
        token_ttl_minutes=int(os.environ.get("TOKEN_TTL_MINUTES", "480")),
        cookie_secure=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
        bcrypt_rounds=int(os.environ.get("BCRYPT_ROUNDS", "12")),
    )


settings = load_settings()
