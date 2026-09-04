import datetime as dt
import inspect
import json
import traceback

import pytest
from pydantic import ValidationError

import governance.ibkr_probe as probe_module
from governance.canonical import typed_hash
from governance.ibkr_probe import (
    ChannelStatus,
    GovernedInstrument,
    HistoricalBar,
    MarketDataMode,
    ProbeConfig,
    ProbeError,
    ProbeEvidence,
    ProbeRequest,
    ResolvedContract,
    SourceKind,
    TickStatus,
    TransportStatus,
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
            "historical_bars": [
                {
                    "event_at": dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
                    "open": "510.00",
                    "high": "510.75",
                    "low": "501.44",
                    "close": "502.43",
                    "volume": "85329",
                }
            ],
            "errors": [],
            "retrieved_at": now,
        }


def evidence(**kwargs):
    return capture_probe(build_request(adapter_version="9.81.1.post1"), FixtureTransport(**kwargs))


def reseal(value, model, hash_field, **changes):
    raw = value.model_dump(mode="python")
    raw.update(changes)
    raw.pop(hash_field)
    return _seal(model, hash_field, **raw)


def fully_reseal_evidence(value, **changes):
    raw = value.model_dump(mode="python")
    raw.update(changes)
    bars = tuple(HistoricalBar.model_validate(x) for x in raw["historical_bars"])
    raw["material_digest"] = typed_hash([x.model_dump(mode="json") for x in bars])
    raw_view = {
        "server_version": raw["tws_server_version"],
        "server_current_time": raw["server_current_time"],
        "contract": ResolvedContract.model_validate(raw["resolved_contract"]).model_dump(
            mode="json"
        ),
        "mode_code": raw["official_market_data_type_code"],
        "tick_count": raw["tick_count"],
        "bars": [x.model_dump(mode="json") for x in bars],
        "errors": [x.model_dump(mode="json") for x in raw["sanitized_errors"]],
    }
    raw["raw_digest"] = typed_hash(raw_view)
    request = ProbeRequest.model_validate(raw["request"])
    raw["provenance_digest"] = typed_hash(
        {
            "request_hash": request.request_hash,
            "raw_digest": raw["raw_digest"],
            "material_digest": raw["material_digest"],
            "lineage_digest": request.instrument.lineage_digest,
        }
    )
    raw.pop("evidence_hash")
    return _seal(ProbeEvidence, "evidence_hash", **raw)


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
        {"host": "localhost"},
        {"host": "192.168.1.2"},
        {"port": 7497},
        {"account_requests_enabled": True},
        {"order_capability_enabled": True},
    ):
        with pytest.raises(ValidationError):
            ProbeConfig.model_validate({**request.config.model_dump(), **changes})


def test_unicode_confusables_and_ambiguous_identity_fail():
    for changes in (
        {"symbol": "ＭＳＦＴ"},
        {"security_master_id": "security.us.msft.xnaѕ"},
        {"permanent_id": "MSFT"},
        {"conid": 1},
        {"primary_exchange": "NYSE"},
    ):
        with pytest.raises(ValidationError):
            GovernedInstrument.model_validate({**GovernedInstrument().model_dump(), **changes})
    with pytest.raises(ValidationError):
        ResolvedContract.model_validate(
            {**evidence().resolved_contract.model_dump(), "local_symbol": "ＭＳＦＴ"}
        )


@pytest.mark.parametrize(
    "mode,code", [("REALTIME", 1), ("FROZEN", 2), ("DELAYED", 3), ("DELAYED_FROZEN", 4)]
)
def test_official_market_mode_mapping_is_distinct(mode, code):
    value = evidence(mode=mode, mode_code=code)
    assert value.confirmed_market_data_mode is MarketDataMode(mode)
    assert value.mode_confirmed_by_callback is True


def test_unconfirmed_mode_cannot_be_spoofed_or_confused():
    with pytest.raises(ProbeError, match="sanitized"):
        evidence(mode="DELAYED", mode_code=None)
    delayed = evidence(mode="DELAYED", mode_code=3)
    for mode in ("REALTIME", "DELAYED_FROZEN"):
        with pytest.raises((ValidationError, ProbeError)):
            validate_evidence(
                reseal(delayed, ProbeEvidence, "evidence_hash", confirmed_market_data_mode=mode)
            )


