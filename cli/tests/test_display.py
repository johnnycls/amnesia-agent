import contextlib
import io
import unittest

from amnesia_agent_cli.display import TerminalRenderer, _print_tool, _tool_command


def render(renderer: TerminalRenderer, event: object) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        renderer.render(event)
    return buffer.getvalue()


class DisplayTests(unittest.TestCase):
    def test_tool_command_extraction(self) -> None:
        call = {"function": {"arguments": '{"command": "ls -la"}'}}
        self.assertEqual(_tool_command(call), "ls -la")
        self.assertEqual(_tool_command({"function": {"arguments": "oops"}}), "oops")

    def test_tool_output_is_trimmed_and_exit_code_shown(self) -> None:
        content = "exit code: 1\n" + "\n".join(f"line{index}" for index in range(10))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            _print_tool(content)
        output = buffer.getvalue()
        self.assertIn("exit code 1", output)
        self.assertIn("line0", output)
        self.assertIn("line9", output)
        self.assertNotIn("line5", output)

    def test_streamed_content_is_bold_and_not_printed_twice(self) -> None:
        message = {"role": "assistant", "content": "hello", "tool_calls": []}
        renderer = TerminalRenderer()
        self.assertEqual(render(renderer, "hel") + render(renderer, "lo"), "[1mhello")
        self.assertEqual(render(renderer, message), "[0m\n")

    def test_unstreamed_assistant_content_is_printed_bold(self) -> None:
        message = {"role": "assistant", "content": "hi", "tool_calls": []}
        output = render(TerminalRenderer(), message)
        self.assertIn("hi", output)
        self.assertTrue(output.startswith("[1m"))

    def test_assistant_tool_commands_are_rendered(self) -> None:
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "shell", "arguments": '{"command": "ls"}'},
                }
            ],
        }
        output = render(TerminalRenderer(), message)
        self.assertIn("$ ls", output)

    def test_tool_result_event_is_rendered(self) -> None:
        result = {"role": "tool", "tool_call_id": "c1", "content": "exit code: 0\nok"}
        self.assertIn("exit code 0", render(TerminalRenderer(), result))

    def test_reset_closes_a_half_finished_stream(self) -> None:
        renderer = TerminalRenderer()
        with contextlib.redirect_stdout(io.StringIO()):
            renderer.render("partial")
        closed = io.StringIO()
        with contextlib.redirect_stdout(closed):
            renderer.reset()
        self.assertEqual(closed.getvalue(), "[0m\n")
        output = render(renderer, {"role": "assistant", "content": "x"})
        self.assertTrue(output.startswith("[1m"))


if __name__ == "__main__":
    unittest.main()
