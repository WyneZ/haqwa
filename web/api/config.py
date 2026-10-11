"""Environment-based API settings and the shop demo vocabulary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from haqwa.ai.vocab import Vocabulary

SHOP_VOCAB = Vocabulary(
    events=[
        "order_created",
        "charged",
        "charge_failed",
        "refunded",
        "cancelled",
        "shipped",
        "refund_requested",
        "refund_completed",
    ],
    fields=["order_id", "customer_id", "payment_type", "amount", "time"],
    field_values={"payment_type": ["card", "installment"]},
)


@dataclass(frozen=True)
class Settings:
    """Settings read from the process environment when the app is built."""

    vocab: Vocabulary
    cache_dir: Path
    dev_cors: bool


def get_settings() -> Settings:
    """Read non-secret API settings from the environment."""
    return Settings(
        vocab=SHOP_VOCAB,
        cache_dir=Path(os.getenv("HAQWA_CACHE_DIR", ".haqwa_cache")),
        dev_cors=os.getenv("HAQWA_DEV_CORS") == "1",
    )
