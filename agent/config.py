from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramSettings(BaseModel):
    bot_token: str
    allowed_chat_ids: list[int]


class ImapSettings(BaseModel):
    host: str
    port: int = 993
    username: str
    password: str


class EventKitSettings(BaseModel):
    enabled: bool = True


class ContactsSettings(BaseModel):
    enabled: bool = True


class OwnTracksSettings(BaseModel):
    host: str
    port: int = 8883
    topic: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AWFULCLAW_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model: str = "claude-sonnet-4-6"
    governance_model: str = "claude-haiku-4-5-20251001"
    memory_path: Path = Path("memory")
    agent_config_path: Path = Path("agent_config")
    mcp_config: Path = Path("config/mcp_servers.json")
    poll_interval: int = 5
    idle_interval: int = 60
    checkin_interval: int = 86400
    obsidian_vault: Path = Path("obsidian")

    telegram: TelegramSettings

    imap: ImapSettings | None = None
    eventkit: EventKitSettings | None = None
    contacts: ContactsSettings | None = None
    owntracks: OwnTracksSettings | None = None
