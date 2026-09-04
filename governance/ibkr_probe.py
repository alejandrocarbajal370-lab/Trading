"""Explicit localhost-only IBKR observation probe; never an admission or trading route."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import threading
import time
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "ibkr-read-only-local-observation-probe-v2"
SHA256 = r"^[0-9a-f]{64}$"
SAFE_ID = r"^[a-z0-9][a-z0-9._:-]{2,127}$"
SAFE_ADAPTER_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
MSFT_LINEAGE = hashlib.sha256(
    b"ibkr-probe-v1|security.us.msft.xnas|ibkr.conid.272093|MSFT|STK|SMART|NASDAQ|USD"
).hexdigest()
ERROR_CLASS = {
    200: "CONTRACT_RESOLUTION",
    354: "MARKET_DATA_PERMISSION",
    10167: "MARKET_DATA_PERMISSION",
}


class ProbeError(ValueError):
    """A probe input or result failed the sealed boundary."""


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MarketDataMode(StrEnum):
    REALTIME = "REALTIME"
    FROZEN = "FROZEN"
    DELAYED = "DELAYED"
    DELAYED_FROZEN = "DELAYED_FROZEN"
    UNKNOWN = "UNKNOWN"


class TickStatus(StrEnum):
    PRESENT = "PRESENT"
    ABSENT_TIMEOUT = "ABSENT_TIMEOUT"
    NOT_REQUESTED = "NOT_REQUESTED"


class TransportStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED_SANITIZED = "FAILED_SANITIZED"


class ChannelStatus(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT_NO_DATA = "TIMEOUT_NO_DATA"
    FAILED_SANITIZED = "FAILED_SANITIZED"


class SourceKind(StrEnum):
    LOCAL_IBKR_OBSERVATION_UNAUTHENTICATED = "LOCAL_IBKR_OBSERVATION_UNAUTHENTICATED"
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"


def _utc(value: dt.datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{label} must be canonical UTC")


def _dump(value: BaseModel, hash_field: str) -> dict[str, Any]:
    return value.model_dump(mode="json", exclude={hash_field}, warnings=False)


def _check_hash(value: BaseModel, hash_field: str) -> None:
    if typed_hash(_dump(value, hash_field)) != getattr(value, hash_field):
        raise ValueError(f"{hash_field} does not match canonical payload")


def _seal(model: type[ContractModel], hash_field: str, **values: Any) -> Any:
    raw = model.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(_dump(raw, hash_field))
    return model(**values)


def _revalidate(model: type[ContractModel], value: Any, label: str) -> Any:
    failed = False
    try:
        if isinstance(value, BaseModel):
            if set(value.__dict__) - set(type(value).model_fields):
                raise ValueError("undeclared fields")
            value = value.model_dump(mode="python", warnings=False)
        elif not isinstance(value, (dict, str)):
            raise TypeError("unsupported input")
        validated = (
            model.model_validate_json(value)
            if isinstance(value, str)
            else model.model_validate(value)
        )
    except BaseException:  # noqa: BLE001 -- caller hooks may throw secret-bearing exceptions
        failed = True
        validated = None
    if failed:
        # Raise outside the handler: neither __cause__ nor __context__ can retain rejected data.
        raise ProbeError(f"invalid {label}")
    return validated


def _safe_external(model: type[ContractModel], value: Any, label: str) -> Any:
    """Validate provider/caller material without retaining a leaky exception chain."""
    return _revalidate(model, value, label)


def _ibkr_bar_time(value: Any) -> dt.datetime:
    text = str(value)
    try:
        if len(text) == 8 and text.isascii() and text.isdigit():
            return dt.datetime.strptime(text, "%Y%m%d").replace(tzinfo=dt.UTC)
        if text.isascii() and text.isdigit():
            return dt.datetime.fromtimestamp(int(text), dt.UTC)
    except (OverflowError, OSError, ValueError):
        raise ProbeError("invalid IBKR bar timestamp") from None
    raise ProbeError("invalid IBKR bar timestamp")


class ProbeConfig(ContractModel):
    profile_id: Literal["ibkr.localhost.tws-live-read-only"] = "ibkr.localhost.tws-live-read-only"
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: Literal[7496] = 7496
    client_id: int = Field(default=71, ge=1, le=999)
    stream_seconds: int = Field(default=12, ge=1, le=30)
    historical_enabled: Literal[True] = True
    account_requests_enabled: Literal[False] = False
    order_capability_enabled: Literal[False] = False

    @model_validator(mode="after")
    def localhost_only(self):
        if not ipaddress.ip_address(self.host).is_loopback:
            raise ValueError("probe host must be loopback")
        return self


class GovernedInstrument(ContractModel):
    binding_id: Literal["binding.ibkr.msft.xnas.v1"] = "binding.ibkr.msft.xnas.v1"
    security_master_id: Literal["security.us.msft.xnas"] = "security.us.msft.xnas"
    permanent_id: Literal["ibkr.conid.272093"] = "ibkr.conid.272093"
    conid: Literal[272093] = 272093
    symbol: Literal["MSFT"] = "MSFT"
    security_type: Literal["STK"] = "STK"
    exchange: Literal["SMART"] = "SMART"
    primary_exchange: Literal["NASDAQ"] = "NASDAQ"
    currency: Literal["USD"] = "USD"
    lineage_digest: Literal[MSFT_LINEAGE] = MSFT_LINEAGE
    admission: Literal["NOT_PROVISIONED"] = "NOT_PROVISIONED"


class ResolvedContract(ContractModel):
    conid: Literal[272093]
    symbol: Literal["MSFT"]
    security_type: Literal["STK"]
    exchange: Literal["SMART"]
    primary_exchange: Literal["NASDAQ"]
    currency: Literal["USD"]
    local_symbol: Literal["MSFT"]


class HistoricalBar(ContractModel):
    event_at: dt.datetime
    open: str = Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")
    high: str = Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")
    low: str = Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")
    close: str = Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")
    volume: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$")

    @model_validator(mode="after")
    def validate_bar(self):
        _utc(self.event_at, "bar event_at")
        numbers = tuple(float(getattr(self, x)) for x in ("open", "high", "low", "close"))
        if min(numbers) < 0 or float(self.volume) < 0 or numbers[1] < numbers[2]:
            raise ValueError("invalid OHLCV")
        return self


class SanitizedError(ContractModel):
    request_id: int
    code: int
    category: Literal["CONTRACT_RESOLUTION", "MARKET_DATA_PERMISSION", "PROVIDER_OTHER"]


class AdapterIdentity(ContractModel):
    api_version: str = Field(pattern=SAFE_ADAPTER_VERSION)


class CollectedResult(ContractModel):
    server_version: int = Field(ge=1)
    server_current_time: dt.datetime | None
    resolved_contract: ResolvedContract
    mode_code: Literal[1, 2, 3, 4] | None
    market_mode: MarketDataMode
    tick_count: int = Field(ge=0)
    historical_bars: tuple[HistoricalBar, ...]
    errors: tuple[SanitizedError, ...]
    retrieved_at: dt.datetime

    @model_validator(mode="after")
    def validate_result(self):
        _utc(self.retrieved_at, "retrieved_at")
        if self.server_current_time is not None:
            _utc(self.server_current_time, "server_current_time")
        expected = {
            1: MarketDataMode.REALTIME,
            2: MarketDataMode.FROZEN,
            3: MarketDataMode.DELAYED,
            4: MarketDataMode.DELAYED_FROZEN,
            None: MarketDataMode.UNKNOWN,
        }[self.mode_code]
        if self.market_mode is not expected:
            raise ValueError("market mode differs from callback code")
        if not self.historical_bars:
            raise ValueError("historical channel returned no data")
        return self


class ProbeRequest(ContractModel):
    provider: Literal["provider.ibkr"] = "provider.ibkr"
    adapter: Literal["adapter.ibkr.python-api.local-read-only-probe"] = (
        "adapter.ibkr.python-api.local-read-only-probe"
    )
    adapter_version: str = Field(pattern=SAFE_ADAPTER_VERSION)
    endpoint: Literal["TWS_API_MARKET_OBSERVATION_ONLY"] = "TWS_API_MARKET_OBSERVATION_ONLY"
    config: ProbeConfig
    instrument: GovernedInstrument
    requested_mode: Literal[MarketDataMode.REALTIME] = MarketDataMode.REALTIME
    stream_requested: Literal[True] = True
    historical_requested: Literal[True] = True
    historical_duration_days: Literal[2] = 2
    request_id: str = Field(pattern=SAFE_ID)
    request_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_request(self):
        _revalidate(ProbeConfig, self.config, "config")
        _revalidate(GovernedInstrument, self.instrument, "instrument")
        if self.request_id != f"ibkr-probe-{self.config.client_id}":
            raise ValueError("request id is not bound to client id")
        _check_hash(self, "request_hash")
        return self


class ProbeEvidence(ContractModel):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    source_kind: SourceKind
    request: ProbeRequest
    tws_server_version: int = Field(ge=1)
    api_version: str = Field(pattern=SAFE_ADAPTER_VERSION)
    server_current_time: dt.datetime | None
    resolved_contract: ResolvedContract
    requested_at: dt.datetime
    retrieved_at: dt.datetime
    observed_at: dt.datetime
    confirmed_market_data_mode: MarketDataMode
    official_market_data_type_code: Literal[1, 2, 3, 4] | None
    mode_confirmed_by_callback: bool
    tick_status: TickStatus
    tick_count: int = Field(ge=0)
    tick_timeout_seconds: int | None = Field(default=None, ge=1, le=30)
    historical_bars: tuple[HistoricalBar, ...]
    pagination: Literal["SINGLE_BOUNDED_REQUEST_NO_CURSOR"] = "SINGLE_BOUNDED_REQUEST_NO_CURSOR"
    transport_status: TransportStatus
    stream_transport_status: ChannelStatus
    historical_transport_status: ChannelStatus
    sanitized_errors: tuple[SanitizedError, ...]
    raw_digest: str = Field(pattern=SHA256)
    material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    evidence_state: Literal["OBSERVED_UNTRUSTED"] = "OBSERVED_UNTRUSTED"
    fixture_truth: Literal[False] = False
    verified: Literal[False] = False
    trusted: Literal[False] = False
    qvm_admissible: Literal[False] = False
    provider_admission: Literal["NOT_PROVISIONED"] = "NOT_PROVISIONED"
    custody_worm_legal: Literal["NOT_PROVISIONED"] = "NOT_PROVISIONED"
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    signals_generated: Literal[False] = False
    live_execution_enabled: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_evidence(self):
        request = _revalidate(ProbeRequest, self.request, "request")
        _revalidate(ResolvedContract, self.resolved_contract, "resolved contract")
        bars = tuple(_revalidate(HistoricalBar, x, "historical bar") for x in self.historical_bars)
        tuple(_revalidate(SanitizedError, x, "sanitized error") for x in self.sanitized_errors)
        for field in ("requested_at", "retrieved_at", "observed_at"):
            _utc(getattr(self, field), field)
        if self.server_current_time is not None:
            _utc(self.server_current_time, "server_current_time")
        if not self.requested_at <= self.retrieved_at <= self.observed_at:
            raise ValueError("probe timestamp chronology is invalid")
        if self.source_kind is SourceKind.CONTRACT_TEST_ONLY and self.fixture_truth:
            raise ValueError("fixture cannot produce truth")
        if (
            self.mode_confirmed_by_callback is False
            and self.confirmed_market_data_mode is not MarketDataMode.UNKNOWN
        ):
            raise ValueError("unconfirmed market mode must remain UNKNOWN")
        expected_mode = {
            1: MarketDataMode.REALTIME,
            2: MarketDataMode.FROZEN,
            3: MarketDataMode.DELAYED,
            4: MarketDataMode.DELAYED_FROZEN,
            None: MarketDataMode.UNKNOWN,
        }[self.official_market_data_type_code]
        if self.confirmed_market_data_mode is not expected_mode:
            raise ValueError("market mode differs from official callback code")
        if self.mode_confirmed_by_callback is not (self.official_market_data_type_code is not None):
            raise ValueError("market mode confirmation flag differs from callback presence")
        if self.tick_status is TickStatus.PRESENT and self.tick_count == 0:
            raise ValueError("present ticks require a positive count")
        if self.tick_status is TickStatus.ABSENT_TIMEOUT:
            if self.tick_count != 0 or self.tick_timeout_seconds != request.config.stream_seconds:
                raise ValueError("timeout must record absence, duration, and no fabricated ticks")
        elif self.tick_timeout_seconds is not None:
            raise ValueError("timeout duration is only valid for observational timeout")
        expected_stream = (
            ChannelStatus.SUCCESS
            if self.tick_status is TickStatus.PRESENT
            else ChannelStatus.TIMEOUT_NO_DATA
        )
        if self.stream_transport_status is not expected_stream:
            raise ValueError("stream transport status differs from observed stream outcome")
        if self.historical_transport_status is not ChannelStatus.SUCCESS or not bars:
            raise ValueError("historical success requires observed bars")
        expected_transport = (
            TransportStatus.SUCCESS
            if expected_stream is ChannelStatus.SUCCESS
            else TransportStatus.PARTIAL
        )
        if self.transport_status is not expected_transport:
            raise ValueError("aggregate transport status differs from channel outcomes")
        # IBKR daily bars are session dates normalized to UTC midnight. Compare calendar
        # dates so the first allowed session is not lost to the request's time-of-day.
        earliest_date = (self.requested_at - dt.timedelta(days=request.historical_duration_days)).date()
        latest_date = self.observed_at.date()
        if any(not earliest_date <= bar.event_at.date() <= latest_date for bar in bars):
            raise ValueError("historical bar is outside the governed request window")
        if tuple(self.gate_states) != tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate):
            raise ValueError("all ten gates must remain OPEN_EXTERNAL")
        raw_view = {
            "server_version": self.tws_server_version,
            "server_current_time": self.server_current_time,
            "contract": self.resolved_contract.model_dump(mode="json"),
            "mode_code": self.official_market_data_type_code,
            "tick_count": self.tick_count,
            "bars": [x.model_dump(mode="json") for x in bars],
            "errors": [x.model_dump(mode="json") for x in self.sanitized_errors],
        }
        if typed_hash(raw_view) != self.raw_digest:
            raise ValueError("raw digest mismatch")
        if typed_hash([x.model_dump(mode="json") for x in bars]) != self.material_digest:
            raise ValueError("material digest mismatch")
        if self.provenance_digest != typed_hash(
            {
                "request_hash": request.request_hash,
                "raw_digest": self.raw_digest,
                "material_digest": self.material_digest,
                "lineage_digest": request.instrument.lineage_digest,
            }
        ):
            raise ValueError("provenance digest mismatch")
        _check_hash(self, "evidence_hash")
        return self


class ProbeTransport(Protocol):
    api_version: str

    def collect(self, config: ProbeConfig, instrument: GovernedInstrument) -> dict[str, Any]: ...


def build_request(*, adapter_version: str, client_id: int = 71) -> ProbeRequest:
    values = {
        "adapter_version": adapter_version,
        "config": ProbeConfig(client_id=client_id),
        "instrument": GovernedInstrument(),
        "requested_mode": MarketDataMode.REALTIME,
        "stream_requested": True,
        "historical_requested": True,
        "request_id": f"ibkr-probe-{client_id}",
    }
    return _seal(ProbeRequest, "request_hash", **values)


def _capture_probe(
    request: Any, transport: ProbeTransport, source_kind: SourceKind
) -> ProbeEvidence:
    request = _revalidate(ProbeRequest, request, "probe request")
    started = dt.datetime.now(dt.UTC)
    failed = False
    try:
        result = transport.collect(request.config, request.instrument)
    except BaseException:  # noqa: BLE001 -- provider hooks may throw secret-bearing exceptions
        failed = True
        result = None
    if failed:
        raise ProbeError("sanitized IBKR probe failure")
    observed = dt.datetime.now(dt.UTC)
    external_failed = False
    try:
        identity = _safe_external(
            AdapterIdentity, {"api_version": transport.api_version}, "adapter identity"
        )
        api_version = identity.api_version
        external = _safe_external(CollectedResult, result, "provider result")
        bars = tuple(external.historical_bars)
    except BaseException:  # noqa: BLE001 -- property hooks may retain rejected data
        external_failed = True
        external = None
        bars = ()
        api_version = ""
    if external_failed:
        raise ProbeError("sanitized IBKR probe failure")
    raw_view = {
        "server_version": external.server_version,
        "server_current_time": external.server_current_time,
        "contract": external.resolved_contract.model_dump(mode="json"),
        "mode_code": external.mode_code,
        "tick_count": external.tick_count,
        "bars": [x.model_dump(mode="json") for x in bars],
        "errors": [x.model_dump(mode="json") for x in external.errors],
    }
    raw_digest = typed_hash(raw_view)
    material_digest = typed_hash([x.model_dump(mode="json") for x in bars])
    provenance_digest = typed_hash(
        {
            "request_hash": request.request_hash,
            "raw_digest": raw_digest,
            "material_digest": material_digest,
            "lineage_digest": request.instrument.lineage_digest,
        }
    )
    tick_count = external.tick_count
    tick_status = TickStatus.PRESENT if tick_count else TickStatus.ABSENT_TIMEOUT
    values = {
        "source_kind": source_kind,
        "request": request,
        "tws_server_version": external.server_version,
        "api_version": api_version,
        "server_current_time": external.server_current_time,
        "resolved_contract": external.resolved_contract,
        "requested_at": started,
        "retrieved_at": external.retrieved_at,
        "observed_at": observed,
        "confirmed_market_data_mode": external.market_mode,
        "official_market_data_type_code": external.mode_code,
        "mode_confirmed_by_callback": external.mode_code is not None,
        "tick_status": tick_status,
        "tick_count": tick_count,
        "tick_timeout_seconds": request.config.stream_seconds if not tick_count else None,
        "historical_bars": bars,
        "transport_status": "SUCCESS" if tick_count else "PARTIAL",
        "stream_transport_status": "SUCCESS" if tick_count else "TIMEOUT_NO_DATA",
        "historical_transport_status": "SUCCESS",
        "sanitized_errors": external.errors,
        "raw_digest": raw_digest,
        "material_digest": material_digest,
        "provenance_digest": provenance_digest,
        "gate_states": tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate),
    }
    return _seal(ProbeEvidence, "evidence_hash", **values)


class IBKRLocalTransport:
    def __init__(self) -> None:
        try:
            import ibapi  # type: ignore[import-not-found]
        except ImportError:
            raise ProbeError("optional ibkr-probe dependency is not installed") from None
        self.api_version = getattr(ibapi, "__version__", "9.81.1.post1")

    def collect(self, config: ProbeConfig, instrument: GovernedInstrument) -> dict[str, Any]:
        from ibapi.client import EClient  # type: ignore[import-not-found]
        from ibapi.contract import Contract  # type: ignore[import-not-found]
        from ibapi.wrapper import EWrapper  # type: ignore[import-not-found]

        state: dict[str, Any] = {
            "ready": threading.Event(),
            "contract_done": threading.Event(),
            "mode": threading.Event(),
            "history_done": threading.Event(),
            "server_time": None,
            "contract": None,
            "mode_code": None,
            "ticks": 0,
            "bars": [],
            "errors": [],
            "delayed_fallback": False,
        }

        class App(EWrapper, EClient):
            def __init__(self):
                EClient.__init__(self, self)

            def nextValidId(self, orderId):
                state["ready"].set()

            def managedAccounts(self, accountsList):
                return  # automatic callback is deliberately discarded

            def currentTime(self, value):
                state["server_time"] = dt.datetime.fromtimestamp(value, dt.UTC)

            def contractDetails(self, reqId, details):
                c = details.contract
                state["contract"] = {
                    "conid": c.conId,
                    "symbol": c.symbol,
                    "security_type": c.secType,
                    "exchange": c.exchange,
                    "primary_exchange": c.primaryExchange,
                    "currency": c.currency,
                    "local_symbol": c.localSymbol,
                }

            def contractDetailsEnd(self, reqId):
                state["contract_done"].set()

            def marketDataType(self, reqId, marketDataType):
                state["mode_code"] = marketDataType
                state["mode"].set()

            def tickPrice(self, reqId, tickType, price, attrib):
                if price is not None and price >= 0:
                    state["ticks"] += 1

            def tickSize(self, reqId, tickType, size):
                if size is not None:
                    state["ticks"] += 1

            def historicalData(self, reqId, bar):
                event = _ibkr_bar_time(bar.date)
                state["bars"].append(
                    {
                        "event_at": event,
                        "open": str(bar.open),
                        "high": str(bar.high),
                        "low": str(bar.low),
                        "close": str(bar.close),
                        "volume": str(bar.volume),
                    }
                )

            def historicalDataEnd(self, reqId, start, end):
                state["history_done"].set()

            def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
                if errorCode >= 1000 or errorCode in ERROR_CLASS:
                    state["errors"].append(
                        {
                            "request_id": reqId,
                            "code": errorCode,
                            "category": ERROR_CLASS.get(errorCode, "PROVIDER_OTHER"),
                        }
                    )

        app = App()
        app.connect(config.host, config.port, clientId=config.client_id)
        runner = threading.Thread(target=app.run, daemon=True)
        runner.start()
        try:
            if not state["ready"].wait(8):
                raise ProbeError("IBKR handshake timeout")
            app.reqCurrentTime()
            contract = Contract()
            contract.conId = instrument.conid
            contract.symbol = instrument.symbol
            contract.secType = instrument.security_type
            contract.exchange = instrument.exchange
            contract.primaryExchange = instrument.primary_exchange
            contract.currency = instrument.currency
            app.reqContractDetails(7101, contract)
            if not state["contract_done"].wait(8) or state["contract"] is None:
                raise ProbeError("IBKR contract resolution timeout")
            ResolvedContract.model_validate(state["contract"])
            app.reqMarketDataType(1)
            app.reqMktData(7102, contract, "", False, False, [])
            deadline = time.monotonic() + config.stream_seconds
            realtime_confirmation_deadline = min(deadline, time.monotonic() + 3)
            while time.monotonic() < realtime_confirmation_deadline and not state["mode"].is_set():
                time.sleep(0.05)
            if not state["mode"].is_set():
                app.cancelMktData(7102)
                state["delayed_fallback"] = True
                app.reqMarketDataType(3)
                app.reqMktData(7104, contract, "", False, False, [])
            while time.monotonic() < deadline:
                time.sleep(0.05)
            app.cancelMktData(7102)
            if state["delayed_fallback"]:
                app.cancelMktData(7104)
            app.reqHistoricalData(7103, contract, "", "2 D", "1 day", "TRADES", 1, 2, False, [])
            if not state["history_done"].wait(12):
                raise ProbeError("IBKR historical observation timeout")
            mode = {1: "REALTIME", 2: "FROZEN", 3: "DELAYED", 4: "DELAYED_FROZEN"}.get(
                state["mode_code"], "UNKNOWN"
            )
            return {
                "server_version": app.serverVersion(),
                "server_current_time": state["server_time"],
                "resolved_contract": state["contract"],
                "mode_code": state["mode_code"],
                "market_mode": mode,
                "tick_count": state["ticks"],
                "historical_bars": state["bars"][-1:],
                "errors": state["errors"],
                "retrieved_at": dt.datetime.now(dt.UTC),
            }
        finally:
            app.disconnect()
            runner.join(timeout=2)


def execute_local_observation_probe(request: Any) -> ProbeEvidence:
    """Observe localhost IBKR without claiming cryptographically authenticated provenance.

    Python process integrity is not a trust root: replacement of this function, the transport,
    callbacks, or classes can fabricate an observation.  Until an independently provisioned
    external attester exists, even this concrete path is deliberately classified as unauthenticated.
    """
    return _capture_probe(
        request,
        IBKRLocalTransport(),
        SourceKind.LOCAL_IBKR_OBSERVATION_UNAUTHENTICATED,
    )


def _make_contract_capture(capture: Any):
    def contract_capture(request: Any, transport: ProbeTransport) -> ProbeEvidence:
        """Caller transports are useful for contract tests but can never assert REAL provenance."""
        return capture(request, transport, SourceKind.CONTRACT_TEST_ONLY)

    return contract_capture


capture_probe = _make_contract_capture(_capture_probe)


def validate_evidence(value: Any) -> ProbeEvidence:
    return _revalidate(ProbeEvidence, value, "probe evidence")


def persist_evidence(evidence: Any, output: Path) -> None:
    value = validate_evidence(evidence)
    if output.exists():
        raise ProbeError("output already exists; evidence is append-only")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-local-observation", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--client-id", type=int, default=71)
    args = parser.parse_args()
    evidence = execute_local_observation_probe(
        build_request(adapter_version="9.81.1.post1", client_id=args.client_id)
    )
    persist_evidence(evidence, args.output)
    print(
        json.dumps(
            {
                "evidence_hash": evidence.evidence_hash,
                "state": evidence.evidence_state,
                "mode": evidence.confirmed_market_data_mode,
                "tick_status": evidence.tick_status,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
