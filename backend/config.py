from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_api_key: str
    gemini_api_key: str
    app_env: str = "development"
    app_port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Single instance imported everywhere — avoids re-reading .env on every call
settings = Settings()
