from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Environment
    environment: str = "development"
    # Skip DB migration checks on API boot (faster reload; run python -m app.utils.init_db when schema changes)
    skip_startup_migrations: bool = False

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

    # CORS — comma-separated in .env, e.g. ALLOWED_ORIGINS=https://app.vercel.app,https://mobile.vercel.app
    allowed_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "https://mrm-rental-manager-frontend-pink.vercel.app",
        "https://mrm-rental-manager-mobile.vercel.app",
    ]

    # Auth email-link redirects + SPA (must match Vite dev server or production URL)
    frontend_base_url: str = "http://localhost:5173"
    # Government portal entry (SPA path or subdomain path prefix)
    government_portal_path: str = "/government/login"

    # Optional comma-separated office IPs allowed for gov login (empty = no restriction)
    government_allowed_ips: str = ""

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

    # Firebase Admin — path to service account JSON (optional). Used by POST /auth/firebase.
    firebase_credentials_path: str = ""

    # Payment gateway (Uganda): mtn_momo | pesapal | flutterwave | mock
    payment_gateway_provider: str = "mtn_momo"
    payment_allow_mock: bool = False
    payment_webhook_secret: str = ""

    # MTN MoMo Collection API — https://momodeveloper.mtn.com (UG MTN)
    mtn_momo_subscription_key: str = ""
    mtn_momo_api_user: str = ""
    mtn_momo_api_key: str = ""
    mtn_momo_target_environment: str = "sandbox"
    mtn_momo_base_url: str = ""
    mtn_momo_callback_url: str = ""
    mtn_momo_webhook_secret: str = ""

    # Pesapal — https://www.pesapal.com/ug/ (MTN + Airtel + card on one page)
    pesapal_consumer_key: str = ""
    pesapal_consumer_secret: str = ""
    pesapal_env: str = "sandbox"
    pesapal_ipn_id: str = ""

    # Flutterwave (optional — not all Uganda merchants can onboard)
    flutterwave_secret_key: str = ""
    flutterwave_public_key: str = ""

    # Sui blockchain — hybrid Web3 (does not replace MoMo/Pesapal)
    sui_network: str = "devnet"
    sui_rpc_url: str = ""
    sui_treasury_address: str = ""
    sui_package_id: str = ""
    sui_escrow_module: str = "escrow"
    sui_ugx_per_sui: float = 6_000_000
    sui_anchor_fiat_receipts: bool = True

    # Walrus decentralized storage
    walrus_publisher_url: str = ""
    walrus_aggregator_url: str = ""

    # Transactional email branding (optional logo: public HTTPS URL, e.g. CDN or your SPA /logo.png)
    email_brand_name: str = "RentDirect UG"
    email_product_tagline: str = "Property rentals · Uganda"
    email_brand_logo_url: str = ""
    email_support_email: str = ""

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value):
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        if not value or not isinstance(value, str):
            return value
        url = value.strip()
        if url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://") :]
        elif url.startswith("postgresql://") and "+psycopg2" not in url:
            url = "postgresql+psycopg2://" + url[len("postgresql://") :]
        return url

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()


def database_url_looks_configured() -> bool:
    """False when still on the placeholder from config defaults."""
    url = (settings.database_url or "").lower()
    if not url:
        return False
    if "user:password@localhost" in url:
        return False
    if url.endswith("/rental_manager_db") and "localhost" in url:
        return False
    return True