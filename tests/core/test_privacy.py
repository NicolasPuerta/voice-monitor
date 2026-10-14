"""Pruebas para garantizar que los secretos no salen del proceso."""

from app.core.privacy import PrivacySanitizer


def test_privacy_sanitizer_removes_home() -> None:
    sanitizer = PrivacySanitizer(home_dir="/home/testuser")

    text = "Running from /home/testuser/projects/secret"
    sanitized = sanitizer.sanitize_text(text)
    assert sanitized == "Running from ~/projects/secret"


def test_privacy_sanitizer_removes_url_credentials() -> None:
    sanitizer = PrivacySanitizer()

    text = "Error connecting to https://admin:superSecret123@api.com/v1"
    sanitized = sanitizer.sanitize_text(text)
    assert sanitized == "Error connecting to https://***:***@api.com/v1"
    assert "admin" not in sanitized
    assert "superSecret123" not in sanitized


def test_privacy_sanitizer_removes_bearer_tokens() -> None:
    sanitizer = PrivacySanitizer()

    text = "Authorization: Bearer x0x0_some_huge_token_abc123"
    sanitized = sanitizer.sanitize_text(text)
    assert sanitized == "Authorization: Bearer ***"


def test_privacy_sanitizer_removes_jwt() -> None:
    sanitizer = PrivacySanitizer()
    text = (
        "Token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkw."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c failed."
    )
    sanitized = sanitizer.sanitize_text(text)
    assert sanitized == "Token ***JWT*** failed."


def test_privacy_sanitizer_removes_aws_keys() -> None:
    sanitizer = PrivacySanitizer()
    text = "Found AKIAIOSFODNN7EXAMPLE in config."
    sanitized = sanitizer.sanitize_text(text)
    assert sanitized == "Found ***AWS_KEY*** in config."
