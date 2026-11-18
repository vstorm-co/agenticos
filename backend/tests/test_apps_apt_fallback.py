"""Execute hosted runner APT selection with temporary sources and a fake network."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
PRIMARY = "https://archive.ubuntu.com/ubuntu"
FALLBACK = "https://mirrors.edge.kernel.org/ubuntu"


@pytest.mark.parametrize("workflow", ["apps.yml", "app-release.yml"])
@pytest.mark.parametrize("outcomes", [(0,), (100, 0), (100, 100)])
def test_install_requires_a_successful_signed_index_update(
    tmp_path: Path, workflow: str, outcomes: tuple[int, ...]
) -> None:
    content = (WORKFLOWS / workflow).read_text()
    step = content.split("        timeout-minutes: 8\n        run: |\n", 1)[1]
    lines: list[str] = []
    for line in step.splitlines():
        if not line.startswith("          "):
            break
        lines.append(line[10:])
    script = "\n".join(lines)
    assert script.startswith("set -euo pipefail")
    apt = tmp_path / "etc/apt"
    (apt / "sources.list.d").mkdir(parents=True)
    (apt / "sources.list.d/ubuntu.sources").write_text(
        "Types: deb\nURIs: http://azure.archive.ubuntu.com/ubuntu\n"
        "Suites: noble noble-updates noble-backports\n"
        "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\n"
        "Types: deb\nURIs: http://security.ubuntu.com/ubuntu\nSuites: noble-security\n"
        "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo = fake_bin / "sudo"
    # sed and tee execute normally; only privileged paths and network are replaced.
    sudo.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent("""\
            import json
            import os
            import subprocess
            import sys
            from pathlib import Path

            root = Path(os.environ['APT_TEST_ROOT'])
            args = [arg.replace('/etc/apt/', str(root / 'etc/apt') + '/') for arg in sys.argv[1:]]
            if args[0] == 'apt-get':
                log = root / 'calls.json'
                calls = json.loads(log.read_text()) if log.exists() else []
                calls.append({'args': args[1:],
                              'sources': (root / 'etc/apt/sources.list.d/ubuntu.sources').read_text(),
                              'mirror': (root / 'etc/apt/apt-mirrors.txt').read_text().strip()})
                log.write_text(json.dumps(calls))
                if 'update' in args:
                    attempt = sum('update' in call['args'] for call in calls) - 1
                    sys.exit(json.loads(os.environ['APT_TEST_OUTCOMES'])[attempt])
                sys.exit(0)
            if args[0] == 'sed' and sys.platform == 'darwin':
                args[1:2] = ['-E', '-i', '']
            sys.exit(subprocess.run(args, check=False).returncode)
            """)
    )
    sudo.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "APT_TEST_ROOT": str(tmp_path),
            "APT_TEST_OUTCOMES": json.dumps(outcomes),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (tmp_path / "calls.json").exists(), result.stderr
    calls = json.loads((tmp_path / "calls.json").read_text())
    succeeded = outcomes[-1] == 0
    assert (result.returncode == 0) is succeeded, result.stderr
    updates = [call for call in calls if "update" in call["args"]]
    installs = [call for call in calls if "install" in call["args"]]
    assert len(updates) == len(outcomes)
    assert len(installs) == int(succeeded)
    for call, archive in zip(updates, (PRIMARY, FALLBACK), strict=False):
        assert call["mirror"] == archive
        assert f"URIs: {archive}\n" in call["sources"]
        assert "azure.archive" not in call["sources"]
        assert "URIs: http://security.ubuntu.com/ubuntu\n" in call["sources"]
        assert call["sources"].count("Signed-By:") == 2
        assert "--error-on=any" in call["args"]
    for call in calls:
        for option in (
            "Acquire::ForceIPv4=true",
            "Acquire::Retries=2",
            "Acquire::http::Timeout=15",
            "Acquire::https::Timeout=15",
        ):
            assert option in call["args"]
        assert not any("unauthenticated" in arg or "AllowInsecure" in arg for arg in call["args"])
    if succeeded:
        assert calls[-1] is installs[0]
        assert installs[0]["mirror"] == (PRIMARY if len(outcomes) == 1 else FALLBACK)
