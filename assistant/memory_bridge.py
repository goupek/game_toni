import json
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from communication_tools import CommunicationExecutor, get_communication_tools
from config import conf
from context_manager import ContextManager, InteractionContext
from memory_system import (
    ArchivalMemory,
    Memory,
    RecallMemory,
    export_memory_backup,
    memory_health_report,
)
from memory_tools import MemoryToolExecutor
from personality_system import PersonalityEngine


_NAME_RE = re.compile(r"\bmy name is\s+([A-Za-z]+)", re.IGNORECASE)
_CALL_ME_RE = re.compile(r"\bcall me\s+([A-Za-z]+)\b", re.IGNORECASE)
_LOVE_RE = re.compile(r"\b(i love|i like|my favou?rite)\s+([^,.!?\n]{3,50})", re.IGNORECASE)
_DONT_LIKE_RE = re.compile(r"\bi don'?t like\s+([^,.!?\n]{3,40})", re.IGNORECASE)
_HAVE_RE = re.compile(r"\bi have (?:a |an )?([A-Za-z]+(?: [A-Za-z]+)?)\b", re.IGNORECASE)
_FAMILY_RE = re.compile(
    r"\bmy (mom|mother|dad|father|sister|brother|grandma|grandpa)\s+(?:is\s+)?([^,.!?\n]{2,40})",
    re.IGNORECASE,
)
_AGE_RE = re.compile(r"\bI'?m\s+(\d{1,2})\s*years?\s*old\b", re.IGNORECASE)
_BULLY_RE = re.compile(r"\b(people|they|someone)\s+(bully|bullies|bullied|bullying)\s+me\b|\bbullied\b", re.IGNORECASE)
_EMOTION_RE = re.compile(
    r"\b(i am|i'm|i feel|im)\s+(sad|upset|angry|hurt|scared|afraid|worried)\b",
    re.IGNORECASE,
)

_REMEMBER_QUERY_RE = re.compile(
    r"what do you remember|what'?s? my name|do you remember me|remember about me|"
    r"what do you know about me|tell me what you know",
    re.IGNORECASE,
)

_KNOWN_TOOLS = {
    "send_message",
    "save_child_info",
    "update_child_info",
    "record_learned_word",
    "consult_russian_teacher_manual",
}
_JSON_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def expand_query_for_rag(query: str) -> str:
    if _REMEMBER_QUERY_RE.search(query):
        return query + " child name interests likes pets family"
    return query


