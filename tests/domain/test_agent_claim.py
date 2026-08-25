import pytest
from pydantic import ValidationError

from aigis.domain import AgentClaim


def test_valid_claim() -> None:
    claim = AgentClaim(iteration=1, message="I fixed the failing test.")
    assert claim.iteration == 1
    assert claim.claimed_at is not None


def test_message_cannot_be_blank() -> None:
    with pytest.raises(ValidationError):
        AgentClaim(iteration=1, message="")


def test_iteration_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AgentClaim(iteration=0, message="done")


def test_claim_is_frozen() -> None:
    claim = AgentClaim(iteration=1, message="done")
    with pytest.raises(ValidationError):
        claim.message = "changed my mind"
