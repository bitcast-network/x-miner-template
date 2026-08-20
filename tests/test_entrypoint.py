"""Container entrypoint tests for the stateless reference product."""

import os
import subprocess
import sys
from pathlib import Path


def test_entrypoint_forwards_arguments_without_wallet_bootstrap(tmp_path: Path) -> None:
    executable = tmp_path / "x-miner-template"
    executable.write_text("#!/bin/sh\nprintf 'started:%s' \"$*\"\n")
    executable.chmod(0o755)
    environment = {
        "PATH": f"{tmp_path}:{Path(sys.executable).parent}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["/bin/sh", "./entrypoint.sh", "--probe"],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "started:--probe"
