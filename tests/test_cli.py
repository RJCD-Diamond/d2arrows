import subprocess
import sys

from arrows import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "arrows", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
