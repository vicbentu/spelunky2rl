import pytest

from spelunky2rl import cli
from spelunky2rl.version import __version__


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_doctor_reports_a_bad_game_dir(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_check_docker", lambda image: True)
    assert cli.main(["doctor", "--game-dir", str(tmp_path)]) == 1
    assert "no Spel2.exe" in capsys.readouterr().out


def test_doctor_accepts_a_game_dir(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_check_docker", lambda image: True)
    (tmp_path / "Spel2.exe").write_bytes(b"MZ")
    assert cli.main(["doctor", "--game-dir", str(tmp_path)]) == 0
    assert "build " in capsys.readouterr().out
