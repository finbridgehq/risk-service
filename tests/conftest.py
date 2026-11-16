"""Test configuration shared by every test.

Settings are read when their module is imported, so the environment is set
here, before any application module is. The database URL is never connected
to: the tests run on in-memory fakes. The background tasks stay off, so
importing ``main`` starts neither the Kafka consumer nor the delivery worker.
"""
import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:1/test"
os.environ["KAFKA_CONSUMER_ENABLED"] = "false"
os.environ["KAFKA_PRODUCER_ENABLED"] = "false"
os.environ["GREEN_ENABLED"] = "false"
os.environ["INVESTMENT_DELIVERY_ENABLED"] = "false"
os.environ["REGISTRY_REFRESH_ENABLED"] = "false"
