from __future__ import annotations

import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from data.fx import FXLineageEntry, FXStalenessPolicy, govern_fx
from fundamentals.governance import AccountingLineageEntry, govern_accounting
from governance.canonical import typed_hash
from governance.phase7d import (
    DEFAULT_SUFFICIENCY_MATRIX,
    CanonicalUpstreamEvidence,
    ConfidenceComponent,
    FactorInputAdapterProof,
    FXUseProof,
    GovernedConfidenceProof,
    MetricSufficiencyMatrix,
    ProviderEvidenceContext,
    ProviderReadinessProof,
    QVMAdmissionV3,
    ReadinessStateProof,
    UpstreamEvidenceProof,
    UpstreamProofContext,
    adapt_accounting_factor_inputs,
    admit_qvm_v3,
    assess_provider_readiness,
    canonical_confidence_evidence,
    governed_fx_conversion,
    readiness_policy_hash,
    reference_upstream_evidence,
    seal_confidence,
    sufficiency_policy_hash,
    verify_fx_use_proof,
    verify_governed_confidence,
    verify_provider_readiness,
    verify_qvm_admission_v3,
)

AS_OF = datetime.datetime(2025, 4, 1, 20, tzinfo=datetime.UTC)


def _accounting(rows: list[dict[str, object]] | None = None):
    rows = rows or [{"entity": "PERM-1", "metric": "net_income", "value": 100.0}]
    frame = pd.DataFrame(
        [
            {
                "fact_id": f"f{i}",
                "fiscal_period": "FY-2024",
                "period_end": "2024-12-31",
                "filing_date": "2025-02-01T12:00:00Z",
                "available_at": "2025-02-01T12:00:00Z",
                "unit": "USD",
                "source": "sec_edgar",
                "dataset_version": "v1",
                "revision": 0,
                "revision_type": "ORIGINAL",
                "supersedes_revision": None,
                **row,
            }
            for i, row in enumerate(rows)
        ]
    )
    return govern_accounting(
        frame,
        source="sec_edgar",
        dataset_version="v1",
        as_of=AS_OF,
        available_at=AS_OF,
        lineage=(
            AccountingLineageEntry(
                source="sec_edgar", dataset="companyfacts", dataset_version="v1"
            ),
        ),
    )


def _components(accounting, score: float | None = 1.0, economic: bool = False):
    names = ["data_confidence", "mapping_confidence", "calculation_confidence"]
    if economic or score != 1.0:
        names.append("economic_confidence")
    result = []
    for name in names:
        economic_evidence = None
        if name == "economic_confidence":
            economic_evidence = CanonicalUpstreamEvidence(
                component=name,
                evidence_type="ECONOMIC_VALIDATION",
                governed_object_type="EconomicValidation",
                governed_object_id="governed-economic-fixture-v1",
                governed_object_hash=typed_hash({"fixture": "economic-v1", "score": score}),
                accounting_canonical_id=accounting.metadata.canonical_id,
                accounting_checksum=accounting.metadata.checksum,
                as_of=AS_OF,
                score=score,
            )
        proof = reference_upstream_evidence(
            canonical_confidence_evidence(
                accounting,
                component=name,
                as_of=AS_OF,
                economic_validation=economic_evidence,
            )
        )
        result.append(
            ConfidenceComponent(
                name=name, score=proof.score, upstream_proofs=(proof,), rationale_code=name
            )
        )
    return tuple(result)


def _context(accounting):
    return UpstreamProofContext(
        evidence=tuple(
            canonical_confidence_evidence(accounting, component=name, as_of=AS_OF)
            for name in ("data_confidence", "mapping_confidence", "calculation_confidence")
        )
    )


def _confidence(accounting, score=1.0, economic=False):
    return seal_confidence(
        accounting, as_of=AS_OF, components=_components(accounting, score, economic)
    )


def _fx(market="2025-03-31T16:00:00Z", pair="EUR/USD", base="EUR", quote="USD"):
    frame = pd.DataFrame(
        [
            {
                "currency_pair": pair,
                "base_currency": base,
                "quote_currency": quote,
                "market_timestamp": market,
                "available_at": "2025-03-31T17:00:00Z",
                "rate": 1.1,
                "source_record_id": "fix-1",
                "raw_evidence_hash": "b" * 64,
            }
        ]
    )
    return govern_fx(
        frame,
        source="fixture",
        dataset_version="v1",
        as_of=AS_OF,
        available_at=AS_OF,
        lineage=(FXLineageEntry(source="fixture", dataset="fx", dataset_version="v1"),),
        staleness_policy=FXStalenessPolicy(maximum_sessions=1),
    )


