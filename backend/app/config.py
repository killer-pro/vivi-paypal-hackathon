from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://vv:vv@localhost:5432/video_virale"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "http://localhost:9100"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "video-virale"
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me"
    public_url: str = "http://localhost:5173"  # base des liens envoyés par e-mail
    secret_key: str = "dev-secret"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    fal_key: str = ""
    comfy_cloud_api_key: str = ""
    elevenlabs_api_key: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""
    comfyui_url: str = "http://127.0.0.1:8188"
    fake_providers: bool = False
    # "dev" : poste local (avertissements, cookie sans Secure, /docs ouvert). Toute autre valeur (ex. "prod") : refus de
    # démarrer avec les secrets par défaut, cookie Secure, documentation de l'API fermée.
    app_env: str = "dev"

    @field_validator("admin_email")
    @classmethod
    def _normalize_admin_email(cls, value: str) -> str:
        """Même forme que les adresses saisies à la connexion (`normalize_email`) : sinon l'admin ne pourrait pas se
        connecter avec un `ADMIN_EMAIL` en majuscules."""
        return value.strip().lower()

    @property
    def is_prod(self) -> bool:
        return self.app_env.strip().lower() != "dev"


# Valeurs par défaut du code et de `.env.example` : acceptables en local uniquement.
INSECURE_VALUES = {"admin_password": {"change-me"}, "secret_key": {"dev-secret", "change-me-too"}}


def insecure_defaults(s: Settings) -> list[str]:
    """Variables encore à leur valeur par défaut connue (noms d'environnement)."""
    return [name.upper() for name, values in INSECURE_VALUES.items() if getattr(s, name) in values]


settings = Settings()
