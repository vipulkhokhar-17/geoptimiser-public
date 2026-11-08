import pytest

from geoptimiser.app.__main__ import main


@pytest.mark.parametrize(
    "override",
    [
        ["--host", "0.0.0.0"],
        ["--allow-remote"],
        ["--allowed-host", "api.example.com"],
    ],
)
def test_serve_has_no_remote_bind_override(tmp_path, override):
    with pytest.raises(SystemExit):
        main(["--data-dir", str(tmp_path / "d"), "serve", *override])
    assert not (tmp_path / "d").exists()


def test_list_on_an_empty_store(tmp_path, capsys):
    assert main(["--data-dir", str(tmp_path / "d"), "list"]) == 0
    assert capsys.readouterr().out == ""


def test_audit_requires_the_attestation(tmp_path):
    with pytest.raises(SystemExit):
        main(["--data-dir", str(tmp_path / "d"), "audit", "https://example.com"])


def test_audit_rejects_unsafe_targets_with_a_clear_error(tmp_path, capsys):
    code = main(
        [
            "--data-dir",
            str(tmp_path / "d"),
            "audit",
            "http://127.0.0.1/",
            "--confirm-authorized",
        ]
    )
    assert code == 2 and "invalid_target" in capsys.readouterr().err


def test_compare_unknown_ids(tmp_path, capsys):
    code = main(
        [
            "--data-dir",
            str(tmp_path / "d"),
            "compare",
            "aud_" + "0" * 20,
            "aud_" + "1" * 20,
        ]
    )
    assert code == 2 and "audit_not_found" in capsys.readouterr().err


def test_serve_rejects_invalid_cors_origins_before_starting(tmp_path, capsys):
    for bad in (
        "*",
        "http://geoptimiser.me",
        "https://geoptimiser.me",
        "https://geoptimiser.me/x",
    ):
        assert (
            main(["--data-dir", str(tmp_path / "d"), "serve", "--cors-origin", bad])
            == 2
        )
        assert "origin" in capsys.readouterr().err


def test_serve_passes_the_agent_rate_limit_and_validates_it(
    tmp_path, monkeypatch, capsys
):
    import geoptimiser.app.__main__ as cli

    seen: dict = {}

    def fake_service(args, **extra):
        seen.update(extra)
        raise ValueError("stop before serving")

    monkeypatch.setattr(cli, "_service", fake_service)
    base = ["--data-dir", str(tmp_path / "d"), "serve"]
    assert main([*base, "--max-agent-audits-per-hour", "3"]) == 2
    assert seen["max_agent_audits_per_hour"] == 3
    monkeypatch.undo()
    assert main([*base, "--max-agent-audits-per-hour", "-1"]) == 2
    assert "max_agent_audits_per_hour" in capsys.readouterr().err
