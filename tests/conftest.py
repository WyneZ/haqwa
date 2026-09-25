from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHOP = ROOT / "examples" / "shop"


@pytest.fixture
def shop_dir() -> Path:
    return SHOP
