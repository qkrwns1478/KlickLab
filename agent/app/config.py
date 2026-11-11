from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "klicklab"
    db_ro_user: str = "klicklab_agent_ro"
    db_ro_password: str = ""
    db_rw_user: str = "klicklab_agent"
    db_rw_password: str = ""

    jwt_secret: str = ""
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    anthropic_api_key: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    def dsn(self, *, read_only: bool) -> str:
        user = self.db_ro_user if read_only else self.db_rw_user
        password = self.db_ro_password if read_only else self.db_rw_password
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={user} password={password}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
