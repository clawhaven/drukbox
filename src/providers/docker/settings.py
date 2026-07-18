from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DockerSettings(BaseSettings):
    """Local Docker provider configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DOCKER_",
        extra="ignore",
    )

    default_image: str = Field(
        default="ghcr.io/czpython/drukbox/sandbox:latest",
        description="Sandbox image with sshd; auto-pulled. Build images/local/ to customize.",
    )
    ssh_username: str = Field(
        default="root",
        description="In-container user callers SSH as. The sandbox image runs sshd for root.",
    )
    bootstrap_ssh_timeout_seconds: float = Field(
        default=30.0,
        description="ssh-keyscan retry budget for a freshly-started sandbox container.",
    )
