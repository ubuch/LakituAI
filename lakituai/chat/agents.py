"""Chat agent for LakituAI.

Provides a REPL interface that connects to a local Ollama model with function
calling support. The agent can query and manage war data conversationally.
"""

import inspect
import sys
from typing import Any

import ollama
from ollama import ChatResponse

from lakituai.chat.tools import ALL_TOOLS

SYSTEM_PROMPT = """\
You are LakituAI, an assistant for tracking Mario Kart World competitive wars.

You have access to tools that let you query and manage war data:
- List and manage players (add/remove)
- List and manage team tags (add/remove)
- View war standings (player and team points)
- Inspect individual race results
- Browse war history

IMPORTANT SETUP ORDER:
1. Before adding players, you MUST check if team tags exist using list_team_tags.
2. If no team tags exist, ask the user what tags to use (e.g., 'RK', 'ne')
   and add them with add_team_tag BEFORE adding any players.
3. Players must include their team tag as prefix or suffix (e.g., 'RK AxeeL', 'ne.ths').

When a user asks about standings, races, or players, use the appropriate tool.
If the user doesn't specify a war, use the current/default war.
Always show results in a clear, readable format.
Be concise but helpful. Respond in the same language the user writes in.
"""

MODEL = "qwen3:4b"


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


def run_chat() -> None:
    """Run the interactive chat REPL.

    Connects to Ollama, sends user messages with tools, handles tool execution
    loops, and prints responses. Exits on 'exit', 'quit', or Ctrl+C.
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

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

        messages.append({"role": "user", "content": user_input})

        try:
            response: ChatResponse = ollama.chat(
                model=MODEL,
                messages=messages,
                tools=ALL_TOOLS,
            )
        except Exception as e:
            print(f"Error connecting to Ollama: {e}")
            print("Make sure Ollama is running (ollama serve) and the model is pulled.")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": response.message.content})

        while response.message.tool_calls:
            for tool_call in response.message.tool_calls:
                tool_name = tool_call.function.name
                print(f"  [tool: {tool_name}]")

                result = _execute_tool(tool_call)

                messages.append(
                    {
                        "role": "tool",
                        "content": result,
                    }
                )

            try:
                response = ollama.chat(
                    model=MODEL,
                    messages=messages,
                    tools=ALL_TOOLS,
                )
            except Exception as e:
                print(f"Error: {e}")
                break

            messages.append({"role": "assistant", "content": response.message.content})

        if response.message.content:
            print(f"\nLakituAI> {response.message.content}\n")


if __name__ == "__main__":
    run_chat()
