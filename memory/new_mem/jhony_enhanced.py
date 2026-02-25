"""
Jhony (Zhanibek) v2.0 - Russian Teacher for Toddlers
MemGPT Architecture: inner monologue + two-phase tool loop
Optimized for 1-2B models (qwen2.5:1.5b) on Jetson Orin Nano.

Architecture overview
─────────────────────
Every turn:
  1. auto_extract_facts()   — rule-based regex saves obvious facts the model misses
  2. Tool loop (≤3 iters)   — tool_choice="auto", ALL tools offered at once
                              if model calls memory tools → execute, nudge, loop
                              if model calls send_message → speak, done
                              if model returns text → use it directly
  3. Emergency fallback      — bare text completion with explicit Russian prompt
                              fires only when the loop produces nothing

Session history stores ONLY:
  • user: raw child input (no RAG context, no injected text)
  • assistant: spoken message (no tool call scaffolding)

This keeps history clean, prevents confabulation, and fits within 1.5B token budget.
"""
import json
import re
import time
from collections import deque
from datetime import datetime
from config import conf

from memory_system import Memory, RecallMemory, ArchivalMemory
from memory_tools import MemoryToolExecutor
from personality_system import PersonalityEngine
from context_manager import ContextManager, InteractionContext
from communication_tools import CommunicationExecutor, get_communication_tools
from openai import OpenAI

print(f"🚀 Initializing Jhony's Brain with {conf.OLLAMA_MODEL}...")
client = OpenAI(base_url=f"{conf.OLLAMA_BASE_URL}/v1", api_key="ollama")
MODEL_NAME = conf.OLLAMA_MODEL

core_mem    = Memory()
recall_mem  = RecallMemory(use_semantic=conf.USE_SEMANTIC_SEARCH)
archival_mem = ArchivalMemory(use_semantic=conf.USE_SEMANTIC_SEARCH)
mem_exec    = MemoryToolExecutor(core_mem, recall_mem, archival_mem)
comm_exec   = CommunicationExecutor()
personality = PersonalityEngine.load()
ctx_mgr     = ContextManager()



# ---------------------------------------------------------------------------
# Rule-based auto extraction (runs on every user turn)
# Catches facts the model reliably misses at 1-2B parameter scale.
# ---------------------------------------------------------------------------

_NAME_RE   = re.compile(r'\bmy name is\s+([A-Za-z]+)', re.IGNORECASE)
_LOVE_RE   = re.compile(r'\b(i love|i like|my favou?rite)\s+([^,.!?\n]{3,50})', re.IGNORECASE)
_HAVE_RE   = re.compile(r'\bi have (?:a |an )?([A-Za-z]+(?: [A-Za-z]+)?)\b', re.IGNORECASE)


def auto_extract_facts(user_input: str) -> None:
    """
    Extract personal facts from user input using simple regex patterns.
    Writes directly to the human core-memory block.
    This is the fallback for when the model doesn't call save_child_info.
    """
    block = core_mem.get_block("human")
    if not block:
        return

    facts = []

    m = _NAME_RE.search(user_input)
    if m:
        name = m.group(1).capitalize()
        # Avoid saving common words accidentally matched as names
        if name.lower() not in {"a", "an", "the", "my", "your", "not"}:
            # Overwrite if we previously had "unknown"
            if "unknown" in block.value and name not in block.value:
                facts.append(("replace", "Child's name: unknown.", f"Child's name: {name}."))
            elif name not in block.value:
                facts.append(("append", f"Child's name: {name}."))

    for m in _LOVE_RE.finditer(user_input):
        interest = m.group(2).strip().rstrip(".,!?")
        entry = f"Child likes: {interest}."
        if entry not in block.value:
            facts.append(("append", entry))

    m = _HAVE_RE.search(user_input)
    if m:
        thing = m.group(1)
        entry = f"Child has: {thing}."
        if entry not in block.value:
            facts.append(("append", entry))

    changed = False
    for fact in facts:
        if fact[0] == "replace":
            success, _ = block.replace(fact[1], fact[2])
        else:
            success, _ = block.append(f"\n{fact[1]}")
        if success:
            changed = True
            print(f"   📝 [auto-saved: {fact[-1]}]")

    if changed:
        core_mem.save()


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------

