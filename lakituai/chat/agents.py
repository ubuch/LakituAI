"""Chat agent for LakituAI.

Provides a REPL interface that connects to a local Ollama model with function
calling support. The agent can query and manage war data conversationally.
"""

import inspect
import json
import re
from types import SimpleNamespace
from typing import Any, Optional

import ollama
from ollama import ChatResponse

from lakituai.chat.tools import ALL_TOOLS

# Safety cap: if the model keeps calling tools without answering, stop after
# this many rounds instead of looping forever.
MAX_TOOL_ROUNDS = 15

# qwen3 tool calling is much more reliable with low temperature.
TEMPERATURE = 0

_ESCAPED_UNICODE = re.compile(r"\\u([0-9a-fA-F]{4})")

# qwen3 sometimes emits a tool call as raw JSON in the message text instead of
# a structured tool_call. Match {"name": "...", "arguments": {...}}.
_TOOL_CALL_IN_TEXT = re.compile(
    r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
    re.DOTALL,
)

SYSTEM_PROMPT = """\
You are LakituAI, an assistant for tracking Mario Kart World competitive wars.

You have access to tools that let you query and manage war data:
- List, add, remove, and rename players
- List and manage team tags (add/remove)
- View war standings (player and team points)
- Inspect individual race results and positions
- Get player stats (avg position, best/worst race)
- Get team stats (total points, top/bottom player)
- Compare two players head-to-head
- Get a quick summary of a race or an entire war
- Get a race's team result with net points (e.g., 'RK +2', 'ne -2')
- Browse war history

IMPORTANT SETUP ORDER:
1. Before adding players, you MUST check if team tags exist using list_team_tags.
2. If no team tags exist, ask the user what tags to use (e.g., 'RK', 'ne')
   and add them with add_team_tag BEFORE adding any players.
3. Players must include their team tag as prefix or suffix (e.g., 'RK AxeeL', 'ne.ths').

Player names may include accents and special characters (e.g., 'César').
Add them EXACTLY as the user spells them: accents are fully supported and
must never be removed or treated as an error.

If add_player reports that a player already exists, simply tell the user it
is already registered. Do not call the same tool again for that player.

When a user asks about standings, races, or players, use the appropriate tool.
If the user doesn't specify a war, use the current/default war.
Always show results in a clear, readable format.
Be concise but helpful. Respond in the same language the user writes in, but never
translate the words "war/wars" and "tag/tags".

ACT, DO NOT DESCRIBE: when the user asks you to add, remove, rename, or query
something, call the tools immediately and completely. Never answer with a
description of the steps you would take instead of doing them. If the setup
is already done (e.g., team tags exist), proceed directly without commenting
on the setup process.
"""

# Model selection: We tested qwen3:1.7b (1.4GB, fast
# but poor tool calling and conversation quality),
# and qwen3:4b (2.5GB, best balance for our hardware).
#
# qwen3:4b requires ~6GB VRAM for optimal performance (model + KV cache).
# With less VRAM, Ollama offloads layers to CPU, slowing inference.
# On a 4GB GPU (e.g., RTX 3050 Ti), expect slower responses.
# For best experience, use a GPU with 6GB+ VRAM.
MODEL = "qwen3:4b"


def get_model_status() -> Optional[str]:
    """Check whether the chat model is usable right now.

    Returns:
        None if the model is installed and Ollama is reachable, otherwise
        a human-readable message describing what is wrong.
    """
    try:
        installed = [m.model for m in ollama.list().models]
    except Exception:
        return (
            "Chat is unavailable: Ollama is not running. "
            "Start it (ollama serve) and try again."
        )

    if not any(name == MODEL or name.startswith(MODEL + ":") for name in installed):
        return (
            f"Chat is unavailable: the model '{MODEL}' is not installed. "
            f"Install the Qwen model with: ollama pull {MODEL}"
        )
    return None


def _unescape_unicode(value: str) -> str:
    """Decode literal \\uXXXX escape sequences (e.g. 'C\\u00e9sar' -> 'César').

    Small models sometimes emit escaped unicode in tool-call arguments.
    Only \\uXXXX sequences are decoded, other backslashes are left alone.
    """
    if "\\u" not in value:
        return value
    return _ESCAPED_UNICODE.sub(lambda m: chr(int(m.group(1), 16)), value)


