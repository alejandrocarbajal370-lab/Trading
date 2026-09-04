import datetime as dt
import json

import pytest
from pydantic import ValidationError

from governance.ibkr_probe import (
    GovernedInstrument,
    MarketDataMode,
    ProbeConfig,
    ProbeError,
    ProbeEvidence,
    ResolvedContract,
    SourceKind,
    TickStatus,
    _ibkr_bar_time,
    _seal,
    build_request,
    capture_probe,
    persist_evidence,
    validate_evidence,
)
from governance.phase7e import EvidenceGate, GateState


class FixtureTransport:
    source_kind = SourceKind.CONTRACT_TEST_ONLY
    api_version = "9.81.1.post1"

    def __init__(self, *, mode="DELAYED", mode_code=3, ticks=0):
        self.mode = mode
        self.mode_code = mode_code
        self.ticks = ticks

    def collect(self, config, instrument):
        now = dt.datetime.now(dt.UTC)
        return {
            "server_version": 157,
            "server_current_time": now - dt.timedelta(seconds=1),
            "resolved_contract": {
                "conid": 272093,
                "symbol": "MSFT",
                "security_type": "STK",
                "exchange": "SMART",
                "primary_exchange": "NASDAQ",
                "currency": "USD",
                "local_symbol": "MSFT",
            },
            "mode_code": self.mode_code,
            "market_mode": self.mode,
            "tick_count": self.ticks,
            "historical_bars": [{
                "event_at": dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
                "open": "510.00", "high": "510.75", "low": "501.44",
                "close": "502.43", "volume": "85329",
            }],
            "errors": [],
            "retrieved_at": now,
            "transport_status": "SUCCESS",
        }


def evidence(**kwargs):
    return capture_probe(build_request(adapter_version="9.81.1.post1"), FixtureTransport(**kwargs))


def reseal(value, model, hash_field, **changes):
    raw = value.model_dump(mode="python")
    raw.update(changes)
    raw.pop(hash_field)
    return _seal(model, hash_field, **raw)


def test_contract_fixture_is_observed_untrusted_and_safety_is_frozen():
    value = evidence()
    assert validate_evidence(value.model_dump_json()) == value
    assert value.source_kind is SourceKind.CONTRACT_TEST_ONLY
    assert value.evidence_state == "OBSERVED_UNTRUSTED"
    assert value.fixture_truth is value.verified is value.trusted is value.qvm_admissible is False
    assert value.provider_admission == value.custody_worm_legal == "NOT_PROVISIONED"
    assert value.gate_states == tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate)
    assert value.trade_decision == "NO_TRADE"
    assert value.signals_generated is value.live_execution_enabled is False
    assert value.backtesting == "NOT_AUTHORIZED"
    assert value.real_route == "QVM_NOT_READY"
    assert value.global_readiness == "INSUFFICIENT_REAL_DATA"


def test_localhost_profile_port_and_read_only_capability_are_closed():
    request = build_request(adapter_version="9.81.1.post1")
    assert request.config.host == "127.0.0.1" and request.config.port == 7496
    assert request.config.account_requests_enabled is False
    assert request.config.order_capability_enabled is False
    for changes in (
        {"host": "localhost"}, {"host": "192.168.1.2"}, {"port": 7497},
        {"account_requests_enabled": True}, {"order_capability_enabled": True},
    ):
        with pytest.raises(ValidationError):
            ProbeConfig.model_validate({**request.config.model_dump(), **changes})


def test_unicode_confusables_and_ambiguous_identity_fail():
    for changes in (
        {"symbol": "ＭＳＦＴ"}, {"security_master_id": "security.us.msft.xnaѕ"},
        {"permanent_id": "MSFT"}, {"conid": 1}, {"primary_exchange": "NYSE"},
    ):
        with pytest.raises(ValidationError):
            GovernedInstrument.model_validate({**GovernedInstrument().model_dump(), **changes})
    with pytest.raises(ValidationError):
        ResolvedContract.model_validate({
            **evidence().resolved_contract.model_dump(), "local_symbol": "ＭＳＦＴ"
        })