def test_079_cannot_supply_caller_threshold_and_blocks():
    accounting = _accounting()
    with pytest.raises(TypeError):
        seal_confidence(
            accounting, as_of=AS_OF, components=_components(accounting, 0.79), threshold=0.0
        )  # type: ignore[call-arg]
    assert _confidence(accounting, 0.79).state == "BELOW_THRESHOLD"


def test_exact_080_boundary_passes():
    assert _confidence(_accounting(), 0.80).state == "CONTRACTUAL_CONTROL_PASS"


def test_alternate_threshold_even_resealed_rejected():
    proof = _confidence(_accounting())
    data = proof.model_dump(mode="json")
    data["threshold"] = 0.7
    data["proof_hash"] = typed_hash({k: v for k, v in data.items() if k != "proof_hash"})
    with pytest.raises(ValidationError):
        GovernedConfidenceProof.model_validate(data)


def test_fabricated_64hex_without_upstream_proof_rejected():
    with pytest.raises(ValidationError):
        ConfidenceComponent(
            name="data_confidence", score=1.0, upstream_proofs=(), rationale_code="fake"
        )


def test_evidence_component_source_swap_rejected():
    accounting = _accounting()
    p = reference_upstream_evidence(
        canonical_confidence_evidence(accounting, component="data_confidence", as_of=AS_OF)
    )
    data = p.model_dump(mode="json")
    data["component"] = "mapping_confidence"
    data["proof_hash"] = typed_hash({k: v for k, v in data.items() if k != "proof_hash"})
    with pytest.raises(ValidationError):
        UpstreamEvidenceProof.model_validate(data)


@pytest.mark.parametrize("score", [None, 0.79])
def test_supplied_economic_unknown_or_low_is_conservative(score):
    assert _confidence(_accounting(), score, economic=True).state != "CONTRACTUAL_CONTROL_PASS"


def test_altered_or_empty_sufficiency_policy_rejected_after_reseal():
    data = DEFAULT_SUFFICIENCY_MATRIX.model_dump(mode="json")
    data["requirements"] = []
    data["matrix_hash"] = typed_hash({"version": data["version"], "requirements": []})
    with pytest.raises(ValidationError):
        MetricSufficiencyMatrix.model_validate(data)


def test_phase6_primary_classification_is_exact():
    by = {x.output_metric: x.classification for x in DEFAULT_SUFFICIENCY_MATRIX.requirements}
    for metric in (
        "raw_accrual_ratio",
        "roic_stability",
        "margin_stability",
        "roic",
        "net_debt_to_ebitda",
        "ev_to_ebit",
    ):
        assert by[metric] == "REQUIRED_PRIMARY"


def test_adapter_does_not_mix_five_entities():
    names = ["cash_from_operations", "net_income", "capital_expenditures", "revenue", "market_cap"]
    rows = [{"entity": f"PERM-{i}", "metric": name, "value": 10.0} for i, name in enumerate(names)]
    accounting = _accounting(rows)
    adapter = adapt_accounting_factor_inputs(
        accounting,
        confidence=_confidence(accounting),
        upstream_context=_context(accounting),
        as_of=AS_OF,
    )
    assert not any(x.state == "PASS" for x in adapter.states)


@pytest.mark.parametrize(
    "mutation",
    [
        {"fiscal_period": "Q1-2024"},
        {"fiscal_period": "YTD-Q1-2024"},
        {"unit": "EUR"},
        {"unit": "SHARES"},
    ],
)
def test_adapter_rejects_period_semantics_currency_or_unit_mixing(mutation):
    rows = [
        {"entity": "PERM-1", "metric": "cash_from_operations", "value": 80.0},
        {"entity": "PERM-1", "metric": "net_income", "value": 100.0, **mutation},
    ]
    accounting = _accounting(rows)
    adapter = adapt_accounting_factor_inputs(
        accounting,
        confidence=_confidence(accounting),
        upstream_context=_context(accounting),
        as_of=AS_OF,
    )
    state = next(x for x in adapter.states if x.metric == "cfo_conversion")
    assert state.state != "PASS"


def test_valid_group_formula_and_exact_lineage():
    accounting = _accounting(
        [
            {"entity": "PERM-1", "metric": "cash_from_operations", "value": 80.0},
            {"entity": "PERM-1", "metric": "net_income", "value": 100.0},
        ]
    )
    state = next(
        x
        for x in adapt_accounting_factor_inputs(
            accounting,
            confidence=_confidence(accounting),
            upstream_context=_context(accounting),
            as_of=AS_OF,
        ).states
        if x.metric == "cfo_conversion"
    )
    assert state.state == "PASS" and state.value == pytest.approx(0.8)
    assert {x.metric for x in state.inputs} == {"cash_from_operations", "net_income"}


