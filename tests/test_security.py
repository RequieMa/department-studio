import pytest

from department_studio.security import OwnerCredential, allowed_request


def test_owner_tokens_are_random_and_compared_without_accepting_malformed_values():
    first, second = OwnerCredential(), OwnerCredential()
    assert first.token != second.token
    assert len(first.token) >= 40
    assert first.matches(first.token)
    assert not first.matches("wrong")
    assert not first.matches("星图")
    assert first.token not in repr(first)


@pytest.mark.parametrize(
    "host,origin,expected",
    [
        ("127.0.0.1:8765", None, True),
        ("127.0.0.1:8765", "http://127.0.0.1:8765", True),
        ("127.0.0.1:8765", "https://evil.example", False),
        ("127.0.0.1:8765", "null", False),
        ("127.0.0.1:8765.evil.example", None, False),
        ("localhost:8765", None, False),
        ("127.0.0.1:9000", None, False),
    ],
)
def test_exact_host_and_origin(host, origin, expected):
    assert allowed_request("http://127.0.0.1:8765", host, origin) is expected
