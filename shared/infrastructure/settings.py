"""Application settings.

Read once, at import time, from the environment and from a ``.env`` file in
the working directory. A missing required value stops the application at
start-up, with the variable's name in the error, instead of failing on the
first request that needs it.
"""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings every bounded context shares.

    Attributes:
        app_name (str): Title of the API in the OpenAPI description.
        database_url (str): SQLAlchemy URL with an async driver, e.g.
            ``postgresql+asyncpg://user:password@localhost:5432/dbname``.
        database_echo (bool): Log every SQL statement. For development only.
        docs_enabled (bool): Serve ``/docs``, ``/redoc`` and ``/openapi.json``.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Vankoo Risk Service"
    database_url: str
    database_echo: bool = False
    docs_enabled: bool = True


class KafkaSettings(BaseSettings):
    """How this service reaches the Kafka broker, read from ``KAFKA_*`` variables.

    Attributes:
        bootstrap_servers (str): ``host:port`` of the broker, e.g. ``kafka-broker:9094``.
        group_id (str): The consumer group; its committed offsets say where to resume.
        auto_offset_reset (str): Where a group with no committed offset starts.
            ``latest`` on purpose: the topics keep every event forever, and
            replaying old auctions would re-grade them.
        consumer_enabled (bool): Start the consumers with the application. Off in
            tests and when only running migrations.
        producer_enabled (bool): Start the outbox relay that sends this
            service's events. Off in tests.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KAFKA_", extra="ignore")

    bootstrap_servers: str = "localhost:9092"
    group_id: str = "risk-auction-assessment-v1"
    auto_offset_reset: Literal["latest", "earliest"] = "latest"
    consumer_enabled: bool = True
    producer_enabled: bool = True


settings = Settings()
kafka_settings = KafkaSettings()