def test_applicability_not_pass_and_sector_specific():
    accounting = _accounting(
        [
            {"entity": "PERM-1", "metric": "cash_from_operations", "value": 80.0},
            {"entity": "PERM-1", "metric": "net_income", "value": 100.0},
        ]
    )
    bank = adapt_accounting_factor_inputs(
        accounting,
        confidence=_confidence(accounting),
        upstream_context=_context(accounting),
        as_of=AS_OF,
        entity_context={"PERM-1": ("Financials", "Banks")},
    )
    industrial = adapt_accounting_factor_inputs(
        accounting,
        confidence=_confidence(accounting),
        upstream_context=_context(accounting),
        as_of=AS_OF,
        entity_context={"PERM-1": ("Industrials", "Machinery")},
    )
    assert (
        next(x for x in bank.states if x.metric == "net_debt_to_ebitda").state == "NOT_APPLICABLE"
    )
    assert (
        next(x for x in industrial.states if x.metric == "net_debt_to_ebitda").state
        == "NOT_COMPUTED"
    )


def test_empty_cross_currency_fx_use_proof_rejected_even_resealed():
    accounting = _accounting()
    _, proof = governed_fx_conversion(
        _fx(),
        accounting=accounting,
        amount=10,
        source_currency="EUR",
        target_currency="USD",
        market_at=AS_OF,
        cutoff=AS_OF,
    )
    data = proof.model_dump(mode="json")
    data["conversions"] = []
    data["proof_hash"] = typed_hash({k: v for k, v in data.items() if k != "proof_hash"})
    with pytest.raises(ValidationError):
        FXUseProof.model_validate(data)


def test_wrong_inverse_stale_future_fx_rejected():
    accounting = _accounting()
    with pytest.raises(ValueError):
        governed_fx_conversion(
            _fx(),
            accounting=accounting,
            amount=1,
            source_currency="USD",
            target_currency="EUR",
            market_at=AS_OF,
            cutoff=AS_OF,
        )
    with pytest.raises(ValueError):
        governed_fx_conversion(
            _fx("2025-03-20T16:00:00Z"),
            accounting=accounting,
            amount=1,
            source_currency="EUR",
            target_currency="USD",
            market_at=AS_OF,
            cutoff=AS_OF,
        )
    with pytest.raises(ValueError):
        _fx("2025-04-02T16:00:00Z")


def test_same_currency_identity_has_no_fabricated_provider():
    conversion, proof = governed_fx_conversion(
        None,
        accounting=_accounting(),
        amount=10,
        source_currency="USD",
        target_currency="USD",
        market_at=AS_OF,
        cutoff=AS_OF,
    )
    assert conversion.conversion_method == "identity" and proof.fx_canonical_id is None
    assert proof.conversions[0].source is None


def test_api_has_no_naked_bypass_flags_or_state_map():
    with pytest.raises(TypeError):
        admit_qvm_v3(
            accounting=_accounting(),
            confidence=None,
            adapter=None,
            fx_dataset=None,
            fx_proof=None,
            batches=(),
            required_metric_states={},
            cross_currency_value=False,
            providers_real_data_ready=True,
        )  # type: ignore[call-arg]


def test_provider_proof_cannot_be_local_arbitrary_hash():
    with pytest.raises(ValidationError):
        ProviderReadinessProof(
            provider="fake",
            dataset_identity="x",
            legal_access=True,
            historical_pit=True,
            operations_monitored=True,
            as_of=AS_OF,
            proof_hash="0" * 64,
        )


def test_readiness_direct_jump_resealed_rejected():
    data = {
        "policy_version": "phase7d-readiness-v3",
        "policy_hash": readiness_policy_hash(),
        "transitions": [
            {
                "from_state": "ACCOUNTING_BOUND",
                "to_state": "QVM_ADMISSIBLE",
                "prerequisite_type": "PrePhase6Admission",
                "prerequisite_hash": "a" * 64,
            }
        ],
        "state": "QVM_ADMISSIBLE",
    }
    data["proof_hash"] = typed_hash(data)
    with pytest.raises(ValidationError):
        ReadinessStateProof.model_validate(data)


def test_locally_resealed_admission_cannot_validate_arbitrary_hashes():
    result = admit_qvm_v3(
        accounting=_accounting(),
        confidence=None,
        adapter=None,
        fx_dataset=None,
        fx_proof=None,
        batches=(),
    )
    data = result.model_dump(mode="json")
    data["state"] = "QVM_ADMISSIBLE"
    data["reasons"] = []
    data["admission_hash"] = typed_hash({k: v for k, v in data.items() if k != "admission_hash"})
    with pytest.raises(ValidationError):
        QVMAdmissionV3.model_validate(data)


