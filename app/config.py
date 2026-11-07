from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str = "change-me-in-production"
    access_token_expire_days: int = 7
    admin_emails: str = ""
    # Vercel Cron envía "Authorization: Bearer $CRON_SECRET" a /jobs/diario
    cron_secret: str = ""
    # Perfiles de preferencias con IA (/jobs/perfiles). Sin API key el proceso queda desactivado.
    anthropic_api_key: str = ""
    perfiles_activo: bool = True
    perfiles_modelo: str = "claude-opus-5-5"
    perfiles_meses_historia: int = 12
    perfiles_max_por_lote: int = 500
    perfiles_max_productos: int = 100
    base_url: str = "http://localhost:8000"
    frontend_urls: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    apple_client_id: str = ""
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def admin_emails_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def frontend_urls_set(self) -> set[str]:
        return {u.strip().rstrip("/") for u in self.frontend_urls.split(",") if u.strip()}


settings = Settings()
