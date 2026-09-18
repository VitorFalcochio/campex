from backend.events.taxonomy import (
    classify_operational_category,
    get_category_config,
    list_operational_categories,
    normalize_category,
)


def test_taxonomy_lists_global_operational_categories():
    categories = {item["id"] for item in list_operational_categories()}

    assert "waiting" in categories
    assert "idle" in categories
    assert "unsafe_presence" in categories
    assert "machine_blocked" in categories


def test_taxonomy_classifies_known_event_types_and_keywords():
    assert classify_operational_category(event_type="MACHINE_WAITING") == "waiting"
    assert classify_operational_category(event_type="PERSON_RESTRICTED_ZONE") == "unsafe_presence"
    assert classify_operational_category(event_type="CUSTOM", activity_label="fila crescendo") == "queue_growth"


def test_taxonomy_allows_explicit_metadata_override():
    assert classify_operational_category(
        event_type="CUSTOM_EVENT",
        metadata={"operational_category": "machine-starved"},
    ) == "machine_starved"


def test_taxonomy_normalizes_unknown_values_to_other():
    assert normalize_category("not-a-category") == "other"
    assert get_category_config("not-a-category").id == "other"
