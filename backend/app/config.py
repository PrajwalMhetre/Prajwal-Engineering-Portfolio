from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_name: str = "Prajwal Engineering Portfolio API"
    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""
    admin_emails: str = "work.mhetreprajwal@gmail.com,mhprajwal601@gmail.com"
    allowed_origins: str = "https://prajwal-engineering-portfolio-web.vercel.app"
    cookie_secure: bool = True
    cookie_domain: str = ""
    access_cookie_name: str = "pm_admin_access"
    refresh_cookie_name: str = "pm_admin_refresh"
    contact_rate_limit_per_hour: int = 5

    @property
    def admin_email_set(self) -> set[str]:
        return {x.strip().lower() for x in self.admin_emails.split(",") if x.strip()}

    @property
    def origin_set(self) -> set[str]:
        return {x.strip().rstrip("/") for x in self.allowed_origins.split(",") if x.strip()}

    @property
    def sqlalchemy_database_url(self) -> str:
        value = self.database_url.strip()
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

@lru_cache
def get_settings() -> Settings:
    return Settings()
