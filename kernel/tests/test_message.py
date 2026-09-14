import tempfile
import unittest

from amnesia_agent_kernel.message import build_messages, truncate_middle
from amnesia_agent_kernel.workspace import Workspace


class MessageTests(unittest.TestCase):
    def test_middle_truncation_respects_the_limit(self) -> None:
        self.assertEqual(truncate_middle("abcdef", 6), "abcdef")
        self.assertEqual(truncate_middle("abcdefghij", 8), "ab\n...\nj")
        self.assertEqual(truncate_middle("abcdefghij", 7), "a\n...\nj")
        self.assertEqual(truncate_middle("abcdefghij", 5), "\n...\n")
        self.assertEqual(truncate_middle("abcdefghij", 1), "\n")

    def test_truncation_never_exceeds_the_limit(self) -> None:
        for limit in range(1, 30):
            result = truncate_middle("x" * 100, limit)
            self.assertLessEqual(len(result), max(limit, 5))

    def test_user_content_is_not_sliced_but_other_content_is(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            messages = build_messages(
                "prompt",
                "0123456789",
                [{"role": "assistant", "content": "abcdefghij"}],
                6,
                workspace,
            )
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "prompt")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "0123456789")
        self.assertEqual(messages[2]["content"], "\n...\n")

    def test_empty_system_prompt_and_memory_omit_system_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            messages = build_messages("", "hi", [], 100, workspace)
        self.assertEqual(messages, [{"role": "user", "content": "hi"}])

    def test_joins_non_empty_system_prompt_and_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.update_memory("memo")
            messages = build_messages("prompt", "hi", [], 100, workspace)
        self.assertEqual(messages[0], {"role": "system", "content": "prompt\n\nmemo"})


if __name__ == "__main__":
    unittest.main()