def test_stream_timeout_is_absence_never_zero_tick_observation():
    value = evidence(ticks=0)
    assert value.tick_status is TickStatus.ABSENT_TIMEOUT
    assert value.tick_count == 0
    assert value.tick_timeout_seconds == 12
    assert value.stream_transport_status is ChannelStatus.TIMEOUT_NO_DATA
    assert value.historical_transport_status is ChannelStatus.SUCCESS
    assert value.transport_status is TransportStatus.PARTIAL
    present = evidence(ticks=2)
    assert present.tick_status is TickStatus.PRESENT and present.tick_timeout_seconds is None
    assert present.transport_status is TransportStatus.SUCCESS
    with pytest.raises(ValidationError):
        reseal(value, ProbeEvidence, "evidence_hash", tick_status="PRESENT")


def test_digests_and_fully_resealed_material_provenance_swaps_fail():
    value = evidence()
    for changes in (
        {"raw_digest": "0" * 64},
        {"material_digest": "0" * 64},
        {"provenance_digest": "0" * 64},
    ):
        with pytest.raises((ValidationError, ProbeError)):
            validate_evidence(reseal(value, ProbeEvidence, "evidence_hash", **changes))


def test_real_provenance_label_no_longer_exists_and_cannot_be_resealed():
    value = evidence(mode="DELAYED", mode_code=3)
    for mode, code in (("REALTIME", 1), ("FROZEN", 2), ("DELAYED_FROZEN", 4)):
        with pytest.raises(ValidationError):
            fully_reseal_evidence(
                value,
                source_kind="REAL_LOCAL_IBKR",
                confirmed_market_data_mode=mode,
                official_market_data_type_code=code,
            )


def test_transport_monkeypatch_subclass_and_replacement_cannot_assert_real(monkeypatch):
    fixture = evidence(mode="REALTIME", mode_code=1, ticks=2)
    monkeypatch.setattr(probe_module, "IBKRLocalTransport", FixtureTransport)
    observed = probe_module.execute_local_observation_probe(
        build_request(adapter_version="9.81.1.post1")
    )
    assert observed.source_kind is SourceKind.LOCAL_IBKR_OBSERVATION_UNAUTHENTICATED
    assert observed.confirmed_market_data_mode is MarketDataMode.DELAYED
    assert observed.evidence_state == "OBSERVED_UNTRUSTED"
    assert observed.verified is observed.trusted is observed.qvm_admissible is False
    monkeypatch.setattr(probe_module, "_capture_probe", lambda *args: fixture)
    replaced = probe_module.execute_local_observation_probe(
        build_request(adapter_version="9.81.1.post1")
    )
    assert replaced.source_kind is SourceKind.CONTRACT_TEST_ONLY
    assert (
        capture_probe(build_request(adapter_version="9.81.1.post1"), FixtureTransport()).source_kind
        is SourceKind.CONTRACT_TEST_ONLY
    )


def test_all_untrusted_construction_routes_fail_to_promote_real():
    value = evidence()
    raw = value.model_dump(mode="python")
    raw.update({"source_kind": "REAL_LOCAL_IBKR"})
    raw.pop("evidence_hash")
    with pytest.raises(ValidationError):
        _seal(ProbeEvidence, "evidence_hash", **raw)
    candidates = (
        {**value.model_dump(mode="python"), "source_kind": "REAL_LOCAL_IBKR"},
        value.model_dump_json().replace("CONTRACT_TEST_ONLY", "REAL_LOCAL_IBKR"),
        value.model_copy(update={"source_kind": "REAL_LOCAL_IBKR"}),
        ProbeEvidence.model_construct(
            **{**value.model_dump(mode="python"), "source_kind": "REAL_LOCAL_IBKR"}
        ),
    )
    for candidate in candidates:
        with pytest.raises(ProbeError, match="invalid probe evidence"):
            validate_evidence(candidate)


def test_arbitrary_resealed_raw_digest_and_out_of_window_bars_fail():
    value = evidence()
    with pytest.raises(ValidationError, match="raw digest mismatch"):
        reseal(value, ProbeEvidence, "evidence_hash", raw_digest="a" * 64)
    stale_bar = value.historical_bars[0].model_copy(
        update={"event_at": dt.datetime(1999, 1, 1, tzinfo=dt.UTC)}
    )
    with pytest.raises(ValidationError, match="outside the governed request window"):
        fully_reseal_evidence(value, historical_bars=(stale_bar,))
    future_bar = value.historical_bars[0].model_copy(
        update={"event_at": value.observed_at + dt.timedelta(days=2)}
    )
    with pytest.raises(ValidationError, match="outside the governed request window"):
        fully_reseal_evidence(value, historical_bars=(future_bar,))