def test_real_route_remains_not_ready_and_safe():
    result = admit_qvm_v3(
        accounting=_accounting(),
        confidence=None,
        adapter=None,
        fx_dataset=None,
        fx_proof=None,
        batches=(),
    )
    assert result.state == "QVM_NOT_READY" and result.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert result.trade_decision == "NO_TRADE" and not result.live_execution_enabled
    assert not result.signals_generated and "PROVIDER_REAL_DATA_OPEN" in result.reasons


def test_stale_adapter_hash_is_rejected():
    accounting = _accounting()
    adapter = adapt_accounting_factor_inputs(
        accounting,
        confidence=_confidence(accounting),
        upstream_context=_context(accounting),
        as_of=AS_OF,
    )
    data = adapter.model_dump(mode="json")
    data["sufficiency_matrix_hash"] = "0" * 64
    with pytest.raises(ValidationError):
        FactorInputAdapterProof.model_validate(data)


def test_sufficiency_hash_is_stable_and_canonical():
    assert DEFAULT_SUFFICIENCY_MATRIX.matrix_hash == sufficiency_policy_hash()


def test_fabricated_confidence_coherently_resealed_is_not_authentic():
    accounting = _accounting()
    proof = _confidence(accounting)
    fake = (
        proof.components[0]
        .upstream_proofs[0]
        .model_copy(update={"governed_object_id": "attacker", "governed_object_hash": "f" * 64})
    )
    fake = fake.model_copy(
        update={"proof_hash": typed_hash(fake.model_dump(mode="json", exclude={"proof_hash"}))}
    )
    component = proof.components[0].model_copy(update={"upstream_proofs": (fake,)})
    resealed = seal_confidence(
        accounting, as_of=AS_OF, components=(component, *proof.components[1:])
    )
    with pytest.raises(ValueError, match="not resolvable"):
        verify_governed_confidence(
            resealed, accounting=accounting, upstream_context=_context(accounting)
        )


def test_resealed_fake_fx_lineage_rejected_by_context_replay():
    accounting = _accounting()
    fx = _fx()
    _, proof = governed_fx_conversion(
        fx,
        accounting=accounting,
        amount=10,
        source_currency="EUR",
        target_currency="USD",
        market_at=AS_OF,
        cutoff=AS_OF,
    )
    entry = proof.conversions[0].model_copy(
        update={
            "source": "ATTACKER",
            "source_record_id": "fake",
            "raw_evidence_hash": "f" * 64,
            "fx_canonical_id": "fake",
            "fx_checksum": "e" * 64,
        }
    )
    values = proof.model_dump(mode="python", exclude={"proof_hash", "conversions"})
    values["conversions"] = (entry,)
    payload = proof.model_dump(mode="json", exclude={"proof_hash", "conversions"})
    payload["conversions"] = [entry.model_dump(mode="json")]
    resealed = FXUseProof(**values, proof_hash=typed_hash(payload))
    with pytest.raises(ValueError):
        verify_fx_use_proof(resealed, fx_dataset=fx, accounting=accounting, adapter_proof_hash=None)


def test_invented_provider_stays_open_external():
    proof = assess_provider_readiness(provider="INVENTED", dataset_identity="fake", as_of=AS_OF)
    assert proof.state == "OPEN_EXTERNAL"
    with pytest.raises(ValueError, match="OPEN_EXTERNAL"):
        verify_provider_readiness(proof, ProviderEvidenceContext(evidence=()))


def test_resealed_not_ready_parses_but_governed_verifier_rejects():
    accounting = _accounting()
    result = admit_qvm_v3(
        accounting=accounting,
        confidence=None,
        adapter=None,
        fx_dataset=None,
        fx_proof=None,
        batches=(),
    )
    data = result.model_dump(mode="json")
    data["accounting_canonical_id"] = "accounting:attacker"
    data["accounting_checksum"] = "f" * 64
    data["admission_hash"] = typed_hash({k: v for k, v in data.items() if k != "admission_hash"})
    parsed = QVMAdmissionV3.model_validate(data)
    with pytest.raises(ValueError, match="not derivable"):
        verify_qvm_admission_v3(
            parsed,
            accounting=accounting,
            confidence=None,
            adapter=None,
            fx_dataset=None,
            fx_proof=None,
            batches=(),
        )


def test_genuine_not_ready_verifies_against_context():
    accounting = _accounting()
    result = admit_qvm_v3(
        accounting=accounting,
        confidence=None,
        adapter=None,
        fx_dataset=None,
        fx_proof=None,
        batches=(),
    )
    assert (
        verify_qvm_admission_v3(
            result,
            accounting=accounting,
            confidence=None,
            adapter=None,
            fx_dataset=None,
            fx_proof=None,
            batches=(),
        )
        == result
    )