@pytest.mark.parametrize("mode,code", [
    ("REALTIME", 1), ("FROZEN", 2), ("DELAYED", 3), ("DELAYED_FROZEN", 4)
])
def test_official_market_mode_mapping_is_distinct(mode, code):
    value = evidence(mode=mode, mode_code=code)
    assert value.confirmed_market_data_mode is MarketDataMode(mode)
    assert value.mode_confirmed_by_callback is True


def test_unconfirmed_mode_cannot_be_spoofed_or_confused():
    with pytest.raises(ValidationError, match="unconfirmed"):
        evidence(mode="DELAYED", mode_code=None)
    delayed = evidence(mode="DELAYED", mode_code=3)
    for mode in ("REALTIME", "DELAYED_FROZEN"):
        with pytest.raises((ValidationError, ProbeError)):
            validate_evidence(reseal(delayed, ProbeEvidence, "evidence_hash",
                                     confirmed_market_data_mode=mode))


def test_stream_timeout_is_absence_never_zero_tick_observation():
    value = evidence(ticks=0)
    assert value.tick_status is TickStatus.ABSENT_TIMEOUT
    assert value.tick_count == 0
    assert value.tick_timeout_seconds == 12
    present = evidence(ticks=2)
    assert present.tick_status is TickStatus.PRESENT and present.tick_timeout_seconds is None
    with pytest.raises(ValidationError):
        reseal(value, ProbeEvidence, "evidence_hash", tick_status="PRESENT")


def test_digests_and_fully_resealed_material_provenance_swaps_fail():
    value = evidence()
    for changes in (
        {"raw_digest": "0" * 64}, {"material_digest": "0" * 64},
        {"provenance_digest": "0" * 64},
    ):
        with pytest.raises((ValidationError, ProbeError)):
            validate_evidence(reseal(value, ProbeEvidence, "evidence_hash", **changes))


def test_model_copy_construct_json_duck_and_trust_promotions_fail():
    value = evidence()
    for forged in (
        value.model_copy(update={"trusted": True}),
        ProbeEvidence.model_construct(**{**value.model_dump(), "qvm_admissible": True}),
        value.model_dump_json().replace("OBSERVED_UNTRUSTED", "TRUSTED"),
        object(),
    ):
        with pytest.raises((ValidationError, ProbeError)):
            validate_evidence(forged)
    raw = value.model_dump(mode="python")
    raw.update({"custody_worm_legal": "PROVISIONED_REAL", "provider_admission": "TRUSTED"})
    with pytest.raises(ProbeError):
        validate_evidence(raw)


def test_fake_real_transport_and_secret_exception_are_sanitized():
    class FakeReal(FixtureTransport):
        source_kind = SourceKind.REAL_LOCAL_IBKR

    with pytest.raises(ProbeError, match="caller-controlled"):
        capture_probe(build_request(adapter_version="9.81.1.post1"), FakeReal())

    class Leaky(FixtureTransport):
        def collect(self, config, instrument):
            raise RuntimeError("password=SENSITIVE_SENTINEL account=U1234567")

    with pytest.raises(ProbeError) as caught:
        capture_probe(build_request(adapter_version="9.81.1.post1"), Leaky())
    assert "SENSITIVE_SENTINEL" not in str(caught.value)
    assert "U1234567" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_append_only_persistence_contains_no_account_or_secret(tmp_path):
    output = tmp_path / "evidence.json"
    persist_evidence(evidence(), output)
    parsed = json.loads(output.read_text())
    text = output.read_text()
    assert parsed["evidence_state"] == "OBSERVED_UNTRUSTED"
    assert "U1234567" not in text and "password=" not in text.lower()
    with pytest.raises(ProbeError, match="already exists"):
        persist_evidence(evidence(), output)


def test_ibkr_daily_date_is_not_misread_as_epoch_seconds():
    assert _ibkr_bar_time("20260904") == dt.datetime(2026, 9, 4, tzinfo=dt.UTC)
    assert _ibkr_bar_time("1788480000") == dt.datetime(2026, 9, 4, tzinfo=dt.UTC)
    for bad in ("２０２６０９０４", "2026-09-04", "account=U123"):
        with pytest.raises(ProbeError):
            _ibkr_bar_time(bad)
