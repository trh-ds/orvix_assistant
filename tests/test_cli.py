import pytest

from orvix import cli


def test_probe_command(capsys):
    assert cli.main(["probe"]) == 0
    assert "RAM:" in capsys.readouterr().out


def test_voice_mode_not_ready(capsys):
    assert cli.main([]) == 2


def test_text_mode_reports_missing_ollama(tmp_path, capsys):
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'[llm]\nhost = "http://127.0.0.1:9"\n[paths]\ndb = "{tmp_path}/t.db"\n')
    assert cli.main(["--text", "--config", str(cfg)]) == 1
    assert "Ollama" in capsys.readouterr().err


def test_bench_and_eval_report_missing_ollama(tmp_path, capsys):
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'[llm]\nhost = "http://127.0.0.1:9"\n[paths]\ndb = "{tmp_path}/t.db"\n')
    assert cli.main(["--config", str(cfg), "bench"]) == 1
    assert cli.main(["--config", str(cfg), "eval"]) == 1


def test_help():
    with pytest.raises(SystemExit):
        cli.main(["--help"])
