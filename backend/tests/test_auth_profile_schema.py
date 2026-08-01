"""Response-contract tests for the authenticated user's profile."""

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schemas.auth import MeResponse


def test_me_response_exposes_existing_profile_timestamps():
    created_at = datetime.now(timezone.utc)
    user = SimpleNamespace(
        id=uuid4(),
        username="field-tech",
        role="technician",
        created_at=created_at,
        archived_at=None,
    )

    response = MeResponse.model_validate(user)

    assert response.created_at == created_at
    assert response.archived_at is None
