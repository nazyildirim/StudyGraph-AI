"""Unit tests for PyJWT HS256 access tokens and strict claim/sub validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest

from app.core.security.tokens import (
    MAX_PG_INT32,
    MAX_TOKEN_BYTES,
    JwtTokenService,
    TokenError,
    extract_bearer_token,
)

TEST_SECRET = "S" * 48
OTHER_SECRET = "X" * 48


class _MutableClock:
    def __init__(self, initial: datetime) -> None:
        self.current = initial

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def _base_claims(now_ts: int, **overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "sub": "42",
        "type": "access",
        "iss": "studygraph-ai",
        "aud": "studygraph-ai-api",
        "iat": now_ts,
        "nbf": now_ts,
        "exp": now_ts + 1800,
        "jti": str(uuid4()),
    }
    claims.update(overrides)
    return claims


def test_create_and_decode_access_token_without_role_claim() -> None:
    clock = _MutableClock(datetime.now(timezone.utc))
    service = JwtTokenService(secret_key=TEST_SECRET, clock=clock)

    token, expires_in = service.create_access_token(42)
    assert expires_in == 1800

    raw_claims = jwt.decode(
        token,
        TEST_SECRET,
        algorithms=["HS256"],
        audience="studygraph-ai-api",
        issuer="studygraph-ai",
    )
    assert "role" not in raw_claims
    assert raw_claims["type"] == "access"
    assert raw_claims["sub"] == "42"
    UUID(raw_claims["jti"])

    parsed = service.decode_access_token(token)
    assert parsed.user_id == 42
    assert parsed.jti == raw_claims["jti"]


def test_extract_bearer_token_parsing() -> None:
    assert extract_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    assert extract_bearer_token("bearer abc.def.ghi") == "abc.def.ghi"

    for bad in (None, "", "Basic abc", "Bearer", "Bearer a b", "abc.def.ghi"):
        with pytest.raises(TokenError):
            extract_bearer_token(bad)


@pytest.mark.parametrize(
    "bad_sub",
    [
        None,
        1,
        "0",
        "-1",
        "01",
        " 1",
        "1 ",
        "1.0",
        "1e3",
        "abc",
        str(MAX_PG_INT32 + 1),
        "1" * 50,
    ],
)
def test_invalid_sub_values_are_rejected(bad_sub: object) -> None:
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    service = JwtTokenService(secret_key=TEST_SECRET, clock=lambda: now)

    claims = _base_claims(now_ts)
    if bad_sub is None:
        del claims["sub"]
    else:
        claims["sub"] = bad_sub

    token = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
    with pytest.raises(TokenError):
        service.decode_access_token(token)


def test_max_valid_pg_int32_sub_is_accepted() -> None:
    now = datetime.now(timezone.utc)
    service = JwtTokenService(secret_key=TEST_SECRET, clock=lambda: now)
    token, _ = service.create_access_token(MAX_PG_INT32)
    assert service.decode_access_token(token).user_id == MAX_PG_INT32


def test_rejects_alg_none_wrong_signature_aud_iss_and_type() -> None:
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    service = JwtTokenService(secret_key=TEST_SECRET, clock=lambda: now)

    # alg=none
    none_token = jwt.encode(_base_claims(now_ts), "", algorithm="none")
    with pytest.raises(TokenError):
        service.decode_access_token(none_token)

    # wrong signature
    wrong_sig = jwt.encode(_base_claims(now_ts), OTHER_SECRET, algorithm="HS256")
    with pytest.raises(TokenError):
        service.decode_access_token(wrong_sig)

    # wrong audience
    wrong_aud = jwt.encode(
        _base_claims(now_ts, aud="other-api"), TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        service.decode_access_token(wrong_aud)

    # wrong issuer
    wrong_iss = jwt.encode(
        _base_claims(now_ts, iss="other-issuer"), TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        service.decode_access_token(wrong_iss)

    # wrong type
    wrong_type = jwt.encode(
        _base_claims(now_ts, type="refresh"), TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        service.decode_access_token(wrong_type)


def test_rejects_expired_future_iat_future_nbf_and_excessive_lifetime() -> None:
    clock = _MutableClock(datetime.now(timezone.utc))
    service = JwtTokenService(secret_key=TEST_SECRET, clock=clock)

    token, _ = service.create_access_token(7)
    clock.advance(1801)
    with pytest.raises(TokenError):
        service.decode_access_token(token)

    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    strict_service = JwtTokenService(secret_key=TEST_SECRET, clock=lambda: now)

    future_nbf = jwt.encode(
        _base_claims(now_ts, nbf=now_ts + 60), TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        strict_service.decode_access_token(future_nbf)

    future_iat = jwt.encode(
        _base_claims(now_ts, iat=now_ts + 60), TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        strict_service.decode_access_token(future_iat)

    too_long_ttl = jwt.encode(
        _base_claims(now_ts, exp=now_ts + 1801), TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        strict_service.decode_access_token(too_long_ttl)


@pytest.mark.parametrize(
    "missing_claim",
    ["sub", "exp", "iat", "nbf", "iss", "aud", "jti", "type"],
)
def test_rejects_missing_required_claim(missing_claim: str) -> None:
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    service = JwtTokenService(secret_key=TEST_SECRET, clock=lambda: now)

    claims = _base_claims(now_ts)
    del claims[missing_claim]
    token = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
    with pytest.raises(TokenError):
        service.decode_access_token(token)


def test_rejects_oversized_malformed_bool_timestamp_and_bad_jti() -> None:
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    service = JwtTokenService(secret_key=TEST_SECRET, clock=lambda: now)

    with pytest.raises(TokenError):
        service.decode_access_token("a." + "b" * MAX_TOKEN_BYTES + ".c")

    for malformed in ("", "abc", "a.b", "a.b.c.d", "a..c"):
        with pytest.raises(TokenError):
            service.decode_access_token(malformed)

    bad_jti = jwt.encode(
        _base_claims(now_ts, jti="not-a-uuid"), TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        service.decode_access_token(bad_jti)

    bool_ts = jwt.encode(
        _base_claims(now_ts, iat=True), TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        service.decode_access_token(bool_ts)


def test_service_configuration_bounds() -> None:
    with pytest.raises(ValueError):
        JwtTokenService(secret_key="short")
    with pytest.raises(ValueError):
        JwtTokenService(secret_key=TEST_SECRET, expire_minutes=4)
    with pytest.raises(ValueError):
        JwtTokenService(secret_key=TEST_SECRET, expire_minutes=61)
    with pytest.raises(ValueError):
        JwtTokenService(secret_key=TEST_SECRET, leeway_seconds=31)


def test_leeway_seconds_allows_small_clock_skew_and_rejects_beyond_leeway() -> None:
    base_now = datetime.now(timezone.utc)
    base_ts = int(base_now.timestamp())
    clock = _MutableClock(base_now)
    service = JwtTokenService(
        secret_key=TEST_SECRET,
        leeway_seconds=10,
        clock=clock,
    )

    # Slightly expired (5s past exp) -> accepted within 10s leeway.
    slightly_expired = jwt.encode(
        _base_claims(base_ts - 1805, exp=base_ts - 5),
        TEST_SECRET,
        algorithm="HS256",
    )
    assert service.decode_access_token(slightly_expired).user_id == 42

    # Beyond leeway (11s past exp) -> rejected.
    past_leeway_expired = jwt.encode(
        _base_claims(base_ts - 1811, exp=base_ts - 11),
        TEST_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        service.decode_access_token(past_leeway_expired)

    # Slightly future iat/nbf (5s ahead) -> accepted within 10s leeway.
    slightly_future = jwt.encode(
        _base_claims(base_ts + 5, nbf=base_ts + 5, exp=base_ts + 1805),
        TEST_SECRET,
        algorithm="HS256",
    )
    assert service.decode_access_token(slightly_future).user_id == 42

    # Future iat/nbf beyond leeway (11s ahead) -> rejected.
    past_leeway_future = jwt.encode(
        _base_claims(base_ts + 11, nbf=base_ts + 11, exp=base_ts + 1811),
        TEST_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        service.decode_access_token(past_leeway_future)