def test_external_secret_values_are_erased_from_error_graph_and_traceback():
    sentinels = ("password=SENSITIVE_SENTINEL", "account=U1234567")
    base = evidence().model_dump(mode="python")
    for field, secret in (("source_kind", sentinels[0]), ("api_version", sentinels[1])):
        forged = {**base, field: secret}
        with pytest.raises(ProbeError) as caught:
            validate_evidence(forged)
        rendered = (
            str(caught.value)
            + repr(caught.value)
            + "".join(traceback.format_exception(caught.value))
        )
        assert all(secret not in rendered for secret in sentinels)
        assert caught.value.__cause__ is caught.value.__context__ is None

    class LeakyIdentity(FixtureTransport):
        def collect(self, config, instrument):
            result = super().collect(config, instrument)
            result.pop("transport_status", None)
            result["resolved_contract"]["local_symbol"] = sentinels[1]
            return result

    with pytest.raises(ProbeError) as caught:
        capture_probe(build_request(adapter_version="9.81.1.post1"), LeakyIdentity())
    rendered = (
        str(caught.value) + repr(caught.value) + "".join(traceback.format_exception(caught.value))
    )
    assert all(secret not in rendered for secret in sentinels)
    assert caught.value.__cause__ is caught.value.__context__ is None


@pytest.mark.parametrize("target", ["contract", "callback", "error", "status", "api"])
def test_provider_callback_fields_never_leak_rejected_values(target):
    secret = "account=U1234567-password=SENSITIVE_SENTINEL"

    class Malicious(FixtureTransport):
        @property
        def api_version(self):
            if target == "api":
                raise RuntimeError(secret)
            return "9.81.1.post1"

        def collect(self, config, instrument):
            result = super().collect(config, instrument)
            if target == "contract":
                result["resolved_contract"]["local_symbol"] = secret
            elif target == "callback":
                result["mode_code"] = secret
            elif target == "error":
                result["errors"] = [{"request_id": 1, "code": 500, "category": secret}]
            elif target == "status":
                result["transport_status"] = secret
            return result

    with pytest.raises(ProbeError) as caught:
        capture_probe(build_request(adapter_version="9.81.1.post1"), Malicious())
    rendered = (
        str(caught.value) + repr(caught.value) + "".join(traceback.format_exception(caught.value))
    )
    assert secret not in rendered
    assert caught.value.__cause__ is caught.value.__context__ is None


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
        source_kind = SourceKind.LOCAL_IBKR_OBSERVATION_UNAUTHENTICATED

    fake = FakeReal()
    fake.__class__.__module__ = "governance.ibkr_probe"
    assert (
        capture_probe(build_request(adapter_version="9.81.1.post1"), fake).source_kind
        is SourceKind.CONTRACT_TEST_ONLY
    )

    class Leaky(FixtureTransport):
        def collect(self, config, instrument):
            raise RuntimeError("password=SENSITIVE_SENTINEL account=U1234567")

    with pytest.raises(ProbeError) as caught:
        capture_probe(build_request(adapter_version="9.81.1.post1"), Leaky())
    assert "SENSITIVE_SENTINEL" not in str(caught.value)
    assert "U1234567" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_no_local_authentication_signer_or_secret_is_introspectable():
    module_text = inspect.getsource(probe_module)
    assert "hmac" not in module_text.lower()
    assert "boundary_attestation" not in module_text
    assert "REAL_LOCAL_IBKR" not in module_text
    assert probe_module.execute_local_observation_probe.__closure__ is None
    for function in (probe_module.execute_local_observation_probe, probe_module.validate_evidence):
        defaults = (function.__defaults__ or ()) + tuple((function.__kwdefaults__ or {}).values())
        assert not any(
            token in str(value).lower()
            for value in defaults
            for token in ("key", "secret", "signer", "hmac")
        )


def test_malicious_model_dump_serializer_repr_str_and_property_are_sanitized():
    secret = "password=SENSITIVE_SENTINEL-account=U1234567"

    class MaliciousEvidence(ProbeEvidence):
        def model_dump(self, *args, **kwargs):
            raise RuntimeError(secret)

        def __repr__(self):
            raise RuntimeError(secret)

        def __str__(self):
            raise RuntimeError(secret)

    malicious = MaliciousEvidence.model_construct(**evidence().model_dump(mode="python"))

    class MaliciousDict(dict):
        def items(self):
            raise RuntimeError(secret)

        def __repr__(self):
            raise RuntimeError(secret)

        def __str__(self):
            raise RuntimeError(secret)

    for candidate in (malicious, MaliciousDict(evidence().model_dump(mode="python"))):
        with pytest.raises(ProbeError) as caught:
            validate_evidence(candidate)
        rendered = str(caught.value) + repr(caught.value) + "".join(
            traceback.format_exception(caught.value)
        )
        assert secret not in rendered
        assert caught.value.__cause__ is caught.value.__context__ is None


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
