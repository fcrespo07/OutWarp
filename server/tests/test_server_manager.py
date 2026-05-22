from __future__ import annotations

import pytest

from outwarp_server.server_manager import validate_client_name


@pytest.mark.parametrize(
    "name",
    ["laptop", "ferra-portatil", "Casa_01", "movil.personal", "a", "Client 1", "x" * 64],
)
def test_validate_client_name_accepts_safe_names(name):
    assert validate_client_name(name) == name


def test_validate_client_name_strips_whitespace():
    assert validate_client_name("  laptop  ") == "laptop"


@pytest.mark.parametrize(
    "name",
    [
        "../secret",       # path traversal
        "..\\secret",      # windows traversal
        "a/b",             # path separator
        "a\\b",            # windows separator
        ".",               # current dir
        "..",              # parent dir
        "",                # empty
        "   ",             # whitespace only
        "x" * 65,          # too long
        "name\x00",        # null byte
        "tab\tname",       # control char
        "/abs",            # absolute-ish
        ".hidden",         # leading dot (separator-like start)
    ],
)
def test_validate_client_name_rejects_unsafe_names(name):
    with pytest.raises(ValueError):
        validate_client_name(name)


def test_validate_client_name_rejects_non_string():
    with pytest.raises(ValueError):
        validate_client_name(None)  # type: ignore[arg-type]
