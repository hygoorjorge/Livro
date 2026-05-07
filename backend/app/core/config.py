from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        extra="ignore",
    )

    app_name: str = "Livro Updater"
    data_dir: Path = Path(__file__).resolve().parents[3] / "data"
    db_path: Path | None = None

    anthropic_api_key: str = ""
    classifier_model: str = "claude-sonnet-4-6"
    proposal_model: str = "claude-sonnet-4-6"
    escalation_model: str = "claude-opus-4-7"

    classifier_batch_size: int = 15
    max_concurrent_claude_calls: int = 4

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def laws_dir(self) -> Path:
        return self.data_dir / "laws"

    @property
    def sqlite_url(self) -> str:
        path = self.db_path or (self.data_dir / "livro.sqlite")
        return f"sqlite+aiosqlite:///{path}"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.exports_dir, self.laws_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
