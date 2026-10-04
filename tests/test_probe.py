from orvix import probe


def test_collect_and_render_without_ollama():
    info = probe.collect("http://127.0.0.1:9")
    assert info["ram_gb"] > 0 and info["ollama"]["reachable"] is False
    out = probe.render(info)
    assert "RAM:" in out and "Ollama:    not reachable" in out
