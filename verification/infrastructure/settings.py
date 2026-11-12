"""Settings the Verification context owns: ``KYC_*`` variables."""
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class KycSettings(BaseSettings):
    """How fichas RUC are fetched and checked, read from ``KYC_*`` variables.

    The bucket is reached through the same client as the green certificates
    (``GREEN_DOCUMENTS_BASE_URL``): both are uploads to Profile's bucket.

    Attributes:
        max_bytes (int): The largest ficha read; SUNAT's are a few hundred KB.
        profile_group_id (str): The consumer group on Profile's events, apart
            from the green certificates' so each reads at its own pace.
        profile_offset_reset (str): Where that group starts the first time;
            ``earliest`` for the same reason as ``GREEN_PROFILE_OFFSET_RESET``.
        demo_ca_path (Path | None): TEMPORARY PATCH for the demonstrations: the
            certificate of Vankoo's demonstration CA (``python -m verification
            demo-ca``). When set, fichas signed by it are accepted and marked
            ``demo``; unset (the default) only SUNAT's signature counts. Never
            set it in production. See ``docs/KYC_RULES.md``.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KYC_", extra="ignore")

    max_bytes: int = 5 * 1024 * 1024
    profile_group_id: str = "risk-profile-verification-v1"
    profile_offset_reset: Literal["latest", "earliest"] = "earliest"
    demo_ca_path: Path | None = None


kyc_settings = KycSettings()
