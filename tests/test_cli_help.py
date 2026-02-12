from __future__ import annotations

import subprocess
import sys


def test_package_cli_help_lists_commands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "proof_please.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    output = result.stdout
    assert "extract-claims" in output
    assert "generate-queries" in output
    assert "run-pipeline" in output
