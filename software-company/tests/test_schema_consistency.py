"""Schema JSON là nguồn sự thật của topic; pydantic model, Topic literal và Envelope phải khớp nó (và ngược lại)."""
import json
from typing import get_args

import pytest
from pydantic import ValidationError

from company.bus import SCHEMA_DIR, BusError, InMemoryBus
from company.events import NAMESPACE_OWNERS, PAYLOAD_MODELS, Envelope, Topic

SCHEMAS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in SCHEMA_DIR.glob("*.json")}


def test_every_topic_has_schema_and_vice_versa():
    assert set(SCHEMAS) == set(get_args(Topic))


def test_schema_const_topic_matches_filename():
    for name, s in SCHEMAS.items():
        assert s["properties"]["topic"]["const"] == name, name


def test_envelope_fields_match_every_schema():
    """Mọi trường của Envelope (kể cả schema_version/correlation_id/causation_id) phải có trong envelope của mọi schema."""
    fields = set(Envelope.model_fields)
    for name, s in SCHEMAS.items():
        assert fields <= set(s["properties"]), (name, fields - set(s["properties"]))


@pytest.mark.parametrize("topic", sorted(PAYLOAD_MODELS))
def test_pydantic_fields_exist_in_schema_with_same_nullability(topic):
    model = PAYLOAD_MODELS[topic]
    props = SCHEMAS[topic]["properties"]["payload"]["properties"]
    for name, f in model.model_json_schema()["properties"].items():
        assert name in props, f"{topic}: model có `{name}` nhưng schema không"
        nullable = any(x.get("type") == "null" for x in f.get("anyOf", []))
        if nullable:
            t = props[name].get("type"); e = props[name].get("enum")
            assert (isinstance(t, list) and "null" in t) or (e is not None and None in e), f"{topic}.{name} phải cho phép null"


def test_schema_required_subset_of_model_required():
    """Schema bắt buộc trường nào thì model không được coi là tuỳ chọn (kẻo code tạo payload thiếu trường)."""
    for topic, model in PAYLOAD_MODELS.items():
        req = set(SCHEMAS[topic]["properties"]["payload"].get("required", []))
        model_req = set(model.model_json_schema().get("required", []))
        assert req <= model_req, (topic, req - model_req)


def test_shared_context_namespace_enum_matches_owners():
    enum = set(SCHEMAS["shared-context"]["properties"]["payload"]["properties"]["namespace"]["enum"])
    assert enum == set(NAMESPACE_OWNERS)


def test_enum_is_enforced_not_just_required():
    bus = InMemoryBus()
    with pytest.raises(BusError, match="JSON Schema"):
        bus.publish(Envelope(topic="release-events", key="R", actor="release-engineer",
                             payload={"release_id": "R", "version": "1.0.0", "env": "prod", "status": "deployed"}))
    with pytest.raises(BusError, match="JSON Schema"):
        bus.publish(Envelope(topic="incidents", key="I", actor="support-docs",
                             payload={"incident_id": "I", "severity": "SEV9", "summary": "x", "root_cause_class": "code"}))
    with pytest.raises(BusError, match="JSON Schema"):
        bus.publish(Envelope(topic="clarification-questions", key="P", actor="clarifier",
                             payload={"project_id": "P", "round": 3, "questions": []}))


def test_envelope_is_validated_too():
    bus = InMemoryBus()
    with pytest.raises(BusError, match="JSON Schema"):
        bus.publish(Envelope(topic="audit-log", key="a", actor="a", schema_version=0, payload={"actor": "a", "action": "x"}))


def test_unknown_topic_rejected_by_pydantic():
    with pytest.raises(ValidationError):
        Envelope(topic="no-such-topic", key="k", actor="a", payload={})


def test_child_keeps_correlation_and_sets_causation():
    root = Envelope(topic="research-requests", key="P", actor="human", payload={"project_id": "P", "description": "x"})
    assert root.correlation_id == root.event_id and root.causation_id is None
    c = root.child(topic="research-findings", key="P", actor="intake", payload={"project_id": "P", "kind": "intake", "data": {}})
    assert c.correlation_id == root.event_id and c.causation_id == root.event_id
    g = c.child(topic="audit-log", key="intake", actor="intake", payload={"actor": "intake", "action": "x"})
    assert g.correlation_id == root.event_id and g.causation_id == c.event_id
