from orvix.tools.base import Runner


def test_real_runner_output_and_timeout():
    r = Runner()
    assert r.run("echo hi", shell=True).stdout.strip() == "hi"
    p = r.run("sleep 5", timeout=0.2, shell=True)
    assert p.timed_out and p.returncode == 124
    assert r.run(["definitely-not-a-binary"]).returncode == 127
