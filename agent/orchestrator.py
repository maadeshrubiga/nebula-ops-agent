"""
The control loop.

This is the "harness" for this project: rather than a prebuilt agent
framework, it implements the observe -> reason -> act -> feed-result-back
loop directly against the Anthropic Messages API's native tool use, which
is what Claude Agent SDK does under the hood. That choice is explained in
the README. Swapping this file for a Claude Agent SDK / Vercel AI SDK
runner is a drop-in change — the skills/tools layer underneath is
harness-agnostic on purpose.

Per-chat conversation history is persisted in SQLite (conversation_state)
so a bill built over several Telegram messages, and general context,
survives process restarts — not just in-memory state.
"""
import json
import os
import anthropic

from db.database import get_conn, transaction
from agent.system_prompt import build_system_prompt
from agent.tools_schema import TOOLS, dispatch_tool
from skills import preferences

MODEL = os.environ.get("NEBULA_MODEL", "claude-sonnet-4-5")
MAX_HISTORY_MESSAGES = 24  # trim to keep token usage sane; preferences (real memory) live in DB, not here

_client = None


def _client_lazy():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def _load_history(chat_id: int):
    conn = get_conn()
    row = conn.execute("SELECT history_json FROM conversation_state WHERE chat_id=?", (chat_id,)).fetchone()
    if row and row["history_json"]:
        return json.loads(row["history_json"])
    return []


def _save_history(chat_id: int, messages: list):
    trimmed = messages[-MAX_HISTORY_MESSAGES:]
    with transaction() as conn:
        conn.execute(
            "INSERT INTO conversation_state (chat_id, history_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(chat_id) DO UPDATE SET history_json=excluded.history_json, updated_at=CURRENT_TIMESTAMP",
            (chat_id, json.dumps(trimmed)),
        )


def reset_history(chat_id: int):
    """Called on /new — clears the conversation, but NOT preferences (that's the point)."""
    with transaction() as conn:
        conn.execute("DELETE FROM conversation_state WHERE chat_id=?", (chat_id,))


def run_turn(chat_id: int, user_text: str, request_token: str):
    """
    request_token: a stable id for this logical user request (we derive it
    from the Telegram update_id upstream). Threaded down to finalize_bill
    calls as the idempotency token if the model needs one and doesn't
    already have a bill-specific token in context.

    Returns (reply_text, [file_paths]) — file_paths are any documents
    (invoice PDF / analysis PPTX) generated this turn, for the bot layer
    to upload.
    """
    client = _client_lazy()
    history = _load_history(chat_id)
    system_prompt = build_system_prompt(preferences.get_all_preferences(), preferences.get_shop_info())

    messages = history + [{"role": "user", "content": user_text}]
    generated_files = []
    final_text_parts = []

    for _ in range(8):  # hard cap on tool-call chaining per turn to avoid runaway loops
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        text_blocks = [b.text for b in response.content if b.type == "text"]
        final_text_parts.extend(text_blocks)

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_input = dict(block.input or {})
            # auto-inject the idempotency token for finalize_bill if the model omitted it
            if block.name == "finalize_bill" and "finalize_token" not in tool_input:
                tool_input["finalize_token"] = f"{chat_id}:{request_token}:{tool_input.get('bill_id')}"

            result = dispatch_tool(block.name, tool_input)
            if isinstance(result, dict) and "file_path" in result:
                generated_files.append(result["file_path"])

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str),
                "is_error": isinstance(result, dict) and "error" in result,
            })

        messages.append({"role": "user", "content": tool_results})

    _save_history(chat_id, messages)
    reply = "\n".join(t for t in final_text_parts if t.strip()) or "Done."
    return reply, generated_files
