import asyncio
import tempfile
import unittest
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import patch

from amnesia_agent_kernel import ExecutionPolicy, KernelSession, ProviderConfig


class KernelTests(unittest.IsolatedAsyncioTestCase):
    def make_config(self) -> ProviderConfig:
        return ProviderConfig(model="openai/test", provider_params={"test": True})

    def _session(self, directory: str) -> KernelSession:
        with patch(
            "amnesia_agent_kernel.provider.litellm.validate_environment",
            return_value={"keys_in_environment": True},
        ):
            return KernelSession(
                self.make_config(), ExecutionPolicy(), workspace_root=directory
            )

    @staticmethod
    def _ok_completion():
        async def fake_completion(**kwargs: object) -> object:
            async def stream() -> object:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="ok", tool_calls=[]))
                    ]
                )

            return stream()

        return fake_completion

    def test_provider_config_is_snapshotted(self) -> None:
        params = {"temperature": 0.1}
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment",
                return_value={"keys_in_environment": True},
            ):
                session = KernelSession(
                    ProviderConfig("openai/test", provider_params=params),
                    workspace_root=directory,
                )
            params["unexpected"] = "changed"
            self.assertNotIn("unexpected", session.provider.provider_params or {})

    def test_workspace_constructor_creates_empty_kernel_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment",
                return_value={"keys_in_environment": True},
            ):
                session = KernelSession(self.make_config(), workspace_root=directory)
            for name in ("system_prompt.md", "memory.md"):
                path = session._workspace.root / name
                self.assertTrue(path.exists(), name)
                self.assertEqual(path.read_text(encoding="utf-8"), "")
            self.assertFalse((session._workspace.root / "history.jsonl").exists())
            self.assertFalse((session._workspace.root / "history").exists())
            self.assertFalse((session._workspace.root / "config.json").exists())

    def test_reset_history_clears_daily_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment",
                return_value={"keys_in_environment": True},
            ):
                session = KernelSession(self.make_config(), workspace_root=directory)
            session.update_system_prompt("changed")
            session.update_memory("changed")
            session.update_history([{"role": "user", "content": "hi"}])
            session.reset_history()
            self.assertEqual(session.read_system_prompt(), "changed")
            self.assertEqual(session.read_memory(), "changed")
            self.assertEqual(session.read_history(), [])

    def test_default_command_timeout_is_1800(self) -> None:
        self.assertEqual(ExecutionPolicy().command_timeout_seconds, 1800.0)

    async def test_turn_aclosing_releases_slot_for_next_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = self._session(directory)
            with patch(
                "amnesia_agent_kernel.agent.acompletion", new=self._ok_completion()
            ):
                async with aclosing(session.turn("first")) as events:
                    async for _ in events:
                        pass
                self.assertFalse(session._turn_open)
                async with aclosing(session.turn("second")) as events:
                    async for _ in events:
                        pass
            users = [
                record["content"]
                for record in session.read_history()
                if record.get("role") == "user"
            ]
            self.assertEqual(users, ["first", "second"])

    async def test_abandoned_turn_without_aclose_fails_loud_on_next(self) -> None:
        async def partial_then_hang(**kwargs: object) -> object:
            async def stream() -> object:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="partial", tool_calls=[])
                        )
                    ]
                )
                await asyncio.sleep(60)

            return stream()

        with tempfile.TemporaryDirectory() as directory:
            session = self._session(directory)
            with patch("amnesia_agent_kernel.agent.acompletion", new=partial_then_hang):
                abandoned = session.turn("stuck")
                first = await abandoned.__anext__()
                self.assertEqual(first, "partial")
                self.assertTrue(session._turn_open)
                with self.assertRaises(RuntimeError) as ctx:
                    next_turn = session.turn("next")
                    await next_turn.__anext__()
                self.assertIn("still open", str(ctx.exception))
                # Defined cleanup path: aclose releases the slot.
                await abandoned.aclose()
                self.assertFalse(session._turn_open)
            with patch(
                "amnesia_agent_kernel.agent.acompletion", new=self._ok_completion()
            ):
                async with aclosing(session.turn("recovered")) as events:
                    async for _ in events:
                        pass

    async def test_overlapping_turns_fail_loud_not_queued(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_completion(**kwargs: object) -> object:
            started.set()
            await release.wait()

            async def stream() -> object:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="ok", tool_calls=[]))
                    ]
                )

            return stream()

        with tempfile.TemporaryDirectory() as directory:
            session = self._session(directory)
            with patch("amnesia_agent_kernel.agent.acompletion", new=fake_completion):
                first = session.turn("a")

                async def run_first() -> None:
                    async with aclosing(first) as events:
                        async for _ in events:
                            pass

                first_task = asyncio.create_task(run_first())
                await started.wait()
                with self.assertRaises(RuntimeError) as ctx:
                    second = session.turn("b")
                    await second.__anext__()
                self.assertIn("still open", str(ctx.exception))
                release.set()
                await first_task


if __name__ == "__main__":
    unittest.main()
