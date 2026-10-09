from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    # Database Settings
    DATABASE_URL: str = ""
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "loandb"
    DATABASE_USER: str = "admin"
    DATABASE_PASSWORD: str = "password"

    # API Keys
    GROQ_API_KEY: str = ""

    # Redis Settings
    ENABLE_REDIS: bool = False
    REDIS_URL: str = ""

    # Comma-separated list of origins permitted to call this API.
    # Empty falls back to the local development hosts in main.py.
    CORS_ALLOW_ORIGINS: str = ""

    # Application Settings
    UPLOAD_DIR: str = "uploads"
    VECTORSTORE_DIR: str = "vectorstore"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    LOG_LEVEL: str = "DEBUG"

    # Configuration for .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
