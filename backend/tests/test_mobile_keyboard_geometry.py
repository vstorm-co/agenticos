"""Run the native geometry itself; device keyboard animation still needs iOS QA."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="Swift toolchain is unavailable",
)
def test_native_keyboard_resizes_only_for_docked_occlusion(tmp_path: Path) -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "mobile/src-tauri/ios/Sources/AgenticOSNative/KeyboardGeometry.swift"
    )
    main = tmp_path / "main.swift"
    main.write_text("""import Foundation
import CoreGraphics
let base = CGRect(x: 20, y: 30, width: 350, height: 740)
assert(keyboardAdjustedFrame(base: base, keyboard: .null) == base)
assert(keyboardAdjustedFrame(base: base, keyboard: CGRect(x: 0, y: 500, width: 400, height: 300)).height == 470)
assert(keyboardAdjustedFrame(base: base, keyboard: CGRect(x: 0, y: 800, width: 400, height: 300)) == base)
assert(keyboardAdjustedFrame(base: base, keyboard: CGRect(x: 50, y: 400, width: 200, height: 150)) == base)
assert(keyboardAdjustedFrame(base: base, keyboard: CGRect(x: 500, y: 500, width: 400, height: 300)) == base)
assert(keyboardAdjustedFrame(base: base, keyboard: CGRect(x: 0, y: 0, width: 400, height: 800)).height == 0)
let rotated = CGRect(x: 0, y: 0, width: 800, height: 350)
assert(keyboardAdjustedFrame(base: rotated, keyboard: CGRect(x: 0, y: 200, width: 800, height: 150)).height == 200)
""")
    compiler = shutil.which("swiftc")
    assert compiler is not None
    binary = tmp_path / "keyboard-geometry"
    compiled = subprocess.run(
        [compiler, str(source), str(main), "-o", str(binary)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    subprocess.run([str(binary)], check=True, timeout=10)
