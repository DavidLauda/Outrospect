from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    twitter_bearer_token: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    # Origin of the Next.js frontend; used for CORS.
    # Set to * only in local dev; override in production.
    frontend_origin: str = "http://localhost:3000"

    class Config:
        env_file = ".env"


settings = Settings()
