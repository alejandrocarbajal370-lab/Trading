"""Fail-closed IBKR read-only market-observation contract foundation."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from enum import StrEnum
from itertools import pairwise
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "ibkr-read-only-observation-v1"
SHA256 = r"^[0-9a-f]{64}$"
SAFE_ID = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
SECRET_FIELD = re.compile(
    r"(?i)(password|passphrase|secret|api[_-]?key|token|cookie|cert(?:ificate)?|"
    r"private[_-]?key|session|authorization|bearer|oauth|jwt|credential)"
)
CREDENTIAL_REFERENCE = re.compile(r"^external-vault-reference:[a-z0-9][a-z0-9._:-]{0,127}$")
FIXTURE_LINEAGE_DIGEST = hashlib.sha256(b"contract-test-lineage").hexdigest()


class ObservationError(ValueError):
    """An observation failed the code-owned contract boundary."""


class ProviderId(StrEnum):
    IBKR = "provider.ibkr"


class AdapterId(StrEnum):
    IBKR_CONTRACT_FIXTURE = "adapter.ibkr.contract_fixture"


class DatasetClass(StrEnum):
    PRICES_OHLCV = "prices_ohlcv"
    CORPORATE_ACTIONS = "corporate_actions"
    SECURITY_MASTER_SYMBOLOGY = "security_master_symbology"
    SHARES_OUTSTANDING_PIT = "shares_outstanding_pit"
    FX = "fx"
    FUNDAMENTALS_COMPLEMENT = "fundamentals_complement"


class DatasetSupport(StrEnum):
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"
    NOT_YET_PROVISIONED = "NOT_YET_PROVISIONED"


class MarketDataMode(StrEnum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    FROZEN = "FROZEN"
    UNKNOWN = "UNKNOWN"


class ProvisioningState(StrEnum):
    NOT_PROVISIONED = "NOT_PROVISIONED"
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"


class EvidenceState(StrEnum):
    OBSERVED_UNTRUSTED = "OBSERVED_UNTRUSTED"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: dt.datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{field} must be canonical UTC")


def _dump(value: BaseModel, hash_field: str) -> dict[str, Any]:
    return value.model_dump(mode="json", exclude={hash_field}, warnings=False)


def _check_hash(value: BaseModel, hash_field: str) -> None:
    if typed_hash(_dump(value, hash_field)) != getattr(value, hash_field):
        raise ValueError(f"{hash_field} does not match canonical payload")


def _seal(model: type[ContractModel], hash_field: str, **values: Any):
    raw = model.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(_dump(raw, hash_field))
    return model(**values)


def _revalidate(model: type[ContractModel], value: Any, label: str):
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise ObservationError(f"{label} contains undeclared fields")
        value = value.model_dump(mode="python", warnings=False)
    try:
        return model.model_validate(value)
    except Exception as exc:
        raise ObservationError(f"invalid {label}") from exc


class CredentialReference(ContractModel):
    """Sanitized external reference: never credential material or a claim of provisioning."""

    reference_digest: str = Field(pattern=SHA256)
    scheme: Literal["EXTERNAL_SECRET_REFERENCE_SHA256"] = "EXTERNAL_SECRET_REFERENCE_SHA256"
    provisioning_state: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED

    @classmethod
    def from_reference(cls, reference: str) -> CredentialReference:
        if (
            not CREDENTIAL_REFERENCE.fullmatch(reference)
            or SECRET_FIELD.search(reference.removeprefix("external-vault-reference:"))
        ):
            raise ObservationError("credential reference must be sanitized")
        return cls(reference_digest=hashlib.sha256(reference.encode()).hexdigest())


class InstrumentIdentity(ContractModel):
    security_master_id: str = Field(pattern=SAFE_ID)
    permanent_id: str = Field(pattern=SAFE_ID)
    symbology_lineage_digest: str = Field(pattern=SHA256)
    display_symbol: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def reject_ticker_identity(self):
        if self.security_master_id == self.display_symbol or self.permanent_id == self.display_symbol:
            raise ValueError("ticker alone cannot be permanent identity")
        if (
            self.security_master_id,
            self.permanent_id,
            self.symbology_lineage_digest,
            self.display_symbol,
        ) != (
            "security.contract-test-001",
            "ibkr.conid.contract-test-001",
            FIXTURE_LINEAGE_DIGEST,
            "EXAMPLE",
        ):
            raise ValueError("instrument identity does not match code-owned fixture binding")
        return self


class ObservationRequest(ContractModel):
    provider: Literal[ProviderId.IBKR] = ProviderId.IBKR
    adapter: Literal[AdapterId.IBKR_CONTRACT_FIXTURE] = AdapterId.IBKR_CONTRACT_FIXTURE
    dataset: Literal[DatasetClass.PRICES_OHLCV] = DatasetClass.PRICES_OHLCV
    endpoint_id: Literal["ibkr.marketdata.historical_bars"] = "ibkr.marketdata.historical_bars"
    scope: Literal["MARKET_OBSERVATION_READ_ONLY"] = "MARKET_OBSERVATION_READ_ONLY"
    requested_mode: MarketDataMode
    timing_sensitive: bool
    instrument: InstrumentIdentity
    request_parameters_digest: str = Field(pattern=SHA256)
    credential: CredentialReference
    request_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_request(self):
        _revalidate(InstrumentIdentity, self.instrument, "instrument")
        _revalidate(CredentialReference, self.credential, "credential")
        if self.timing_sensitive and self.requested_mode is MarketDataMode.UNKNOWN:
            raise ValueError("UNKNOWN mode cannot satisfy timing-sensitive use")
        _check_hash(self, "request_hash")
        return self


class PageMetadata(ContractModel):
    page_index: int = Field(ge=0)
    cursor_digest: str | None = Field(default=None, pattern=SHA256)
    next_cursor_digest: str | None = Field(default=None, pattern=SHA256)
    is_last: bool


class ResponseMetadata(ContractModel):
    status: Literal["SUCCESS"]
    error_code: None = None
    market_data_mode: MarketDataMode
    page: PageMetadata


class RawObservationEnvelope(ContractModel):
    contract_version: Literal["ibkr-read-only-observation-v1"] = CONTRACT_VERSION
    request: ObservationRequest
    payload_digest: str = Field(pattern=SHA256)
    payload_size: int = Field(ge=1)
    market_event_at: dt.datetime
    retrieved_at: dt.datetime
    observed_at: dt.datetime
    response: ResponseMetadata
    evidence_state: Literal[EvidenceState.OBSERVED_UNTRUSTED] = EvidenceState.OBSERVED_UNTRUSTED
    historical_completeness: Literal["NOT_CLAIMED"] = "NOT_CLAIMED"
    provider_admission: Literal["NOT_PROVISIONED"] = "NOT_PROVISIONED"
    envelope_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_envelope(self):
        request = _revalidate(ObservationRequest, self.request, "request")
        response = _revalidate(ResponseMetadata, self.response, "response")
        for field in ("market_event_at", "retrieved_at", "observed_at"):
            _utc(getattr(self, field), field)
        if self.market_event_at > self.retrieved_at or self.retrieved_at > self.observed_at:
            raise ValueError("market, retrieval and observation chronology is invalid")
        if response.market_data_mode is not request.requested_mode:
            raise ValueError("returned market-data mode differs from requested mode")
        if request.timing_sensitive and response.market_data_mode is MarketDataMode.UNKNOWN:
            raise ValueError("UNKNOWN response mode cannot satisfy timing-sensitive use")
        _check_hash(self, "envelope_hash")
        return self


class ObservationBatch(ContractModel):
    envelopes: tuple[RawObservationEnvelope, ...]
    evidence_state: Literal[EvidenceState.OBSERVED_UNTRUSTED] = EvidenceState.OBSERVED_UNTRUSTED
    durable_replay: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    trust_root: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    authority: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    independent_verifier: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    signals_generated: Literal[False] = False
    live_execution_enabled: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    batch_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_batch(self):
        envelopes = tuple(_revalidate(RawObservationEnvelope, x, "envelope") for x in self.envelopes)
        if not envelopes:
            raise ValueError("batch cannot be empty")
        pages = tuple(x.response.page for x in envelopes)
        if any(x.request.request_hash != envelopes[0].request.request_hash for x in envelopes[1:]):
            raise ValueError("all pages must bind the same canonical request")
        if tuple(p.page_index for p in pages) != tuple(range(len(pages))):
            raise ValueError("pages must be complete and ordered")
        for current, following in pairwise(pages):
            if current.is_last or current.next_cursor_digest != following.cursor_digest:
                raise ValueError("pagination cursor chain is invalid")
        if not pages[-1].is_last or pages[-1].next_cursor_digest is not None:
            raise ValueError("last page marker is invalid")
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError("all gates must remain OPEN_EXTERNAL")
        _check_hash(self, "batch_hash")
        return self


class ReadOnlyMarketObservationAdapter(Protocol):
    provider_id: Literal[ProviderId.IBKR]
    provisioning_state: ProvisioningState

    def observe(self, request: ObservationRequest) -> tuple[bytes, ResponseMetadata, dt.datetime]: ...


class ContractFixtureAdapter:
    provider_id = ProviderId.IBKR
    provisioning_state = ProvisioningState.CONTRACT_TEST_ONLY

    def observe(self, request: ObservationRequest) -> tuple[bytes, ResponseMetadata, dt.datetime]:
        canonical = _revalidate(ObservationRequest, request, "request")
        if canonical.requested_mode is not MarketDataMode.DELAYED:
            raise ObservationError("contract fixture provides DELAYED data only")
        page = PageMetadata(page_index=0, is_last=True)
        response = ResponseMetadata(status="SUCCESS", market_data_mode=MarketDataMode.DELAYED, page=page)
        return b'{"bars":[{"close":"100.00"}]}', response, dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


DATASET_SUPPORT = {
    DatasetClass.PRICES_OHLCV: DatasetSupport.CONTRACT_TEST_ONLY,
    DatasetClass.CORPORATE_ACTIONS: DatasetSupport.NOT_YET_PROVISIONED,
    DatasetClass.SECURITY_MASTER_SYMBOLOGY: DatasetSupport.NOT_YET_PROVISIONED,
    DatasetClass.SHARES_OUTSTANDING_PIT: DatasetSupport.NOT_YET_PROVISIONED,
    DatasetClass.FX: DatasetSupport.NOT_YET_PROVISIONED,
    DatasetClass.FUNDAMENTALS_COMPLEMENT: DatasetSupport.NOT_YET_PROVISIONED,
}


def build_request(*, mode: MarketDataMode, timing_sensitive: bool = False) -> ObservationRequest:
    instrument = InstrumentIdentity(
        security_master_id="security.contract-test-001",
        permanent_id="ibkr.conid.contract-test-001",
        symbology_lineage_digest=FIXTURE_LINEAGE_DIGEST,
        display_symbol="EXAMPLE",
    )
    credential = CredentialReference.from_reference("external-vault-reference:contract-test")
    return _seal(
        ObservationRequest,
        "request_hash",
        requested_mode=mode,
        timing_sensitive=timing_sensitive,
        instrument=instrument,
        request_parameters_digest=hashlib.sha256(b"contract-test-request").hexdigest(),
        credential=credential,
    )


def observe_contract_fixture(request: ObservationRequest, *, observed_at: dt.datetime) -> ObservationBatch:
    adapter = ContractFixtureAdapter()
    canonical = _revalidate(ObservationRequest, request, "request")
    payload, response, event_at = adapter.observe(canonical)
    _utc(observed_at, "observed_at")
    envelope = _seal(
        RawObservationEnvelope,
        "envelope_hash",
        request=canonical,
        payload_digest=hashlib.sha256(payload).hexdigest(),
        payload_size=len(payload),
        market_event_at=event_at,
        retrieved_at=observed_at,
        observed_at=observed_at,
        response=response,
    )
    return _seal(
        ObservationBatch,
        "batch_hash",
        envelopes=(envelope,),
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    )


def validate_observation_batch(value: Any) -> ObservationBatch:
    if isinstance(value, str):
        try:
            return ObservationBatch.model_validate_json(value)
        except Exception as exc:
            raise ObservationError("invalid observation batch") from exc
    return _revalidate(ObservationBatch, value, "observation batch")


def evaluate_real_route(*, adapter: ReadOnlyMarketObservationAdapter | None = None) -> None:
    if adapter is not None:
        raise ObservationError("caller-controlled adapters cannot enter the REAL route")
    raise ObservationError("IBKR REAL observation is NOT_PROVISIONED")


def assert_payload(envelope: RawObservationEnvelope, payload: bytes) -> None:
    canonical = _revalidate(RawObservationEnvelope, envelope, "envelope")
    if len(payload) != canonical.payload_size or hashlib.sha256(payload).hexdigest() != canonical.payload_digest:
        raise ObservationError("payload bytes do not match the content-addressed envelope")