def retrieve_relevant_context(query: str) -> str:
    hits  = recall_mem.search(query, limit=3)
    facts = archival_mem.search(query, limit=3)
    if not hits and not facts:
        return ""
    parts = ["[RECENT CONTEXT]"]
    for h in hits:
        parts.append(f"  {h['role']}: {h['content'][:100]}")
    if facts:
        parts.append("[KNOWN FACTS]")
        for f in facts:
            parts.append(f"  - {f['content'][:100]}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# System prompt  (MemGPT inner-monologue pattern)
# ---------------------------------------------------------------------------

def get_system_prompt() -> str:
    return f"""You are Jhony (Zhanibek), a warm Russian teacher for a young child.

RULE 1 — RUSSIAN ONLY (most important):
  send_message MUST be in Russian. Never English. Never Chinese.
  GOOD: "Привет! Как дела?" BAD: "Hello!" BAD: "你好"

RULE 2 — send_message IS YOUR ONLY VOICE:
  The child cannot see your text. Call send_message every turn — short (3-8 words).

RULE 3 — SAVE WHAT YOU LEARN:
  Child shares name or interests? → call save_child_info first.
  NEVER invent facts. Only what is in <human> is real.

{core_mem.compile()}"""


# ---------------------------------------------------------------------------
# Text-tool-call fallback parser
# ---------------------------------------------------------------------------

_KNOWN_TOOLS = {
    "send_message", "save_child_info", "update_child_info",
    "record_learned_word", "consult_russian_teacher_manual",
}
_JSON_RE = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', re.DOTALL)


def parse_text_tool_calls(content: str) -> list:
    """
    Fallback for models that emit tool calls as plain text instead of structured API calls.
    Handles:
      Style A: {"name": "send_message", "arguments": {"message": "..."}}
      Style B: Send_message\n{"message": "..."}   ← what qwen2.5 actually outputs
      Style C: {"function": "send_message", "parameters": {...}}
    """
    results = []

    # Style A & C: JSON object containing the tool name
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

    # Style B: ToolName on its own line, followed by bare args JSON
    lines = content.strip().splitlines()
    for i, line in enumerate(lines):
        candidate = line.strip().lower().replace("-", "_").rstrip(":")
        if candidate in _KNOWN_TOOLS:
            remaining = "\n".join(lines[i + 1:])
            for match in _JSON_RE.finditer(remaining):
                try:
                    args = json.loads(match.group())
                    if isinstance(args, dict):
                        results.append({"name": candidate, "arguments": args})
                        break
                except json.JSONDecodeError:
                    continue

    return results


# ---------------------------------------------------------------------------
# Summarizer (for memory compression)
# ---------------------------------------------------------------------------

def summarize_for_archival(text: str) -> str:
    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content":
                 "Summarize in 2–3 sentences: Russian words introduced, child's reactions, "
                 "any personal details mentioned."},
                {"role": "user", "content": text[:2000]}
            ],
            max_tokens=120
        )
        return resp.choices[0].message.content or text[:300]
    except Exception:
        return text[:300]


# ---------------------------------------------------------------------------
# Chat session
# Stores ONLY clean user messages + final spoken assistant messages.
# Tool call scaffolding is kept in working_messages (per-turn local variable)
# and never persisted to session, keeping history lean and API-spec compliant.
# ---------------------------------------------------------------------------

class ChatSession:
    def __init__(self):
        # 8 slots = ~4 turns (user + assistant each) — fits 1.5B context budget
        self.history: deque = deque(maxlen=8)

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def get_messages(self, rag_context: str = "") -> list:
        """
        Build the full message list for an API call.
        RAG context is injected as a second system message — NOT glued to the
        user message — so it never pollutes session history.
        """
        msgs = [{"role": "system", "content": get_system_prompt()}]
        if rag_context.strip():
            msgs.append({"role": "system", "content": rag_context})
        msgs.extend(list(self.history))
        return msgs


session = ChatSession()


# ---------------------------------------------------------------------------
# Performance timer
# ---------------------------------------------------------------------------

class PerformanceTimer:
    def __init__(self):
        self.start_time = 0.0
        self.end_time   = 0.0

    def start(self): self.start_time = time.perf_counter()
    def stop(self):  self.end_time   = time.perf_counter()

    def report(self):
        if self.start_time and self.end_time:
            print(f"   [⏱️  {self.end_time - self.start_time:.2f}s]")


# ---------------------------------------------------------------------------
# Main chat function — single MemGPT-style tool loop with emergency fallback
# ---------------------------------------------------------------------------

def _extract_text(content: str) -> str:
    """Strip <think> blocks and return clean text content."""
    return re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()


