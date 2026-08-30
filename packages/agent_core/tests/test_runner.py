import asyncio
from pathlib import Path

import pytest

from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.types import PermissionMode


@pytest.mark.asyncio
async def test_local_runner_timeout_terminates_child_processes(tmp_path: Path) -> None:
    marker = tmp_path / "child-survived.txt"
    (tmp_path / "child.py").write_text(
        "import time\nfrom pathlib import Path\ntime.sleep(2)\n"
        "Path('child-survived.txt').write_text('unsafe')\n",
        encoding="utf-8",
    )
    (tmp_path / "parent.py").write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    result = await LocalRunner(tmp_path).run(
        "python parent.py",
        permission=PermissionMode.EXECUTE,
        timeout=1,
    )
    await asyncio.sleep(2)

    assert result.timed_out is True
    assert not marker.exists()
