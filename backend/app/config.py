from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "Prajwal Engineering Portfolio API"
    firebase_project_id: str = ""
    firebase_client_email: str = ""
    firebase_private_key: str = ""
    firebase_storage_bucket: str = ""
    firebase_web_api_key: str = ""
    allowed_admin_emails: str = "work.mhetreprajwal@gmail.com,mhprajwal601@gmail.com"
    allowed_origins: str = "https://prajwal-engineering-portfolio-web.vercel.app"
    cookie_secure: bool = True
    cookie_domain: str = ""
    access_cookie_name: str = "pm_admin_access"
    refresh_cookie_name: str = "pm_admin_refresh"
    contact_rate_limit_per_hour: int = 5
    login_rate_limit_per_window: int = 10
    login_rate_limit_window_seconds: int = 900
    upload_max_bytes: int = 4 * 1024 * 1024

    @property
    def admin_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.allowed_admin_emails.split(",") if email.strip()}

    @property
    def origin_set(self) -> set[str]:
        return {origin.strip().rstrip("/") for origin in self.allowed_origins.split(",") if origin.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
