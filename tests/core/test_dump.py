from datetime import timedelta

import pytest

from haqwa.core.canonical import canonical_examples
from haqwa.core.spec import Spec, dump_spec, iso_duration, load_spec, save_spec

from .helpers import amo, mp, nav, wt


def roundtrip(spec: Spec) -> Spec:
    import yaml

    return Spec.model_validate(yaml.safe_load(dump_spec(spec)))


def test_example_roundtrips_to_equal_spec(shop_dir):
    spec = load_spec(shop_dir / "rules.spec.yaml")
    assert roundtrip(spec) == spec


def test_dump_is_idempotent(shop_dir, tmp_path):
    spec = load_spec(shop_dir / "rules.spec.yaml")
    first = dump_spec(spec)
    p = tmp_path / "rules.spec.yaml"
    save_spec(spec, p)
    assert p.read_text(encoding="utf-8") == first
    assert dump_spec(load_spec(p)) == first


def test_key_order_and_rule_order_are_kept():
    rules = [r.model_dump(by_alias=True) for r in (wt(id="z-last"), amo(id="a-first"))]
    text = dump_spec(Spec.model_validate({"rules": rules}))
    assert text.index("z-last") < text.index("a-first")  # owner's order, not sorted
    block = text.split("- id: z-last")[1].split("  - id:")[0]
    keys = [ln.strip().split(":")[0] for ln in block.splitlines() if ln.startswith("    ")]
    assert keys == ["source", "pattern", "start", "event", "within", "per"]


def test_empty_fields_are_omitted():
    text = dump_spec(Spec.model_validate({"rules": [amo().model_dump(by_alias=True)]}))
    assert "except" not in text and "confirmed_examples" not in text


@pytest.mark.parametrize("rule", [amo(), nav(), mp(), wt()], ids=lambda r: r.pattern)
def test_every_pattern_with_canonical_examples_roundtrips(rule):
    examples = [ex.as_confirmed() for ex in canonical_examples(rule)]
    spec = Spec.model_validate(
        {"rules": [{**rule.model_dump(by_alias=True), "confirmed_examples": examples}]}
    )
    assert roundtrip(spec) == spec
    assert dump_spec(roundtrip(spec)) == dump_spec(spec)


def test_within_time_uses_hours_and_at_offsets():
    rule = wt()
    examples = [ex.as_confirmed() for ex in canonical_examples(rule)]
    spec = Spec.model_validate(
        {"rules": [{**rule.model_dump(by_alias=True), "confirmed_examples": examples}]}
    )
    text = dump_spec(spec)
    assert "within: PT48H" in text
    assert "at: PT65H" in text and "at: PT0S" in text


@pytest.mark.parametrize(
    ("td", "iso"),
    [
        (timedelta(hours=48), "PT48H"),
        (timedelta(hours=1, minutes=30), "PT1H30M"),
        (timedelta(seconds=45), "PT45S"),
        (timedelta(seconds=1, microseconds=500000), "PT1.5S"),
        (timedelta(0), "PT0S"),
    ],
)
def test_iso_duration(td, iso):
    assert iso_duration(td) == iso


def test_unicode_kept():
    rule = amo(source="ဖောက်သည်ကို နှစ်ခါ မကောက်ရ")
    text = dump_spec(Spec.model_validate({"rules": [rule.model_dump(by_alias=True)]}))
    assert "ဖောက်သည်" in text
