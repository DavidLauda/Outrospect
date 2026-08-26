from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    twitter_bearer_token: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"


settings = Settings()
