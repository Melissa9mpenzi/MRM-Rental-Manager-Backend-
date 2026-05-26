from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

_DEFAULT_CORS_CSV = (
    "http://localhost:5173,"
    "http://localhost:5174,"
    "http://127.0.0.1:5173,"
    "http://127.0.0.1:5174,"
    "https://mrm-rental-manager-frontend-pink.vercel.app,"
    "https://mrm-rental-manager-mobile.vercel.app"
)


def _parse_allowed_origins(value: str | list[str] | None) -> list[str]:
    """Parse ALLOWED_ORIGINS from .env — comma-separated or JSON array."""
    if value is None:
        return [p.strip() for p in _DEFAULT_CORS_CSV.split(",") if p.strip()]
    if isinstance(value, list):
        return [str(p).strip() for p in value if str(p).strip()]
    s = str(value).strip()
    if not s:
        return [p.strip() for p in _DEFAULT_CORS_CSV.split(",") if p.strip()]
    if s.startswith("["):
        import json

        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(p).strip() for p in parsed if str(p).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in s.split(",") if part.strip()]


class Settings(BaseSettings):
    # Environment
    environment: str = "development"
    # Skip DB migration checks on API boot (faster reload; run python -m app.utils.init_db when schema changes)
    skip_startup_migrations: bool = False

    # Database — Neon / Postgres (set DATABASE_URL in .env)
    # Example: postgresql+psycopg2://USER:PASSWORD@ep-xxx.region.aws.neon.tech/neondb?sslmode=require
    database_url: str = "postgresql+psycopg2://user:password@localhost:5432/rental_manager_db?sslmode=require"

    # Postgres: schema for ORM tables. Production Neon uses "public" (see .env.example).
    # Use "rental_mgr" only when you created tables in that schema via init_db.
    database_schema: str = "public"

    # JWT
    secret_key: str = "change-me-in-production-use-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # CORS — comma-separated in .env (not JSON). Example:
    # ALLOWED_ORIGINS=http://localhost:5173,https://your-app.vercel.app
    allowed_origins_csv: str = Field(default=_DEFAULT_CORS_CSV, validation_alias="ALLOWED_ORIGINS")

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

    # Privy — social login (Google/Apple/email) + embedded Sui wallets. https://www.privy.io/
    privy_app_id: str = ""
    privy_app_secret: str = ""

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
    sui_network: str = "testnet"
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

    @property
    def allowed_origins(self) -> List[str]:
        return _parse_allowed_origins(self.allowed_origins_csv)

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
        # Neon UI often adds channel_binding=require; it breaks many Vercel/Linux psycopg2 builds.
        url = url.replace("channel_binding=require", "").replace("channel_binding=prefer", "")
        url = url.replace("&&", "&").replace("?&", "?").rstrip("?&")
        return url

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def is_production(self) -> bool:
        return (self.environment or "").strip().lower() == "production"


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