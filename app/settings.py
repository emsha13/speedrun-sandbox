from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    APP_NAME: str = 'speedrun'
    DB_URL: str = 'postgresql+asyncpg://postgres:postgres@localhost/speedrun'
    # The tests' database. The suite drops and creates it on every run.
    DB_URL_TEST: str = 'postgresql+asyncpg://postgres:postgres@localhost/speedrun_test'
    REDIS_URL: str = 'redis://localhost:6379/0'
    SECRET_KEY: str = 'change-me-change-me-change-me-change-me'
    # Whether the team workspace (`app/workspace/`, 195 tables and some 350 routes) is wired in.
    # Without it the app is the small one it started as: accounts, six tables.
    WORKSPACE: bool = True
    # The services outside (`app/workspace/outside.py`). Unset, the workspace does not call them.
    S3_BUCKET: str | None = None
    STRIPE_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None

    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 28
    CODE_MINUTES: int = 10
    CODE_ATTEMPTS: int = 5
    LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 15

    # Requests one address may make to one door of `/auth` in a minute.
    DOOR_LIMIT: int = 30
    # Codes one mailbox or one phone may be sent in ten minutes.
    SEND_LIMIT: int = 3
    SEND_WINDOW_MINUTES: int = 10


settings = Settings()
