"""JWT Authentication Module for Multi-tenant API.

Parses and validates Authorization header ("Bearer <token>").
Supports HS256 (local testing key) and RS256/JWKS (production Clerk/Supabase).
"""

from __future__ import annotations

import logging
import os
import jwt
from typing import Optional

log = logging.getLogger(__name__)

# Secret used for local development and test suite
DEFAULT_TEST_SECRET = "twin-local-test-secret-key-32-chars-long"


def authenticate_token(
    authorization: Optional[str],
    secret_or_key: Optional[str] = None,
    algorithms: list[str] | None = None,
) -> Optional[str]:
    """Parse and verify JWT token from Authorization header.

    Returns the `sub` claim (user_id) if valid.
    Returns None on any failure (expired, tampered, missing header, bad token).
    Never raises an exception (prevents 500 error leak).
    """
    if not authorization:
        return None

    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    token = parts[1]
    secret = secret_or_key or os.environ.get("TWIN_JWT_SECRET") or DEFAULT_TEST_SECRET
    algos = algorithms or ["HS256", "RS256"]

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=algos,
            options={"verify_exp": True, "verify_signature": True},
        )
        user_id = payload.get("sub")
        if not user_id or not isinstance(user_id, str):
            return None
        return user_id
    except (jwt.PyJWTError, Exception) as exc:
        log.debug("JWT authentication failed: %s", exc)
        return None
