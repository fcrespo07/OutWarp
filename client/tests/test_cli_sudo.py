from __future__ import annotations

import sys

from outwarp import cli


def test_reexec_does_nothing_without_a_terminal(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(cli.os, "execv", lambda *a: called.append(a))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    cli._reexec_with_sudo()
    assert called == []


def test_reexec_runs_the_same_command_through_sudo(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(cli.os, "execv", lambda *a: called.append(a))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    found = {"sudo": "/usr/bin/sudo", "outwarp": "/usr/local/bin/outwarp"}
    monkeypatch.setattr("shutil.which", found.get)
    monkeypatch.setattr(sys, "argv", ["outwarp", "update"])
    cli._reexec_with_sudo()
    assert called == [("/usr/bin/sudo", ["/usr/bin/sudo", "/usr/local/bin/outwarp", "update"])]


def test_package_managed_only_for_usr_prefix(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "prefix", "/usr")
    assert cli._package_managed()
    monkeypatch.setattr(sys, "prefix", "/opt/pipx/venvs/outwarp-client")
    assert not cli._package_managed()
