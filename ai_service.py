"""ai_service.py - Groq AI Integration and Dynamic Tool-Calling Engine for CricScorer.

Handles communication with the Groq Chat Completions API.
Implements bounded multi-round tool calling for dynamic data retrieval.
Maintains strict read-only safety, error recovery, and live scoring isolation.
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, List, Any, Optional, Tuple

# Auto-load .env file if present
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip("'\"")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

import ai_data_access
import ai_chat_storage

# Default to Groq's high-speed, high-accuracy tool-calling model
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_TOOL_ROUNDS = 5
REQUEST_TIMEOUT_SECONDS = 35


SYSTEM_PROMPT = """You are the **CricScorer AI Cricket Assistant**, an intelligent cricket analytics and data assistant built directly into the CricScorer Admin Panel.

### CORE IDENTITY & CONVERSATION PROTOCOLS:
1. **Greetings**: When greeted (e.g., "Hello", "Hi", "Hey", "Good morning"), respond warmly and professionally, welcoming the administrator and asking how you can assist with CricScorer cricket statistics, matches, scorecards, or players today. DO NOT invoke any tools or output unprompted statistics on a greeting.
2. **Identity**: When asked "Who are you?", identify yourself concisely as the **CricScorer AI Cricket Assistant**, an analytics engine embedded in the CricScorer Admin Panel. Explain what you can do (player stats & form, match scorecards, ball-by-ball summaries, tournament standings, leaderboards, dot-ball analysis, tactical collapse investigations). DO NOT invoke tools or output unprompted statistics on identity questions.
3. **Latest Intent Priority & Topic Shifts**:
   - Always prioritize the administrator's latest message as the primary task.
   - If the user asks a follow-up question related to the current topic (e.g., "What about his bowling?", "Compare him to Smith"): retain the conversation context and build upon previous turns.
   - If the user switches topics or asks a new, unrelated question (e.g., asking for tournament standings after previously analyzing dot balls): completely switch focus to the new topic. DO NOT carry over, repeat, or summarize previous analyses (such as dot balls or batting collapses) into unrelated answers.
   - NEVER repeat an unrequested dot-ball analysis.
4. **Data-Backed Accuracy**: Every cricket answer must be grounded in verified data retrieved through your available tools. Do not invent match results, players, scores, rankings, formulas, or statistics.
5. **Dynamic Tool Calling & Dot Balls**:
   - Query your tools when the administrator asks for specific cricket data.
   - For dot-ball queries, use the `analyze_dot_balls` tool. Distinguish between:
     * Dot balls faced by a batter (legal delivery faced with 0 runs off bat).
     * Dot balls bowled by a bowler (legal delivery where bowler conceded 0 runs; byes/leg-byes not charged).
     * Totals for an innings, match, tournament, or career.
   - If a request is ambiguous (e.g., asking "how many dot balls" without specifying player or match), ask a short clarifying question or provide the tournament/match summary while offering to drill down.
6. **Strict Read-Only Status**: You are strictly a read-only analytics assistant. You CANNOT insert, update, or delete cricket records, awards, or rankings.
7. **Live vs. Completed Distinction**: If data relates to an active/live match (status 'live' or 'toss_done'), explicitly note that the information is from an in-progress match snapshot.
8. **Formatting**:
   - Use clean Markdown formatting.
   - Use Markdown tables for player comparisons, leaderboards, scorecards, and head-to-head statistics.
   - Highlight key statistics with bold text and emojis (e.g. 🏏 🏆 🎯 📊).
   - Keep answers professional, structured, and easy to scan for cricket administrators.
"""


def is_groq_configured() -> bool:
    """Checks if the GROQ_API_KEY environment variable is present."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    return bool(key)


def get_current_model() -> str:
    """Returns the configured Groq model identifier."""
    return os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip()


def _parse_retry_after(headers, default_delay: float = 2.0) -> float:
    """Parses Retry-After header (seconds or HTTP-date) with bounded range."""
    if not headers:
        return default_delay
    val = headers.get("Retry-After")
    if not val:
        return default_delay
    val_str = str(val).strip()
    try:
        secs = float(val_str)
        return min(max(secs, 1.0), 10.0)
    except ValueError:
        pass
    try:
        import email.utils
        from datetime import datetime, timezone
        parsed_time = email.utils.parsedate_to_datetime(val_str)
        diff = (parsed_time - datetime.now(timezone.utc)).total_seconds()
        return min(max(diff, 1.0), 10.0)
    except Exception:
        return default_delay


