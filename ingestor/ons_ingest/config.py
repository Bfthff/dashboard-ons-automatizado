import os
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Config:
    database_url: str
    bucket_url: str
    dataset_prefix: str
    poll_interval: int
    backfill_years: int

    @property
    def min_year(self) -> int:
        """Primeiro ano (inclusive) a carregar."""
        return date.today().year - self.backfill_years + 1

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            bucket_url=os.getenv(
                "ONS_BUCKET_URL",
                "https://ons-aws-prod-opendata.s3.us-west-2.amazonaws.com",
            ).rstrip("/"),
            dataset_prefix=os.getenv(
                "ONS_DATASET_PREFIX", "dataset/balanco_energia_subsistema_ho/"
            ),
            poll_interval=int(os.getenv("POLL_INTERVAL_SECONDS", "3600")),
            backfill_years=int(os.getenv("BACKFILL_YEARS", "2")),
        )