def parse_text_tool_calls(content: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for match in _JSON_RE.finditer(content):
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            continue
        name = data.get("name") or data.get("function")
        args = data.get("arguments") or data.get("parameters") or data.get("args") or {}
        if isinstance(name, str) and name.lower() in _KNOWN_TOOLS and isinstance(args, dict):
            results.append({"name": name.lower(), "arguments": args})

    if results:
        return results

    lines = content.strip().splitlines()
    for index, line in enumerate(lines):
        candidate = line.strip().lower().replace("-", "_").rstrip(":")
        if candidate not in _KNOWN_TOOLS:
            continue
        remaining = "\n".join(lines[index + 1 :])
        for match in _JSON_RE.finditer(remaining):
            try:
                args = json.loads(match.group())
            except json.JSONDecodeError:
                continue
            if isinstance(args, dict):
                results.append({"name": candidate, "arguments": args})
                break

    return results


def _extract_text(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()


class PipelineMemoryBridge:
    def __init__(
        self,
        base_dir: Path,
        base_system_prompt: str,
        response_temperature: float = 0.5,
        response_max_tokens: int = 80,
        summary_max_tokens: int = 120,
        model_name: Optional[str] = None,
        completion_transport: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.base_dir = Path(base_dir)
        self.base_system_prompt = base_system_prompt.strip()
        self.response_temperature = response_temperature
        self.response_max_tokens = response_max_tokens
        self.summary_max_tokens = summary_max_tokens
        self.tool_max_tokens = max(160, response_max_tokens * 2)
        self.fallback_max_tokens = max(60, response_max_tokens)
        self._completion_transport = completion_transport

        conf.FAISS_INDEX_PATH = str(self.base_dir / "walle_faiss.index")

        self.core_mem = Memory(db_path=str(self.base_dir / "walle_core_memory.db"))
        self.recall_mem = RecallMemory(
            db_path=str(self.base_dir / "walle_recall_memory.db"),
            use_semantic=conf.USE_SEMANTIC_SEARCH,
        )
        self.archival_mem = ArchivalMemory(
            db_path=str(self.base_dir / "walle_archival_memory.db"),
            use_semantic=conf.USE_SEMANTIC_SEARCH,
        )

        self.mem_exec = MemoryToolExecutor(self.core_mem, self.recall_mem, self.archival_mem)
        self.comm_exec = CommunicationExecutor()
        self.personality = PersonalityEngine.load()
        self.ctx_mgr = ContextManager()

        self.session_id = datetime.now().strftime("%Y-%m-%d-%H%M")
        self.session_history: deque[Dict[str, str]] = deque(maxlen=8)

        self.model_name = model_name or self._resolve_model()
        self.prefer_text_tool_calls = conf.should_use_text_tool_calls(self.model_name)
        self.tools_supported = True

    def _resolve_model(self) -> str:
        try:
            return conf.resolve_model()
        except Exception:
            requested = (conf.LLAMA_CPP_MODEL or "").strip()
            if requested and requested.lower() not in {"auto", "default"}:
                return requested
            return conf.LLAMA_CPP_FALLBACK_MODEL

    def get_health_report(self) -> Dict[str, Any]:
        return memory_health_report(self.core_mem, self.recall_mem, self.archival_mem)

    def export_backup(self, filepath: str, recall_limit: int = 100, archival_limit: int = 500) -> None:
        export_memory_backup(
            self.core_mem,
            self.recall_mem,
            self.archival_mem,
            filepath,
            recall_limit=recall_limit,
            archival_limit=archival_limit,
        )

    def auto_extract_facts(self, user_input: str) -> None:
        block = self.core_mem.get_block("human")
        if not block:
            return

        changed = False

        def update_name(name: str) -> None:
            nonlocal changed
            if name.lower() in {"a", "an", "the", "my", "your", "not"}:
                return
            if name in block.value:
                return
            success, _ = block.replace_line_by_key("Child's name:", f"Child's name: {name}.")
            if success:
                changed = True

        name_match = _NAME_RE.search(user_input)
        if name_match:
            update_name(name_match.group(1).capitalize())

        call_me_match = _CALL_ME_RE.search(user_input)
        if call_me_match:
            update_name(call_me_match.group(1).capitalize())

        for match in _LOVE_RE.finditer(user_input):
            entry = f"Child likes: {match.group(2).strip().rstrip('.,!?')}."
            if entry not in block.value:
                success, _ = block.append(f"\n{entry}")
                changed = changed or success

        for match in _DONT_LIKE_RE.finditer(user_input):
            entry = f"Child dislikes: {match.group(1).strip().rstrip('.,!?')}."
            if entry not in block.value:
                success, _ = block.append(f"\n{entry}")
                changed = changed or success

        have_match = _HAVE_RE.search(user_input)
        if have_match:
            entry = f"Child has: {have_match.group(1)}."
            if entry not in block.value:
                success, _ = block.append(f"\n{entry}")
                changed = changed or success

        for match in _FAMILY_RE.finditer(user_input):
            role = match.group(1).lower()
            desc = match.group(2).strip().rstrip(".,!?")
            entry = f"Child family: {role} - {desc}."
            if entry not in block.value:
                success, _ = block.append(f"\n{entry}")
                changed = changed or success

        age_match = _AGE_RE.search(user_input)
        if age_match:
            entry = f"Child age: {age_match.group(1)} years."
            if entry not in block.value:
                success, _ = block.append(f"\n{entry}")
                changed = changed or success

        if _BULLY_RE.search(user_input):
            entry = "Child feels: being bullied."
            if entry not in block.value:
                success, _ = block.append(f"\n{entry}")
                changed = changed or success

        emotion_match = _EMOTION_RE.search(user_input)
        if emotion_match:
            entry = f"Child feels: {emotion_match.group(2).strip().lower()}."
            if entry not in block.value:
                success, _ = block.append(f"\n{entry}")
                changed = changed or success

        if changed:
            self.core_mem.save()

    def _retrieve_relevant_context(self, query: str) -> str:
        expanded = expand_query_for_rag(query)
        hits = self.recall_mem.search(expanded, limit=getattr(conf, "RAG_RECALL_K", 3))
        facts = self.archival_mem.search(expanded, limit=getattr(conf, "RAG_ARCHIVAL_K", 3))

        if not hits and not facts:
            return ""

        parts = ["[RECENT CONTEXT]"]
        for hit in hits:
            parts.append(f"  {hit['role']}: {hit['content'][:100]}")

        if facts:
            parts.append("[KNOWN FACTS]")
            for fact in facts:
                parts.append(f"  - {fact['content'][:100]}")

        return "\n".join(parts)

    def _format_last_turns(self) -> str:
        if not self.session_history:
            return ""

        lines = ["[LAST DIALOGUE]"]
        for message in list(self.session_history)[-getattr(conf, "RAG_LAST_N_TURNS", 4) :]:
            lines.append(f"  {message['role']}: {message['content'][:120]}")
        return "\n".join(lines)

    def _build_system_prompt(self, context_hint: str = "") -> str:
        parts = [
            self.base_system_prompt,
            (
                "MEMORY RULES:\n"
                "- Only facts from the current user turn or the memory blocks are reliable.\n"
                "- When the child shares new personal facts, call save_child_info.\n"
                "- When a saved fact changes, call update_child_info.\n"
                "- When the child successfully learns a Russian word, call record_learned_word.\n"
                "- When you need grounded help from stored vocabulary or prior lessons, call consult_russian_teacher_manual.\n"
                "- Use send_message for the final spoken reply whenever tools are available.\n"
                "- Never invent memories or pretend to remember something that is not stored."
            ),
            self.personality.get_system_prompt_addition(),
        ]

        if context_hint.strip():
            parts.append(context_hint.strip())

        parts.append(self.core_mem.compile())
        return "\n\n".join(part for part in parts if part and part.strip())

    def _build_working_messages(self, user_input: str, context_hint: str = "") -> List[Dict[str, str]]:
        rag_context = self._retrieve_relevant_context(user_input)

        working_messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt(context_hint=context_hint)}
        ]

        if rag_context.strip():
            working_messages.append({"role": "system", "content": rag_context})

        last_turns = self._format_last_turns()
        if last_turns:
            working_messages.append({"role": "system", "content": last_turns})

        working_messages.extend(list(self.session_history))
        return working_messages

    def _compress_memory_if_needed(self) -> int:
        if self.recall_mem.get_count() <= conf.RECALL_MEMORY_LIMIT:
            return 0
        keep_recent = max(10, conf.RECALL_MEMORY_LIMIT - 15)
        return self.recall_mem.compress_old_memories(
            self.summarize_for_archival,
            self.archival_mem,
            keep_recent=keep_recent,
        )

    def summarize_for_archival(self, text: str) -> str:
        try:
            message = self._chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize in 2-3 sentences: Russian words introduced, "
                            "child reactions, and any personal details mentioned."
                        ),
                    },
                    {"role": "user", "content": text[:2000]},
                ],
                max_tokens=self.summary_max_tokens,
                temperature=0.2,
            )
        except Exception:
            return text[:300]

        summary = _extract_text(message.get("content", ""))
        return summary or text[:300]

    def _chat_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: Optional[float] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.response_temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        if self._completion_transport is not None:
            response_payload = self._completion_transport(payload)
        else:
            try:
                response = requests.post(
                    f"{conf.openai_base_url()}/chat/completions",
                    json=payload,
                    timeout=(
                        conf.LLAMA_CPP_TIMEOUT_SECONDS,
                        getattr(conf, "LLAMA_CPP_CHAT_TIMEOUT_SECONDS", 120),
                    ),
                )
                response.raise_for_status()
            except requests.exceptions.RequestException as exc:
                raise RuntimeError(
                    f"Failed to reach llama.cpp at {conf.http_base_url()}: {exc}"
                ) from exc
            response_payload = response.json()

        choices = response_payload.get("choices") or []
        if not choices:
            raise RuntimeError("llama.cpp returned no choices")

        message = choices[0].get("message") or {}
        return {
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
        }

    def _is_tools_unsupported_error(self, err: Exception) -> bool:
        msg = str(err).lower()
        return (
            ("does not support tools" in msg)
            or ("support tools" in msg and "does not" in msg)
            or ("tools param requires --jinja flag" in msg)
            or ("tool_choice param requires --jinja flag" in msg)
        )

    def _extract_spoken_message(self, args: Dict[str, Any]) -> Optional[str]:
        result = self.comm_exec.execute("send_message", args)
        message = self.comm_exec.get_last_message()
        if message:
            return message

        if result.startswith("Validation error"):
            for value in args.values():
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def _execute_tool(self, fn_name: str, args: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        if fn_name == "send_message":
            message = self._extract_spoken_message(args)
            if not message:
                return "Failed: send_message produced no message.", None
            return "Message delivered.", message

        return self.mem_exec.execute(fn_name, args), None

    def _toolless_system_nudge(self) -> str:
        return (
            "TOOLS ARE NOT AVAILABLE THROUGH THE API.\n"
            "You MUST write plain-text tool calls so the program can parse and execute them.\n"
            "Allowed format only:\n"
            "  save_child_info\n"
            "  {\"content\":\"...\"}\n"
            "  update_child_info\n"
            "  {\"old_content\":\"...\",\"new_content\":\"...\"}\n"
            "  record_learned_word\n"
            "  {\"russian_word\":\"...\",\"english_word\":\"...\"}\n"
            "  consult_russian_teacher_manual\n"
            "  {\"query\":\"...\"}\n"
            "  send_message\n"
            "  {\"message\":\"...\"}\n"
            "The final send_message is required. Its message must stay in Russian only and follow the tutor style rules."
        )

    def _run_text_tool_loop(self, working_messages: List[Dict[str, Any]]) -> Tuple[Optional[str], List[str]]:
        spoken_message: Optional[str] = None
        used_tools: List[str] = []

        for _ in range(3):
            message = self._chat_completion(
                messages=working_messages + [{"role": "system", "content": self._toolless_system_nudge()}],
                max_tokens=self.tool_max_tokens,
            )
            clean = _extract_text(message.get("content", ""))
            if not clean:
                continue

            parsed = parse_text_tool_calls(clean)
            if not parsed:
                if not clean.startswith("{"):
                    spoken_message = clean
                break

            working_messages.append({"role": "assistant", "content": clean})
            tool_feedback: List[str] = []

            for tool_call in parsed:
                fn_name = tool_call.get("name", "")
                args = tool_call.get("arguments") or {}
                result, maybe_message = self._execute_tool(fn_name, args)
                used_tools.append(fn_name)

                if fn_name != "send_message":
                    tool_feedback.append(f"{fn_name}: {result}")
                if maybe_message:
                    spoken_message = maybe_message

            for feedback in tool_feedback:
                working_messages.append({"role": "system", "content": f"TOOL RESULT {feedback}"})

            if spoken_message:
                break

            working_messages.append(
                {
                    "role": "system",
                    "content": (
                        "Memory actions are complete. Now output the final send_message tool call only, "
                        "with the reply in Russian."
                    ),
                }
            )

        return spoken_message, used_tools

    def _run_structured_tool_loop(self, working_messages: List[Dict[str, Any]]) -> Tuple[Optional[str], List[str]]:
        spoken_message: Optional[str] = None
        used_tools: List[str] = []
        all_tools = self.mem_exec.get_tool_schemas() + get_communication_tools()

        for iteration in range(3):
            try:
                message = self._chat_completion(
                    messages=working_messages,
                    max_tokens=self.tool_max_tokens,
                    tools=all_tools,
                    tool_choice="auto",
                )
            except Exception as exc:
                if self._is_tools_unsupported_error(exc):
                    self.tools_supported = False
                    return self._run_text_tool_loop(working_messages)
                raise

            raw_text = message.get("content", "")
            tool_calls = message.get("tool_calls") or []

            if not tool_calls:
                clean = _extract_text(raw_text)
                parsed_text_calls = parse_text_tool_calls(clean)

                if parsed_text_calls:
                    working_messages.append({"role": "assistant", "content": clean})
                    tool_feedback: List[str] = []
                    for tool_call in parsed_text_calls:
                        fn_name = tool_call.get("name", "")
                        args = tool_call.get("arguments") or {}
                        result, maybe_message = self._execute_tool(fn_name, args)
                        used_tools.append(fn_name)
                        if fn_name != "send_message":
                            tool_feedback.append(f"{fn_name}: {result}")
                        if maybe_message:
                            spoken_message = maybe_message

                    for feedback in tool_feedback:
                        working_messages.append({"role": "system", "content": f"TOOL RESULT {feedback}"})

                    if spoken_message:
                        break

                    working_messages.append(
                        {
                            "role": "system",
                            "content": "Memory actions are complete. Now call send_message with the final Russian reply.",
                        }
                    )
                    continue

                if clean and not clean.startswith("{"):
                    spoken_message = clean
                break

            assistant_message: Dict[str, Any] = {"role": "assistant", "content": raw_text}
            normalized_tool_calls = []

            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                normalized_tool_calls.append(
                    {
                        "id": tool_call.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": function.get("name", ""),
                            "arguments": function.get("arguments", "{}"),
                        },
                    }
                )

            assistant_message["tool_calls"] = normalized_tool_calls
            working_messages.append(assistant_message)

            for tool_call in normalized_tool_calls:
                function = tool_call.get("function") or {}
                fn_name = function.get("name", "")
                raw_args = function.get("arguments", "{}")
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args or "{}")
                    except json.JSONDecodeError:
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}

                result, maybe_message = self._execute_tool(fn_name, args)
                used_tools.append(fn_name)
                if maybe_message:
                    spoken_message = maybe_message

                working_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "name": fn_name,
                        "content": str(result),
                    }
                )

            if spoken_message:
                break

            if iteration == 1:
                working_messages.append(
                    {
                        "role": "system",
                        "content": "Memory has been updated. Now call send_message with the final Russian reply.",
                    }
                )

        return spoken_message, used_tools

    def _run_tool_loop(self, working_messages: List[Dict[str, Any]]) -> Tuple[Optional[str], List[str]]:
        if self.prefer_text_tool_calls or not self.tools_supported:
            return self._run_text_tool_loop(working_messages)
        return self._run_structured_tool_loop(working_messages)

    def _run_emergency_fallback(self, working_messages: List[Dict[str, Any]]) -> str:
        message = self._chat_completion(
            messages=working_messages
            + [
                {
                    "role": "user",
                    "content": (
                        "Reply to the child in Russian only, in the same warm tutor style. "
                        "Do not use tools in this answer."
                    ),
                }
            ],
            max_tokens=self.fallback_max_tokens,
            temperature=0.4,
        )
        clean = _extract_text(message.get("content", ""))
        parsed = parse_text_tool_calls(clean)
        for tool_call in parsed:
            if tool_call.get("name") == "send_message":
                return (tool_call.get("arguments") or {}).get("message", "").strip()

        if clean.startswith("{"):
            return ""
        return clean

    def generate_reply(self, user_input: str) -> str:
        compressed = self._compress_memory_if_needed()
        if compressed > 0:
            print(f"[Memory] Compressed {compressed} old recall entries into archival storage.")

        self.auto_extract_facts(user_input)

        context_hint = self.ctx_mgr.get_context_string()
        self.ctx_mgr.update_interaction(InteractionContext(last_interaction=datetime.now()))

        self.recall_mem.insert("user", user_input, defer_embedding=True, session_id=self.session_id)
        self.session_history.append({"role": "user", "content": user_input})

        working_messages = self._build_working_messages(user_input, context_hint=context_hint)
        spoken_message, used_tools = self._run_tool_loop(working_messages)

        if not spoken_message:
            spoken_message = self._run_emergency_fallback(working_messages)

        spoken_message = spoken_message.strip()
        if not spoken_message:
            return ""

        self.recall_mem.insert(
            "assistant",
            spoken_message,
            tools_used=used_tools or None,
            session_id=self.session_id,
        )
        self.session_history.append({"role": "assistant", "content": spoken_message})
        return spoken_message
