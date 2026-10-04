import pytest

from orvix.core.config import Config
from orvix.memory.store import Store
from orvix.tools.base import Proc, ToolContext


class FakeRunner:
    def __init__(self):
        self.launched: list[list[str]] = []
        self.ran: list = []
        self.next = Proc(0, "", "")

    def launch(self, argv, cwd=None):
        self.launched.append(argv)

    def run(self, argv, timeout=30, cwd=None, shell=False):
        self.ran.append(argv)
        return self.next

    def kill_all(self):
        pass


@pytest.fixture
def ctx(tmp_path):
    cfg = Config()
    cfg.paths.home = str(tmp_path)
    cfg.paths.blocked = [str(tmp_path / ".ssh")]
    return ToolContext(cfg=cfg, store=Store(":memory:"), runner=FakeRunner())
