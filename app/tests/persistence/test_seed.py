"""Tests for the YAML seed loader.

Happy path uses the real `data/` directory so the production seed is
covered as part of the test suite. Failure-mode tests build minimal
YAML fixtures in `tmp_path` so each failure mode is exercised in
isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session

from app.persistence import repositories as repo
from app.persistence.seed import (
    SeedLoadError,
    SeedSummary,
    load_seed_data,
    seed_if_empty,
)

# --- Happy path -----------------------------------------------------------


def test_seed_if_empty_loads_real_data_directory(session: Session) -> None:
    summary = seed_if_empty(session)
    session.commit()

    assert summary == SeedSummary(
        members=3, policies=3, rules=32, claims=13, line_items=15
    )
    assert len(repo.list_members(session)) == 3
    assert len(repo.list_claims(session)) == 13


def test_seed_if_empty_is_noop_when_database_is_populated(
    session: Session,
) -> None:
    seed_if_empty(session)
    session.commit()

    again = seed_if_empty(session)
    assert again is None


# --- Failure modes --------------------------------------------------------


def _write_minimal_seed(
    target_dir: Path,
    *,
    members: list | None = None,
    policies: list | None = None,
    claims: list | None = None,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "members.yaml").write_text(
        yaml.safe_dump(members if members is not None else [])
    )
    (target_dir / "policies.yaml").write_text(
        yaml.safe_dump(policies if policies is not None else [])
    )
    (target_dir / "claims.yaml").write_text(
        yaml.safe_dump(claims if claims is not None else [])
    )


def test_missing_file_raises_seed_load_error(
    session: Session, tmp_path: Path
) -> None:
    (tmp_path / "members.yaml").write_text("- {id: M1, name: A}\n")
    with pytest.raises(SeedLoadError, match="Seed file not found"):
        load_seed_data(session, data_dir=tmp_path)


def test_malformed_yaml_raises_seed_load_error(
    session: Session, tmp_path: Path
) -> None:
    (tmp_path / "members.yaml").write_text("[ not valid yaml }")
    (tmp_path / "policies.yaml").write_text("[]")
    (tmp_path / "claims.yaml").write_text("[]")
    with pytest.raises(SeedLoadError, match="Malformed YAML"):
        load_seed_data(session, data_dir=tmp_path)


def test_unknown_rule_kind_raises_seed_load_error(
    session: Session, tmp_path: Path
) -> None:
    _write_minimal_seed(
        tmp_path,
        members=[{"id": "M1", "name": "A"}],
        policies=[
            {
                "id": "P1",
                "member_id": "M1",
                "name": "x",
                "effective_date": "2026-01-01",
                "termination_date": "2026-12-31",
                "annual_deductible": "0.00",
                "rules": [
                    {
                        "id": "R1",
                        "service_type": "x",
                        "kind": "bogus_kind",
                        "parameters": {},
                    }
                ],
            }
        ],
    )
    with pytest.raises(SeedLoadError, match="Validation failed"):
        load_seed_data(session, data_dir=tmp_path)


def test_unknown_member_id_raises_seed_load_error(
    session: Session, tmp_path: Path
) -> None:
    _write_minimal_seed(
        tmp_path,
        members=[{"id": "M1", "name": "A"}],
        policies=[
            {
                "id": "P1",
                "member_id": "M-MISSING",
                "name": "x",
                "effective_date": "2026-01-01",
                "termination_date": "2026-12-31",
                "annual_deductible": "0.00",
                "rules": [],
            }
        ],
    )
    with pytest.raises(
        SeedLoadError, match="references unknown member M-MISSING"
    ):
        load_seed_data(session, data_dir=tmp_path)


def test_duplicate_cost_sharing_rules_raise_seed_load_error(
    session: Session, tmp_path: Path
) -> None:
    _write_minimal_seed(
        tmp_path,
        members=[{"id": "M1", "name": "A"}],
        policies=[
            {
                "id": "P1",
                "member_id": "M1",
                "name": "x",
                "effective_date": "2026-01-01",
                "termination_date": "2026-12-31",
                "annual_deductible": "0.00",
                "rules": [
                    {
                        "id": "R1",
                        "service_type": "x",
                        "kind": "copay",
                        "parameters": {"amount": "25.00"},
                    },
                    {
                        "id": "R2",
                        "service_type": "x",
                        "kind": "coinsurance",
                        "parameters": {"member_pct": 20},
                    },
                ],
            }
        ],
    )
    with pytest.raises(
        SeedLoadError, match="multiple cost-sharing rules"
    ):
        load_seed_data(session, data_dir=tmp_path)


def test_duplicate_member_ids_raise_seed_load_error(
    session: Session, tmp_path: Path
) -> None:
    _write_minimal_seed(
        tmp_path,
        members=[
            {"id": "M1", "name": "A"},
            {"id": "M1", "name": "B"},
        ],
    )
    with pytest.raises(SeedLoadError, match="Duplicate member id"):
        load_seed_data(session, data_dir=tmp_path)
