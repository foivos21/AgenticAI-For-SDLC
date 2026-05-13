from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TechMellon Airline Backend"
    app_env: str = "development"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./techmellon_airline.db"
    cors_allow_origins: str = "*"
    app_log_level: str = "INFO"
    enable_elevenlabs_agentic: bool = False
    openai_api_key: str = ""
    jira_base_url: str = ""
    jira_user_email: str = ""
    jira_api_token: str = ""
    jira_webhook_token: str = ""
    jira_project_key: str = ""
    jira_transition_in_progress: str = "In Progress"
    jira_transition_in_review: str = "In Review"
    jira_transition_done: str = "Done"
    jira_transition_blocked: str = "Blocked"
    jira_planner_model: str = "openai:gpt-4o-mini"
    almas_analyzer_model: str = "openai:gpt-4o-mini"
    almas_planner_model: str = "openai:gpt-4o-mini"
    almas_fixer_model: str = "openai:gpt-4o-mini"
    almas_max_review_revisions: int = 1
    almas_data_dir: str = ""
    github_token: str = ""
    github_repo: str = ""
    github_base_branch: str = "main"

    @property
    def cors_allow_origins_list(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def jira_required_fields(self) -> dict[str, str]:
        return {
            "JIRA_BASE_URL": self.jira_base_url.strip(),
            "JIRA_USER_EMAIL": self.jira_user_email.strip(),
            "JIRA_API_TOKEN": self.jira_api_token.strip(),
            "JIRA_PROJECT_KEY": self.jira_project_key.strip(),
        }

    @property
    def jira_missing_required(self) -> list[str]:
        return [name for name, value in self.jira_required_fields.items() if not value]

    @property
    def jira_integration_enabled(self) -> bool:
        return not self.jira_missing_required

    @property
    def almas_data_dir_path(self) -> Path:
        if self.almas_data_dir.strip():
            return Path(self.almas_data_dir).expanduser()
        return Path(__file__).resolve().parents[1] / "data" / "almas"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
