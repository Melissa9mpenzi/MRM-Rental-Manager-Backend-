from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Environment
    environment: str = "development"

    # Database — Neon / Postgres (set DATABASE_URL in .env)
    # Example: postgresql+psycopg2://USER:PASSWORD@ep-xxx.region.aws.neon.tech/neondb?sslmode=require
    database_url: str = "postgresql+psycopg2://user:password@localhost:5432/rental_manager_db?sslmode=require"

    # Postgres: schema for ORM tables (avoids clashing with Neon Auth public.users, etc.).
    # Set to "public" only on a database where you control all public.* tables.
    database_schema: str = "rental_mgr"

    # JWT
    secret_key: str = "change-me-in-production-use-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # CORS
    allowed_origins: List[str] = ["http://localhost:5173", "http://localhost:5174"]

    # Auth email-link redirects + SPA (must match Vite dev server or production URL)
    frontend_base_url: str = "http://localhost:5173"

    # Used in outbound emails (must reach this FastAPI instance from the user's mail client)
    api_public_base_url: str = "http://localhost:8000"

    # File uploads
    upload_dir: str = "./uploads"

    # SMTP — fill these in your .env file
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_tls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()