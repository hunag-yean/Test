from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str
    whisper_model: str = "base"
    whisper_language: str = "zh"
    audio_device_index: int | None = None
    audio_chunk_seconds: int = 15
    analysis_interval_seconds: int = 30
    analysis_min_new_words: int = 50
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
