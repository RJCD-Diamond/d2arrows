import subprocess
import sys

from d2arrows import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "d2arrows", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
