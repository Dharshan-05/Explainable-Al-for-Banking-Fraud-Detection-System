# ============================================================
#  config.py  —  App Settings
# ============================================================
from pydantic_settings import BaseSettings
from pydantic import model_validator

class Settings(BaseSettings):
    # Database (Required in environment / .env)
    DATABASE_URL: str

    # JWT (Required in environment / .env)
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # App
    APP_NAME: str = "Fraud Detection XAI"
    DEBUG: bool = False
    API_PREFIX: str = "/api"

    # ML Model paths
    MODEL_PATH: str = "ml/model.pkl"
    EXPLAINER_PATH: str = "ml/shap_explainer.pkl"
    SCALER_PATH: str = "ml/scaler.pkl"

    # Redis (Required in environment / .env)
    REDIS_URL: str

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60
    TRUSTED_PROXIES: list[str] = []

    # File Upload Settings
    MAX_UPLOAD_SIZE: int = 250 * 1024 * 1024  # 250 MB
    UPLOAD_CHUNK_SIZE: int = 1024 * 1024    # 1 MB
    UPLOAD_DIR: str = "/app/uploads"

    # Cookie & CSRF Configuration
    COOKIE_NAME: str = "access_token"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: str | None = None
    TESTING: bool = False

    @model_validator(mode="after")
    def enforce_production_security(self) -> "Settings":
        if not self.DEBUG and not self.TESTING:
            self.COOKIE_SECURE = True
        # Validate TRUSTED_PROXIES entries
        import ipaddress
        for proxy in self.TRUSTED_PROXIES:
            try:
                ipaddress.ip_network(proxy, strict=False)
            except ValueError as e:
                raise ValueError(f"Invalid trusted proxy IP/network: '{proxy}'") from e
        return self

    model_config = {"protected_namespaces": (), "env_file": ".env", "extra": "ignore"}

settings = Settings()

