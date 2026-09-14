"""Minimal command-line CLI for the amnesia agent kernel."""

import argparse
import asyncio
import importlib.metadata
import subprocess
import sys
from collections.abc import Callable
from contextlib import aclosing
from typing import TypeVar

from amnesia_agent_kernel import AgentError, ConfigError, KernelSession

from amnesia_agent_cli import display
from amnesia_agent_cli.config import ConfigStore
from amnesia_agent_cli.reporting import report_error

try:
    import readline  # noqa: F401 - enables up-arrow input history on POSIX
except ImportError:
    pass

T = TypeVar("T")


def _open_in_editor(path: str) -> None:
    """Open the given file with the platform's default opener."""
    try:
        if sys.platform == "win32":
            completed = subprocess.run(["notepad.exe", path], check=False, shell=False)
        elif sys.platform == "darwin":
            completed = subprocess.run(["open", "-t", "-W", path], check=False, shell=False)
        else:
            completed = subprocess.run(["xdg-open", path], check=False, shell=False)
    except OSError as e:
        report_error(RuntimeError(f"Cannot open {path}: {e}. Edit it manually and re-run."))
        return
    if completed.returncode != 0:
        report_error(
            RuntimeError(
                f"Cannot open {path}: editor opener exited with status "
                f"{completed.returncode}. Edit it manually and re-run."
            )
        )


def _load_or_edit(loader: Callable[[], T]) -> T:
    """Run a loader, or open its erroring file in an editor and exit."""
    try:
        return loader()
    except ConfigError as e:
        if e.path is None:
            raise
        report_error(e, context=f"configuration file {e.path}")
        print(
            f"Opening {e.path} to fix.\n"
            "Re-run amnesia-agent after saving.",
            file=sys.stderr,
        )
        _open_in_editor(e.path)
        raise SystemExit(1) from e


async def _render_turn(
    session: KernelSession, user_input: str, renderer: display.TerminalRenderer
) -> None:
    """Run one turn and render its events to the terminal."""
    async with aclosing(session.turn(user_input)) as events:
        async for event in events:
            renderer.render(event)


def _run() -> None:
    """Seed CLI and kernel state, then run the interactive loop."""
    config_store = ConfigStore()
    renderer = display.TerminalRenderer()
    while True:
        loaded = _load_or_edit(config_store.load)
        try:
            user_input: str = input("> ")
        except KeyboardInterrupt:
            print()
            return
        try:
            session = KernelSession(loaded.provider, loaded.policy)
        except AgentError as e:
            report_error(e, f"while initializing from {config_store.path}")
            raise
        try:
            asyncio.run(_render_turn(session, user_input, renderer))
        except KeyboardInterrupt:
            renderer.reset()
            print()
            return
        except AgentError as e:
            renderer.reset()
            report_error(e)
            raise
        except Exception:
            renderer.reset()
            raise


def _version() -> str:
    try:
        return importlib.metadata.version("amnesia-agent-cli")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def main() -> None:
    """Console-script entry point."""
    parser = argparse.ArgumentParser(
        prog="amnesia-agent",
        description="A minimal self-directed agent that runs bash commands.",
    )
    parser.add_argument(
        "--version", action="version", version=f"amnesia-agent {_version()}"
    )
    parser.parse_args()
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print()
    except AgentError as e:
        raise SystemExit(1) from e
    except Exception as e:
        report_error(e, context="fatal CLI failure", include_traceback=True)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