def _call_groq_api(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Sends an HTTP POST request to the Groq Chat Completions endpoint.
    Implements bounded retries with exponential backoff, jitter, and Retry-After header handling.
    Gracefully falls back across models (qwen/qwen3.8-27b -> openai/gpt-oss-120b -> openai/gpt-oss-20b).
    Does NOT retry indefinitely, ensuring scoring engine and admin UI are never blocked.
    """
    import time
    import random
    import re

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured. Please set the GROQ_API_KEY environment variable.")

    primary_model = get_current_model()
    all_fallback_models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
    models_to_try = [primary_model]
    for fb in all_fallback_models:
        if fb not in models_to_try:
            models_to_try.append(fb)
    models_to_try = models_to_try[:2]  # Bounded to maximum 2 models

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "CricScorer-AI-Admin/1.0"
    }

    payload = {
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 2048,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    max_retries_per_model = 2
    last_err_msg = None
    last_err_code = None

    for model_candidate in models_to_try:
        payload["model"] = model_candidate
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(GROQ_API_URL, data=data_bytes, headers=headers, method="POST")

        for attempt in range(max_retries_per_model):
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                    resp_body = resp.read().decode("utf-8")
                    return json.loads(resp_body)

            except urllib.error.HTTPError as e:
                error_body = ""
                try:
                    error_body = e.read().decode("utf-8")
                    err_json = json.loads(error_body)
                    msg = err_json.get("error", {}).get("message", error_body)
                except Exception:
                    msg = error_body or str(e)

                last_err_code = e.code
                last_err_msg = f"Groq API error ({e.code}): {msg}"

                # Non-retryable client errors: fail immediately
                if e.code in (400, 401, 403, 404):
                    raise RuntimeError(last_err_msg)

                # Retryable errors: 503 (Over Capacity), 429 (Rate Limit), 502, 504, 500
                if e.code in (503, 429, 502, 504, 500):
                    retry_after = _parse_retry_after(e.headers, default_delay=1.5)

                    if e.code == 429:
                        match = re.search(r'try again in ([\d\.]+)s', msg, re.IGNORECASE)
                        if match:
                            try:
                                retry_after = min(max(float(match.group(1)), 1.0), 10.0)
                            except Exception:
                                pass

                    # If retry wait is too high (> 6s), switch to fallback model immediately
                    if retry_after > 6.0 and model_candidate != models_to_try[-1]:
                        break

                    # Exponential backoff + random jitter
                    jitter = random.uniform(0.1, 0.75)
                    backoff_delay = min(retry_after + jitter, 1.0 * (2 ** attempt) + jitter)
                    backoff_delay = min(backoff_delay, 5.0)

                    if attempt < max_retries_per_model - 1:
                        time.sleep(backoff_delay)
                        continue
                    else:
                        break

                raise RuntimeError(last_err_msg)

            except (urllib.error.URLError, TimeoutError) as e:
                err_str = str(getattr(e, "reason", e))
                last_err_msg = f"Network timeout/error connecting to Groq: {err_str}"
                if attempt < max_retries_per_model - 1:
                    jitter = random.uniform(0.2, 0.5)
                    time.sleep(1.0 + jitter)
                    continue
                else:
                    break

            except Exception as e:
                raise RuntimeError(f"Unexpected error communicating with Groq: {str(e)}")

    if last_err_code == 503:
        raise RuntimeError("Groq AI servers are temporarily over capacity (503). Please wait a moment and try your request again.")
    elif last_err_code == 429:
        raise RuntimeError("Groq AI rate limit reached (429). Please wait a moment and try your request again.")
    raise RuntimeError(last_err_msg or "Failed to connect to Groq AI service.")


def _clean_and_validate_messages(raw_history: List[Dict[str, Any]], system_prompt: str, is_conversational_only: bool = False) -> List[Dict[str, Any]]:
    """
    Constructs a well-formed message sequence compliant with Groq/OpenAI specs:
    1. System message at index 0.
    2. Strips orphaned tool messages at the start of history.
    3. Guarantees every assistant tool_calls block is followed by corresponding tool responses.
    4. If is_conversational_only is True (e.g. for greetings or identity questions), strips raw tool
       payloads so the model doesn't hallucinate or drag along previous statistical context.
    """
    clean_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]

    entries: List[Dict[str, Any]] = []
    for m in raw_history:
        role = m.get("role", "user")
        if is_conversational_only and role == "tool":
            continue

        entry: Dict[str, Any] = {"role": role}
        if role == "tool":
            entry["content"] = m.get("content") or ""
            entry["tool_call_id"] = m.get("tool_call_id") or ""
            if m.get("name"):
                entry["name"] = m["name"]
        elif role == "assistant":
            entry["content"] = m.get("content") or ""
            if not is_conversational_only and m.get("tool_calls"):
                entry["tool_calls"] = m["tool_calls"]
        else:  # user or system
            entry["content"] = m.get("content") or ""

        entries.append(entry)

    # Discard any leading tool messages that don't have an assistant preceding them
    while entries and entries[0].get("role") == "tool":
        entries.pop(0)

    # Validate tool call / tool response pairs
    idx = 0
    while idx < len(entries):
        entry = entries[idx]
        if entry.get("role") == "assistant" and entry.get("tool_calls"):
            expected_ids = {tc.get("id") for tc in entry["tool_calls"] if isinstance(tc, dict) and tc.get("id")}
            found_ids = set()
            j = idx + 1
            while j < len(entries) and entries[j].get("role") == "tool":
                tid = entries[j].get("tool_call_id")
                if tid:
                    found_ids.add(tid)
                j += 1

            if not expected_ids.issubset(found_ids):
                # Missing corresponding tool responses; drop tool_calls to avoid 400 Bad Request
                entry.pop("tool_calls", None)
                if not entry.get("content"):
                    entry["content"] = "Retrieved match analytics."
        idx += 1

    clean_messages.extend(entries)
    return clean_messages


def process_chat_message(
    admin_username: str,
    user_message: str,
    conversation_id: Optional[str] = None,
    conn=None
) -> Dict[str, Any]:
    """
    Processes an incoming user message through Groq with dynamic read-only tool calling.
    Maintains conversation persistence and 48-hour expiration.
    """
    import time

    # 1. Ensure conversation exists or create a new one
    if not conversation_id:
        title_snippet = user_message.strip().replace("\n", " ")[:35]
        if len(user_message.strip()) > 35:
            title_snippet += "..."
        conversation_id = ai_chat_storage.create_conversation(admin_username, title=title_snippet, conn=conn)
    else:
        conv = ai_chat_storage.get_conversation(conversation_id, admin_username=admin_username, conn=conn)
        if not conv:
            title_snippet = user_message.strip().replace("\n", " ")[:35]
            conversation_id = ai_chat_storage.create_conversation(admin_username, title=title_snippet, conn=conn)

    # 2. Record the user message
    ai_chat_storage.add_message(
        conversation_id=conversation_id,
        role="user",
        content=user_message,
        conn=conn
    )

    # Check for Groq API key configuration
    if not is_groq_configured():
        warning_msg = (
            "⚠️ **Groq API Key Not Configured**\n\n"
            "The `GROQ_API_KEY` environment variable is not set on the server. "
            "To enable the AI Cricket Assistant, please set your Groq API key in your environment variables or `.env` file:\n\n"
            "```bash\n"
            "GROQ_API_KEY=gsk_your_groq_api_key_here\n"
            "```\n\n"
            "Once set, reload or send a message to start querying cricket statistics."
        )
        ai_chat_storage.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=warning_msg,
            metadata={"error": "missing_api_key", "is_configured": False},
            conn=conn
        )
        return {
            "success": True,
            "conversation_id": conversation_id,
            "response": warning_msg,
            "is_configured": False,
            "tools_called": []
        }

    # 3. Detect conversational intents (greetings, identity)
    user_clean = user_message.strip().lower()
    is_greeting = user_clean in ("hello", "hi", "hey", "hello!", "hi!", "good morning", "good evening", "good afternoon", "greetings")
    is_identity = user_clean in ("who are you", "who are you?", "who are u", "who are u?", "what are you", "what are you?", "what is cricscorer ai", "what can you do", "what can you do?")

    # Retrieve message history (last 8 messages to conserve tokens)
    raw_history = ai_chat_storage.get_messages(conversation_id, limit=8, conn=conn)

    # Format and sanitize messages array for Groq
    is_conversational_only = is_greeting or is_identity
    api_messages = _clean_and_validate_messages(
        raw_history=raw_history,
        system_prompt=SYSTEM_PROMPT,
        is_conversational_only=is_conversational_only
    )

    # If simple greeting or identity query, suppress tool schema to prevent hallucinated tool calls
    tools_to_provide = None if is_conversational_only else ai_data_access.AI_TOOLS_DEFINITIONS

    # 4. Tool Execution Loop (up to MAX_TOOL_ROUNDS)
    tools_called_log: List[str] = []
    has_live_data = False
    rounds = 0

    try:
        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            if rounds > 1:
                # Brief inter-round pause to prevent free-tier token burst limit
                time.sleep(1.0)

            response = _call_groq_api(messages=api_messages, tools=tools_to_provide)
            
            choices = response.get("choices", [])
            if not choices:
                raise RuntimeError("Empty response received from Groq API.")

            choice = choices[0]
            msg = choice.get("message", {})
            content = msg.get("content")
            tool_calls = msg.get("tool_calls")

            if not tool_calls:
                # Final response reached without further tool calls
                final_text = content or "No response generated."
                
                # Check if live data was queried to attach metadata badge
                metadata = {
                    "model": get_current_model(),
                    "tools_called": tools_called_log,
                    "has_live_data": has_live_data
                }

                ai_chat_storage.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=final_text,
                    metadata=metadata,
                    conn=conn
                )

                return {
                    "success": True,
                    "conversation_id": conversation_id,
                    "response": final_text,
                    "model": get_current_model(),
                    "tools_called": tools_called_log,
                    "has_live_data": has_live_data
                }

            # Assistant requested tool calls
            api_messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": tool_calls
            })

            # Record tool call in storage
            ai_chat_storage.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                tool_calls=tool_calls,
                conn=conn
            )

            # Execute each requested tool
            for tc in tool_calls:
                call_id = tc.get("id", "")
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                fn_args_raw = fn.get("arguments", "{}")
                tools_called_log.append(fn_name)

                try:
                    fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else (fn_args_raw or {})
                except Exception:
                    fn_args = {}

                # Execute tool safely via read-only data access layer
                tool_result = ai_data_access.execute_tool(fn_name, fn_args, conn=conn)

                # Check if result contains live data
                if isinstance(tool_result, dict):
                    res_val = tool_result.get("result", {})
                    if isinstance(res_val, dict) and (res_val.get("is_live") or res_val.get("is_live_snapshot")):
                        has_live_data = True

                result_json_str = json.dumps(tool_result, ensure_ascii=False)

                # Append tool result to API messages
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": fn_name,
                    "content": result_json_str
                })

                # Persist tool message in storage
                ai_chat_storage.add_message(
                    conversation_id=conversation_id,
                    role="tool",
                    content=result_json_str,
                    tool_call_id=call_id,
                    name=fn_name,
                    conn=conn
                )

        # If loop limit reached, do one final call without tools to summarize
        final_resp = _call_groq_api(messages=api_messages, tools=None)
        final_text = final_resp.get("choices", [{}])[0].get("message", {}).get("content", "Analysis complete.")
        
        metadata = {
            "model": get_current_model(),
            "tools_called": tools_called_log,
            "has_live_data": has_live_data
        }
        ai_chat_storage.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_text,
            metadata=metadata,
            conn=conn
        )
        return {
            "success": True,
            "conversation_id": conversation_id,
            "response": final_text,
            "model": get_current_model(),
            "tools_called": tools_called_log,
            "has_live_data": has_live_data
        }

    except Exception as e:
        error_msg = f"❌ **Error from AI Assistant**: {str(e)}"
        ai_chat_storage.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=error_msg,
            metadata={"error": str(e)},
            conn=conn
        )
        return {
            "success": False,
            "conversation_id": conversation_id,
            "error": str(e),
            "response": error_msg,
            "tools_called": tools_called_log
        }
