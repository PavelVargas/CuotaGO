"""Optional JS runtime regressions; application runtime does not require Node."""
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.parametrize("script", ["test_service_worker_runtime.cjs", "test_badge_lifecycle.cjs"])
def test_js_performance_runtime(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is optional, needed only for isolated SW runtime tests')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, '--test', f'tests/{script}'],
                            cwd=root, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
