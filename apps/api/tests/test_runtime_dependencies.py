"""Tests for dependencies required by production-only integration paths."""


def test_mysql_sha2_auth_dependency_is_installed() -> None:
    """MySQL 8's default caching_sha2_password flow must be usable in the API image."""
    import cryptography

    assert cryptography.__version__
