import datetime as dt
import hashlib

import pytest
from pydantic import ValidationError

from governance.ibkr_observation import (
    DATASET_SUPPORT,
    AdapterId,
    ContractFixtureAdapter,
    CredentialReference,
    DatasetClass,
    DatasetSupport,
    EvidenceState,
    InstrumentIdentity,
    MarketDataMode,
    ObservationBatch,
    ObservationError,
    ObservationRequest,
    PageMetadata,
    ProviderId,
    RawObservationEnvelope,
    _seal,
    assert_payload,
    build_request,
    evaluate_real_route,
    observe_contract_fixture,
    validate_observation_batch,
)
from governance.phase7e import EvidenceGate, GateState

NOW = dt.datetime(2026, 9, 3, 12, tzinfo=dt.UTC)


def result(mode=MarketDataMode.DELAYED):
    return observe_contract_fixture(build_request(mode=mode), observed_at=NOW)


def test_closed_identity_read_only_scope_and_dataset_registry():
    request = build_request(mode=MarketDataMode.DELAYED)
    assert type(request.provider) is ProviderId
    assert type(request.adapter) is AdapterId
    assert request.scope == "MARKET_OBSERVATION_READ_ONLY"
    assert request.dataset is DatasetClass.PRICES_OHLCV
    assert DATASET_SUPPORT[DatasetClass.PRICES_OHLCV] is DatasetSupport.CONTRACT_TEST_ONLY
    assert all(
        DATASET_SUPPORT[item] is DatasetSupport.NOT_YET_PROVISIONED
        for item in DatasetClass
        if item is not DatasetClass.PRICES_OHLCV
    )
    assert not any(hasattr(ContractFixtureAdapter(), name) for name in ("order", "execute", "rebalance"))


def test_safety_and_observed_untrusted_handoff_are_frozen():
    value = result()
    assert value.evidence_state is EvidenceState.OBSERVED_UNTRUSTED
    assert value.gate_states == tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate)
    assert value.trust_root == value.authority == value.independent_verifier == "NOT_PROVISIONED"
    assert value.durable_replay == "NOT_PROVISIONED"
    assert value.real_route == "QVM_NOT_READY"
    assert value.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert value.trade_decision == "NO_TRADE"
    assert value.signals_generated is value.live_execution_enabled is False
    assert value.backtesting == "NOT_AUTHORIZED"


@pytest.mark.parametrize("field,value", [
    ("provider", "provider.fake"),
    ("adapter", "adapter.fake"),
    ("dataset", "fundamentals_complement"),
    ("endpoint_id", "ibkr.orders.submit"),
    ("scope", "ORDER_EXECUTION"),
])
def test_route_swaps_fail_even_with_reseal(field, value):
    raw = build_request(mode=MarketDataMode.DELAYED).model_dump(mode="python")
    raw[field] = value
    raw.pop("request_hash")
    with pytest.raises(ValidationError):
        _seal(ObservationRequest, "request_hash", **raw)


def test_ticker_only_or_wrong_permanent_identity_fails():
    digest = hashlib.sha256(b"lineage").hexdigest()
    with pytest.raises(ValidationError, match="ticker alone"):
        InstrumentIdentity(
            security_master_id="example",
            permanent_id="ibkr.conid.1",
            symbology_lineage_digest=digest,
            display_symbol="example",
        )
    raw = build_request(mode=MarketDataMode.DELAYED).model_dump(mode="python")
    raw["instrument"]["permanent_id"] = "ibkr.conid.wrong"
    raw.pop("request_hash")
    with pytest.raises(ValidationError):
        _seal(ObservationRequest, "request_hash", **raw)
    raw = build_request(mode=MarketDataMode.DELAYED).model_dump(mode="python")
    raw["instrument"] = {
        "security_master_id": "security.attacker-999",
        "permanent_id": "ibkr.conid.wrong-but-valid",
        "symbology_lineage_digest": "0" * 64,
        "display_symbol": "ＥＸＡＭＰＬＥ",
    }
    raw.pop("request_hash")
    with pytest.raises(ValidationError, match="code-owned fixture binding"):
        _seal(ObservationRequest, "request_hash", **raw)


def test_payload_digest_and_size_bind_actual_bytes():
    envelope = result().envelopes[0]
    assert_payload(envelope, b'{"bars":[{"close":"100.00"}]}')
    with pytest.raises(ObservationError):
        assert_payload(envelope, b'{"bars":[{"close":"900.00"}]}')


def test_market_retrieval_chronology_and_canonical_utc_fail_closed():
    raw = result().envelopes[0].model_dump(mode="python")
    raw["market_event_at"] = NOW + dt.timedelta(seconds=1)
    raw.pop("envelope_hash")
    with pytest.raises(ValidationError, match="chronology"):
        _seal(RawObservationEnvelope, "envelope_hash", **raw)
    raw = result().envelopes[0].model_dump(mode="python")
    raw["retrieved_at"] = NOW.replace(tzinfo=None)
    raw.pop("envelope_hash")
    with pytest.raises(ValidationError, match="canonical UTC"):
        _seal(RawObservationEnvelope, "envelope_hash", **raw)
    raw = result().envelopes[0].model_dump(mode="python")
    raw["retrieved_at"] = NOW.astimezone(dt.timezone(dt.timedelta(hours=-6)))
    raw.pop("envelope_hash")
    with pytest.raises(ValidationError, match="canonical UTC"):
        _seal(RawObservationEnvelope, "envelope_hash", **raw)


