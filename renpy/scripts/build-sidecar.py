"""Build the local FastAPI server as a platform-native PyInstaller sidecar.

Run from the renpy directory after installing the local packages and PyInstaller:
    pip install ../kernel ../local_server pyinstaller
    python scripts/build-sidecar.py

Use --output-dir to place the executable somewhere other than game/server.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


RENPY_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = RENPY_DIR.parent
DEFAULT_OUTPUT_DIR = RENPY_DIR / "game" / "server"
BUILD_DIR = RENPY_DIR / ".sidecar-build"
ENTRYPOINT = RENPY_DIR / ".sidecar-entry.py"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory in which to write the native server executable",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.iterdir():
        if path.name != ".gitkeep":
            shutil.rmtree(path) if path.is_dir() else path.unlink()

    ENTRYPOINT.write_text(
        "from amnesia_agent_local_server.__main__ import main\nmain()\n",
        encoding="utf-8",
    )
    separator = ";" if os.name == "nt" else ":"
    data_source = REPO_DIR / "local_server" / "amnesia_agent_local_server" / "data"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "amnesia-agent-local-server",
        "--distpath",
        str(output_dir),
        "--workpath",
        str(BUILD_DIR / "work"),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(REPO_DIR / "kernel"),
        "--paths",
        str(REPO_DIR / "local_server"),
    ]
    if data_source.is_dir():
        command.extend(
            [
                "--add-data",
                f"{data_source}{separator}amnesia_agent_local_server/data",
            ]
        )
    command.extend(
        [
            "--collect-data",
            "litellm",
            "--collect-data",
            "tiktoken",
            "--collect-submodules",
            "tiktoken_ext",
            str(ENTRYPOINT),
        ]
    )
    try:
        subprocess.run(command, cwd=RENPY_DIR, check=True)
    finally:
        ENTRYPOINT.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
