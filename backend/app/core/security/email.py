"""Email validation and normalization shared across registration, login, and CLI.

Implements Revision 3 §6.2:
- Validates syntax via email-validator with `check_deliverability=False` (no DNS).
- Strips leading/trailing whitespace, normalizes IDN domains, and lowercases
  the entire address.
- Enforces RFC 5321 maximum length (254 characters).
- Does NOT apply provider-specific rules (Gmail dots or +tags are preserved).
"""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

MAX_EMAIL_LENGTH = 254


class InvalidEmailError(ValueError):
    """Raised when an email address fails syntax or length validation."""


def normalize_email(raw_email: str) -> str:
    """Validate and normalize an email address to canonical lowercase form."""
    if not isinstance(raw_email, str):
        raise InvalidEmailError("Email address must be a string.")

    stripped = raw_email.strip()
    if not stripped:
        raise InvalidEmailError("Email address cannot be empty.")

    try:
        validated = validate_email(stripped, check_deliverability=False)
    except EmailNotValidError as error:
        raise InvalidEmailError("Invalid email address.") from error

    normalized = validated.normalized.lower()
    if len(normalized) > MAX_EMAIL_LENGTH:
        raise InvalidEmailError(
            f"Email address must be at most {MAX_EMAIL_LENGTH} characters."
        )

    return normalized