def test_delayed_cannot_be_relabelled_realtime_and_unknown_timing_fails():
    raw = result().envelopes[0].model_dump(mode="python")
    raw["response"]["market_data_mode"] = MarketDataMode.REALTIME
    raw.pop("envelope_hash")
    with pytest.raises(ValidationError, match="differs"):
        _seal(RawObservationEnvelope, "envelope_hash", **raw)
    with pytest.raises(ValidationError, match="UNKNOWN"):
        build_request(mode=MarketDataMode.UNKNOWN, timing_sensitive=True)
    for mode in (MarketDataMode.REALTIME, MarketDataMode.FROZEN, MarketDataMode.UNKNOWN):
        with pytest.raises(ObservationError, match="DELAYED data only"):
            observe_contract_fixture(build_request(mode=mode), observed_at=NOW)


def test_pagination_omission_reordering_and_cursor_tampering_fail():
    envelope = result().envelopes[0]
    cursor = hashlib.sha256(b"cursor").hexdigest()
    first_raw = envelope.model_dump(mode="python")
    first_raw["response"]["page"] = PageMetadata(page_index=0, next_cursor_digest=cursor, is_last=False)
    first_raw.pop("envelope_hash")
    first = _seal(RawObservationEnvelope, "envelope_hash", **first_raw)
    second_raw = envelope.model_dump(mode="python")
    second_raw["response"]["page"] = PageMetadata(page_index=1, cursor_digest=cursor, is_last=True)
    second_raw.pop("envelope_hash")
    second = _seal(RawObservationEnvelope, "envelope_hash", **second_raw)
    template = result().model_dump(mode="python")
    template["envelopes"] = (first, second)
    template.pop("batch_hash")
    assert len(_seal(ObservationBatch, "batch_hash", **template).envelopes) == 2
    for pages in ((second, first), (first,), (second,)):
        raw = result().model_dump(mode="python")
        raw["envelopes"] = pages
        raw.pop("batch_hash")
        with pytest.raises(ValidationError):
            _seal(ObservationBatch, "batch_hash", **raw)

    other_request = build_request(mode=MarketDataMode.FROZEN)
    mixed_raw = second.model_dump(mode="python")
    mixed_raw["request"] = other_request
    mixed_raw["response"]["market_data_mode"] = MarketDataMode.FROZEN
    mixed_raw.pop("envelope_hash")
    mixed = _seal(RawObservationEnvelope, "envelope_hash", **mixed_raw)
    raw = result().model_dump(mode="python")
    raw["envelopes"] = (first, mixed)
    raw.pop("batch_hash")
    with pytest.raises(ValidationError, match="same canonical request"):
        _seal(ObservationBatch, "batch_hash", **raw)


def test_error_or_secret_fields_and_fake_provisioning_rejected():
    raw = result().envelopes[0].model_dump(mode="python")
    raw["response"] = {"status": "ERROR", "error_code": "500", "market_data_mode": "DELAYED", "page": {"page_index": 0, "is_last": True}}
    raw.pop("envelope_hash")
    with pytest.raises(ValidationError):
        _seal(RawObservationEnvelope, "envelope_hash", **raw)
    with pytest.raises((ValidationError, ObservationError)):
        CredentialReference.from_reference("password=hunter2")
    with pytest.raises(ValidationError):
        CredentialReference.model_validate({
            "reference_digest": "0" * 64,
            "provisioning_state": "PROVISIONED_REAL",
            "api_key": "secret",
        })
    for material in (
        "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
        "sessionid=abc123",
        "authorization=Basic dXNlcjpwYXNz",
        "hunter2",
        "external-vault-reference:api-token",
        "external-vault-reference:sessionid",
        "external-vault-reference:authorization-header",
        "external-vault-reference:client-certificate",
    ):
        with pytest.raises(ObservationError):
            CredentialReference.from_reference(material)


def test_copy_construct_json_nested_mutation_and_outer_reseal_fail():
    value = result()
    assert validate_observation_batch(value.model_dump_json()) == value
    forged_response = value.envelopes[0].response.model_construct(
        **{**value.envelopes[0].response.model_dump(), "market_data_mode": "REALTIME"}
    )
    forged_envelope = value.envelopes[0].model_construct(
        **{**value.envelopes[0].model_dump(), "response": forged_response}
    )
    for forged in (
        value.model_copy(update={"trade_decision": "TRADE"}),
        ObservationBatch.model_construct(**{**value.model_dump(), "envelopes": (forged_envelope,)}),
    ):
        with pytest.raises(ObservationError):
            validate_observation_batch(forged)


def test_fixture_and_fake_adapter_cannot_enter_real_route():
    with pytest.raises(ObservationError, match="caller-controlled"):
        evaluate_real_route(adapter=ContractFixtureAdapter())
    with pytest.raises(ObservationError, match="NOT_PROVISIONED"):
        evaluate_real_route()


def test_duplicates_are_not_misrepresented_as_durable_replay_protection():
    value = result()
    assert validate_observation_batch(value) == value
    assert validate_observation_batch(value) == value
    assert value.durable_replay == "NOT_PROVISIONED"
