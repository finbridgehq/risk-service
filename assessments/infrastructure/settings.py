"""Settings the Assessments context owns: ``INVESTMENT_*``, ``CREDIT_BUREAU_*`` and ``NEWS_*`` variables."""
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class InvestmentSettings(BaseSettings):
    """How assessments reach the Investment service.

    Attributes:
        base_url (str): Investment's own address, never the gateway's: the
            gateway does not route the internal evaluation endpoint.
        connect_timeout (float): Seconds to wait for a connection.
        read_timeout (float): Seconds to wait for the answer.
        delivery_enabled (bool): Start the delivery worker with the
            application. Off in tests and when only running migrations.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="INVESTMENT_", extra="ignore")

    base_url: str = "http://localhost:8082"
    connect_timeout: float = 2.0
    read_timeout: float = 5.0
    delivery_enabled: bool = True


investment_settings = InvestmentSettings()


class CreditBureauSettings(BaseSettings):
    """Whether the scoring asks a credit bureau, read from ``CREDIT_BUREAU_*`` variables.

    Attributes:
        enabled (bool): Ask the (simulated) bureau. With ``false`` the credit
            rating is left out of the score.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CREDIT_BUREAU_", extra="ignore")

    enabled: bool = True


credit_bureau_settings = CreditBureauSettings()


class NewsSettings(BaseSettings):
    """The web search for negative news, read from ``NEWS_*`` variables and ``OPENAI_API_KEY``.

    Attributes:
        enabled (bool): Search for news. Without an API key it is off anyway.
        model (str): The OpenAI model that searches and reads, e.g. ``gpt-6-luna``.
        reasoning_effort (str): How much the model reasons. ``medium``: at ``low`` it
            mixed up categories in the first real runs.
        max_searches (int): The most web searches per payer (each costs about $0.01).
        cache_days (int): How long a payer's search is reused before searching again.
        timeout (float): Seconds to wait for the whole search.
        api_key (SecretStr | None): ``OPENAI_API_KEY``; never logged.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEWS_", extra="ignore")

    enabled: bool = True
    model: str = "gpt-6-luna"
    reasoning_effort: Literal["none", "low", "medium", "high"] = "medium"
    max_searches: int = 5
    cache_days: int = 7
    timeout: float = 90.0
    api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    @property
    def active(self) -> bool:
        """Whether a search can run: turned on and with a key."""
        return self.enabled and self.api_key is not None and bool(self.api_key.get_secret_value())


news_settings = NewsSettings()