def chat(user_input: str) -> None:
    timer = PerformanceTimer()
    timer.start()

    # Compress recall memory if needed
    if recall_mem.get_count() > conf.RECALL_MEMORY_LIMIT:
        keep = max(10, conf.RECALL_MEMORY_LIMIT - 15)
        n = recall_mem.compress_old_memories(summarize_for_archival, archival_mem, keep_recent=keep)
        if n > 0:
            print(f"🗜️  Compressed {n} old memories into archival.")

    # ── Rule-based fact extraction (no extra API call) ─────────────────────
    auto_extract_facts(user_input)

    # ── Store in recall and session ────────────────────────────────────────
    ctx_mgr.update_interaction(InteractionContext(last_interaction=datetime.now()))
    recall_mem.insert("user", user_input, defer_embedding=True)
    session.add("user", user_input)

    # ── Build per-turn working message chain ──────────────────────────────
    rag_context      = retrieve_relevant_context(user_input)
    working_messages = session.get_messages(rag_context=rag_context)

    # All tools in one list — model decides what to call
    all_tools    = mem_exec.get_tool_schemas() + get_communication_tools()
    spoken_message = None

    # ── Tool loop (max 3 iterations) ──────────────────────────────────────
    # Each iteration: the model either speaks (→ done) or calls memory tools
    # (→ execute and loop). A nudge is added on iteration 1 if still no speech.
    for iteration in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=working_messages,
                tools=all_tools,
                tool_choice="auto",
                max_tokens=150,
            )
        except Exception as e:
            print(f"❌ API error (iter {iteration}): {e}")
            break

        msg        = resp.choices[0].message
        raw_text   = msg.content or ""
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            # Model responded with plain text (inner thought or direct speech)
            clean = _extract_text(raw_text)
            if clean:
                # Try to parse a text-encoded tool call first
                parsed = parse_text_tool_calls(clean)
                for tc in parsed:
                    if tc["name"] == "send_message":
                        spoken_message = tc["arguments"].get("message", "")
                        break
                    else:
                        mem_exec.execute(tc["name"], tc["arguments"])
                # Use raw text as message if no send_message found in it
                if not spoken_message and not any(t["name"] == "send_message" for t in parsed):
                    # Don't use pure JSON blobs as messages
                    if not clean.startswith("{"):
                        spoken_message = clean
            break  # No tool calls → end loop regardless

        # ── Execute each tool call ────────────────────────────────────────
        working_messages.append({
            "role": "assistant",
            "content": raw_text,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if tc.function.name == "send_message":
                comm_exec.execute("send_message", args)
                msg_text = comm_exec.get_last_message()
                # Pydantic may reject empty args; fall back to raw argument values
                if not msg_text:
                    msg_text = next((v for v in args.values() if isinstance(v, str) and v.strip()), None)
                if msg_text:
                    spoken_message = msg_text
                result = "Message delivered."
            else:
                result = mem_exec.execute(tc.function.name, args)

            working_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": str(result),
            })

        if spoken_message:
            break

        # Model called only memory tools — nudge it to speak on next iteration
        if iteration == 1:
            working_messages.append({
                "role": "system",
                "content": "Хорошо. Теперь вызови send_message и ответь ребёнку по-русски (3-6 слов).",
            })

    # ── Emergency fallback: bare text completion ───────────────────────────
    # Fires only when the loop produced nothing — rare, but covers model confusion.
    if not spoken_message:
        try:
            emer = client.chat.completions.create(
                model=MODEL_NAME,
                messages=working_messages + [{
                    "role": "user",
                    "content": "Ответь по-русски коротко (3-6 слов).",
                }],
                max_tokens=60,
            )
            raw = _extract_text(emer.choices[0].message.content or "")
            if raw and not raw.startswith("{"):
                spoken_message = raw
        except Exception as e:
            print(f"❌ Emergency fallback error: {e}")

    # ── Deliver and store ──────────────────────────────────────────────────
    if spoken_message:
        # If somehow a JSON blob slipped through, try to unwrap send_message from it
        if spoken_message.strip().startswith("{"):
            parsed = parse_text_tool_calls(spoken_message)
            for tc in parsed:
                if tc["name"] == "send_message":
                    spoken_message = tc["arguments"].get("message", spoken_message)
                    break

        print(f"\n🇷🇺 Jhony: {spoken_message}")
        recall_mem.insert("assistant", spoken_message)
        session.add("assistant", spoken_message)
    else:
        print("⚠️  Jhony produced no spoken output this turn.")

    timer.stop()
    timer.report()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"🎓 Jhony (Zhanibek) Online — Ready to teach Russian!")
    print(f"   Model    : {MODEL_NAME}")
    print(f"   Recall   : {recall_mem.get_count()} messages stored")
    print(f"   Archival : {archival_mem.get_count()} facts stored")
    learned = core_mem.get_block("learned_words")
    if learned and learned.value.strip():
        n = len([w for w in learned.value.strip().splitlines() if w.strip()])
        print(f"   Learned  : {n} Russian words")
    human = core_mem.get_block("human")
    if human:
        print(f"   Child    : {human.value.strip()}")
    print()

    while True:
        try:
            u = input("Child: ").strip()
            if not u:
                continue
            if u.lower() in ["exit", "quit"]:
                print("👋 Goodbye!")
                core_mem.save()
                break
            chat(u)
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            core_mem.save()
            break


if __name__ == "__main__":
    main()