def _make_tool_call(name: str, arguments: dict) -> Any:
    """Build a tool_call-like object for the agent loop."""
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def _extract_tool_calls_from_text(content: str) -> Optional[Any]:
    """Parse JSON tool calls embedded in plain text (qwen3 quirk).

    Small models sometimes answer with raw JSON instead of structured
    tool_calls. Handled shapes:
    - A single call: {"name": "add_player", "arguments": {...}}
    - A list of add_player requests:
      [{"name": "César", "team_tag": "RK"}, {"name": "ths", "team_tag": "ne"}]
    - The same, wrapped in a ```json code fence.

    Args:
        content: The assistant's message text.

    Returns:
        A tool_call-like object, a list of them, or None.
    """
    if not content:
        return None

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    data = None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = None

    if isinstance(data, list):
        calls = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            if isinstance(item.get("team_tag"), str):
                calls.append(
                    _make_tool_call(
                        "add_player",
                        {"name": item["name"], "team_tag": item["team_tag"]},
                    )
                )
            elif isinstance(item.get("arguments"), dict):
                calls.append(_make_tool_call(item["name"], item["arguments"]))
        if not calls:
            return None
        return calls if len(calls) > 1 else calls[0]

    if not isinstance(data, dict):
        match = _TOOL_CALL_IN_TEXT.search(content)
        if not match:
            return None
        name, args_json = match.group(1), match.group(2)
        try:
            data = {"name": name, "arguments": json.loads(args_json)}
        except (ValueError, TypeError):
            return None

    if not isinstance(data, dict):
        return None
    name = data.get("name")
    arguments = data.get("arguments")
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return None

    return _make_tool_call(name, arguments)


def _execute_tool(tool_call: Any) -> str:
    """Execute a tool call from the LLM and return the result as a string.

    Finds the matching Python function by name, converts argument types
    to match the function signature, and calls it.

    Args:
        tool_call: An Ollama tool_call object with function.name and function.arguments.

    Returns:
        The tool's return value as a string.
    """
    func_name = tool_call.function.name
    func = next((t for t in ALL_TOOLS if t.__name__ == func_name), None)
    if func is None:
        return f"Error: unknown tool '{func_name}'"

    sig = inspect.signature(func)
    kwargs = {}
    for param_name, param_value in tool_call.function.arguments.items():
        if param_name in sig.parameters:
            if isinstance(param_value, str):
                param_value = _unescape_unicode(param_value)
            param_type = sig.parameters[param_name].annotation
            if param_type is not inspect.Parameter.empty:
                try:
                    kwargs[param_name] = param_type(param_value)
                except (ValueError, TypeError):
                    kwargs[param_name] = param_value
            else:
                kwargs[param_name] = param_value

    try:
        result = func(**kwargs)
    except Exception as e:
        result = f"Error executing {func_name}: {e}"

    return str(result)


class ChatSession:
    """Holds conversation history and answers one message at a time.

    Used by both the REPL (run_chat) and the desktop GUI, so the same
    tool-calling loop runs everywhere. Not thread-safe: call respond()
    from a single thread at a time.
    """

    def __init__(self) -> None:
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def respond(self, user_input: str) -> str:
        """Send a user message and return the assistant's final reply.

        Runs the tool-calling loop until the model answers without tools.
        On error, rolls back the conversation to its previous state and
        re-raises so the caller can show a friendly message.

        Args:
            user_input: The user's message.

        Returns:
            The assistant's final text response (may be empty).
        """
        start_len = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})

        try:
            response: ChatResponse = ollama.chat(
                model=MODEL,
                messages=self.messages,
                tools=ALL_TOOLS,
                options={"temperature": TEMPERATURE},
            )

            tool_rounds = 0
            while True:
                # qwen3 sometimes returns the tool call as JSON in the message
                # text instead of a structured tool_call. Detect and run it.
                if not response.message.tool_calls:
                    text_calls = _extract_tool_calls_from_text(
                        response.message.content
                    )
                    if isinstance(text_calls, list):
                        response.message.tool_calls = text_calls
                    elif text_calls is not None:
                        response.message.tool_calls = [text_calls]

                self.messages.append(
                    {"role": "assistant", "content": response.message.content}
                )

                if not response.message.tool_calls:
                    return response.message.content

                tool_rounds += 1
                if tool_rounds > MAX_TOOL_ROUNDS:
                    return (
                        "I stopped because this request needed too many tool "
                        "calls in a row. Please ask for one action at a time."
                    )

                for tool_call in response.message.tool_calls:
                    tool_name = tool_call.function.name
                    print(f"  [tool: {tool_name}]")

                    result = _execute_tool(tool_call)

                    self.messages.append(
                        {
                            "role": "tool",
                            "content": result,
                        }
                    )

                response = ollama.chat(
                    model=MODEL,
                    messages=self.messages,
                    tools=ALL_TOOLS,
                    options={"temperature": TEMPERATURE},
                )
        except Exception:
            del self.messages[start_len:]
            raise


def run_chat() -> None:
    """Run the interactive chat REPL.

    Connects to Ollama, sends user messages with tools, handles tool execution
    loops, and prints responses. Exits on 'exit', 'quit', or Ctrl+C.
    """
    session = ChatSession()

    print("LakituAI Chat")
    print(f"Model: {MODEL}")
    print("Type 'exit' or 'quit' to leave.\n")

    while True:
        try:
            user_input = input("You> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Bye!")
            break

        try:
            content = session.respond(user_input)
        except Exception as e:
            print(f"Error connecting to Ollama: {e}")
            print("Make sure Ollama is running (ollama serve) and the model is pulled.")
            continue

        if content:
            print(f"\nLakituAI> {content}\n")


if __name__ == "__main__":
    run_chat()
