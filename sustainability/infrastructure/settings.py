"""Settings the Sustainability context owns: ``GREEN_*`` variables and ``OPENAI_API_KEY``."""
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GreenSettings(BaseSettings):
    """How certificates are fetched and read, read from ``GREEN_*`` variables.

    Attributes:
        enabled (bool): Read certificates. Without an API key it is off anyway,
            and uploads stay undecided.
        model (str): The OpenAI model that reads them, e.g. ``gpt-6-luna``.
        reasoning_effort (str): How much the model reasons.
        timeout (float): Seconds to wait for the model's answer.
        documents_base_url (str): Where Profile's bucket is reachable from this
            service, e.g. ``http://minio:9000/vankoo-profile-documents``. Not the
            public URL the browser uses: inside Docker that is ``localhost``.
        max_bytes (int): The largest file read; Profile accepts PDF, JPEG and PNG.
        profile_group_id (str): The consumer group on Profile's events.
        profile_offset_reset (str): Where that group starts the first time.
            ``earliest``, unlike the auctions' consumer: Profile's topic may not
            exist yet when this service starts, and a group that starts at
            ``latest`` on a topic it discovers later skips its first messages.
            Nothing is lost by reading old events: the other event types are
            skipped and the inbox ignores a repeated one.
        api_key (SecretStr | None): ``OPENAI_API_KEY``; never logged.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="GREEN_", extra="ignore")

    enabled: bool = True
    model: str = "gpt-6-luna"
    reasoning_effort: Literal["none", "low", "medium", "high"] = "low"
    timeout: float = 90.0
    documents_base_url: str = "http://localhost:9100/vankoo-profile-documents"
    max_bytes: int = 10 * 1024 * 1024
    profile_group_id: str = "risk-profile-sustainability-v1"
    profile_offset_reset: Literal["latest", "earliest"] = "earliest"
    api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    @property
    def active(self) -> bool:
        """Whether certificates can be read: turned on and with a key."""
        return self.enabled and self.api_key is not None and bool(self.api_key.get_secret_value())


green_settings = GreenSettings()
