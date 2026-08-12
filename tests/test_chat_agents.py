"""Tests for the chat agent loop and tool-call handling."""

import unittest
from types import SimpleNamespace
from unittest import mock

from lakituai.chat import agents


def _tool_call_response():
    """A fake Ollama response that keeps requesting one tool call."""
    call = SimpleNamespace(
        function=SimpleNamespace(name="list_players", arguments={})
    )
    msg = SimpleNamespace(content="", tool_calls=[call])
    return SimpleNamespace(message=msg)


class UnicodeHandlingTests(unittest.TestCase):
    """Tests for escaped-unicode decoding in tool arguments."""

    def test_unescape_unicode(self):
        self.assertEqual(agents._unescape_unicode("C\\u00e9sar"), "César")

    def test_unescape_unicode_leaves_plain_text_alone(self):
        self.assertEqual(agents._unescape_unicode("César"), "César")

    def test_unescape_unicode_leaves_backslashes_alone(self):
        self.assertEqual(agents._unescape_unicode("a\\b\\u0000"), "a\\b\x00")

    def test_execute_tool_decodes_escaped_unicode(self):
        tool_call = SimpleNamespace(
            function=SimpleNamespace(
                name="add_player",
                arguments={"name": "C\\u00e9sar", "team_tag": "RK"},
            )
        )
        with mock.patch("lakituai.chat.tools.player_management") as pm:
            pm.add_player.return_value = (True, "added")
            result = agents._execute_tool(tool_call)
        pm.add_player.assert_called_once_with("RK César")
        self.assertEqual(result, "added")

    def test_execute_tool_unknown_tool(self):
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name="nope", arguments={})
        )
        self.assertIn("unknown tool", agents._execute_tool(tool_call))

    def test_execute_tool_catches_exceptions(self):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        boom.__name__ = "list_players"
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name="list_players", arguments={})
        )
        with mock.patch("lakituai.chat.agents.ALL_TOOLS", [boom]):
            result = agents._execute_tool(tool_call)
        self.assertIn("Error executing", result)
        self.assertIn("boom", result)


class TextToolCallExtractionTests(unittest.TestCase):
    """Tests for extracting JSON tool calls from plain model text."""

    def test_plain_json_object(self):
        call = agents._extract_tool_calls_from_text(
            '{"name": "add_player", "arguments": {"name": "César", "team_tag": "RK"}}'
        )
        self.assertIsNotNone(call)
        self.assertEqual(call.function.name, "add_player")
        self.assertEqual(call.function.arguments["name"], "César")

    def test_json_in_code_fence(self):
        call = agents._extract_tool_calls_from_text(
            '```json\n{"name": "list_players", "arguments": {}}\n```'
        )
        self.assertIsNotNone(call)
        self.assertEqual(call.function.name, "list_players")

    def test_list_of_players_becomes_add_player_calls(self):
        calls = agents._extract_tool_calls_from_text(
            '[{"name": "César", "team_tag": "RK"}, {"name": "ths", "team_tag": "ne"}]'
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].function.name, "add_player")
        self.assertEqual(calls[0].function.arguments["name"], "César")
        self.assertEqual(calls[1].function.arguments["team_tag"], "ne")

    def test_plain_text_returns_none(self):
        self.assertIsNone(
            agents._extract_tool_calls_from_text("Hola, esto es texto.")
        )

    def test_empty_content_returns_none(self):
        self.assertIsNone(agents._extract_tool_calls_from_text(""))

    def test_invalid_arguments_returns_none(self):
        call = agents._extract_tool_calls_from_text(
            '{"name": "add_player", "arguments": "oops"}'
        )
        self.assertIsNone(call)


class ToolLoopCapTests(unittest.TestCase):
    """Tests that respond() stops after MAX_TOOL_ROUNDS tool rounds."""

    def test_respond_stops_after_max_tool_rounds(self):
        session = agents.ChatSession()
        with mock.patch(
            "lakituai.chat.agents.ollama.chat",
            return_value=_tool_call_response(),
        ):
            reply = session.respond("hi")

        self.assertIn("one action at a time", reply)
        # user + system + initial assistant + (tool + assistant) per round.
        self.assertEqual(len(session.messages), 3 + agents.MAX_TOOL_ROUNDS * 2)

    def test_respond_returns_final_answer_without_tools(self):
        session = agents.ChatSession()
        final = SimpleNamespace(message=SimpleNamespace(content="All good", tool_calls=[]))
        with mock.patch(
            "lakituai.chat.agents.ollama.chat",
            return_value=final,
        ):
            reply = session.respond("hi")

        self.assertEqual(reply, "All good")

    def test_respond_executes_json_tool_call_in_text(self):
        session = agents.ChatSession()
        responses = iter(
            [
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"name": "list_players", "arguments": {}}',
                        tool_calls=[],
                    )
                ),
                SimpleNamespace(
                    message=SimpleNamespace(content="Done", tool_calls=[])
                ),
            ]
        )
        with mock.patch(
            "lakituai.chat.agents.ollama.chat",
            side_effect=lambda **kwargs: next(responses),
        ):
            reply = session.respond("hi")

        self.assertEqual(reply, "Done")


class ModelStatusTests(unittest.TestCase):
    """Tests for get_model_status()."""

    def test_ok_when_model_installed(self):
        fake_models = [SimpleNamespace(model="qwen3:4b"), SimpleNamespace(model="llama3")]
        with mock.patch(
            "lakituai.chat.agents.ollama.list",
            return_value=SimpleNamespace(models=fake_models),
        ):
            self.assertIsNone(agents.get_model_status())

    def test_missing_model_when_not_installed(self):
        fake_models = [SimpleNamespace(model="llama3")]
        with mock.patch(
            "lakituai.chat.agents.ollama.list",
            return_value=SimpleNamespace(models=fake_models),
        ):
            message = agents.get_model_status()
            self.assertIsNotNone(message)
            self.assertIn("not installed", message)
            self.assertIn(agents.MODEL, message)

    def test_matches_qualified_model_names(self):
        fake_models = [SimpleNamespace(model="qwen3:4b:latest")]
        with mock.patch(
            "lakituai.chat.agents.ollama.list",
            return_value=SimpleNamespace(models=fake_models),
        ):
            self.assertIsNone(agents.get_model_status())

    def test_error_when_ollama_unreachable(self):
        with mock.patch(
            "lakituai.chat.agents.ollama.list",
            side_effect=ConnectionError("server down"),
        ):
            message = agents.get_model_status()
            self.assertIsNotNone(message)
            self.assertIn("not running", message)


if __name__ == "__main__":
    unittest.main()
