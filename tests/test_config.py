from orvix.core.config import load_config


def test_loads_repo_config():
    cfg = load_config()
    assert cfg.llm.keep_alive == -1
    assert cfg.loop.max_tool_calls == 5
    assert cfg.paths.db_path.name == "orvix.db"
