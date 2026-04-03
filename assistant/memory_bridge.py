import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from config import conf
from memory_system import ArchivalMemory, Memory, RecallMemory


_NAME_RE = re.compile(r"\bmy name is\s+([A-Za-z]+)", re.IGNORECASE)
_CALL_ME_RE = re.compile(r"\bcall me\s+([A-Za-z]+)\b", re.IGNORECASE)
_LOVE_RE = re.compile(r"\b(i love|i like|my favou?rite)\s+([^,.!?\n]{3,50})", re.IGNORECASE)
_DONT_LIKE_RE = re.compile(r"\bi don'?t like\s+([^,.!?\n]{3,40})", re.IGNORECASE)
_HAVE_RE = re.compile(r"\bi have (?:a |an )?([A-Za-z]+(?: [A-Za-z]+)?)\b", re.IGNORECASE)
_FAMILY_RE = re.compile(r"\bmy (mom|mother|dad|father|sister|brother|grandma|grandpa)\s+(?:is\s+)?([^,.!?\n]{2,40})", re.IGNORECASE)
_AGE_RE = re.compile(r"\bI'?m\s+(\d{1,2})\s*years?\s*old\b", re.IGNORECASE)
_BULLY_RE = re.compile(r"\b(people|they|someone)\s+(bully|bullies|bullied|bullying)\s+me\b|\bbullied\b", re.IGNORECASE)
_EMOTION_RE = re.compile(r"\b(i am|i'm|i feel|im)\s+(sad|upset|angry|hurt|scared|afraid|worried)\b", re.IGNORECASE)

_REMEMBER_QUERY_RE = re.compile(
    r"what do you remember|what'?s? my name|do you remember me|remember about me|"
    r"what do you know about me|tell me what you know",
    re.IGNORECASE,
)


def expand_query_for_rag(query: str) -> str:
    if _REMEMBER_QUERY_RE.search(query):
        return query + " child name interests likes pets family"
    return query


class PipelineMemoryBridge:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
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

        self.session_id = datetime.now().strftime("%Y-%m-%d-%H%M")
        self.session_history: deque[Dict[str, str]] = deque(maxlen=8)

    def _append_fact(self, entry: str) -> None:
        block = self.core_mem.get_block("human")
        if not block or entry in block.value:
            return
        success, _ = block.append(f"\n{entry}")
        if success:
            self.core_mem.save()

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
        for message in list(self.session_history)[-getattr(conf, "RAG_LAST_N_TURNS", 4):]:
            lines.append(f"  {message['role']}: {message['content'][:120]}")
        return "\n".join(lines)

    def prepare_messages(self, user_text: str) -> List[Dict[str, str]]:
        self.auto_extract_facts(user_text)
        self.session_history.append({"role": "user", "content": user_text})

        context_messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.core_mem.compile()},
        ]

        rag_context = self._retrieve_relevant_context(user_text)
        if rag_context.strip():
            context_messages.append({"role": "system", "content": rag_context})

        last_turns = self._format_last_turns()
        if last_turns:
            context_messages.append({"role": "system", "content": last_turns})

        self.recall_mem.insert("user", user_text, defer_embedding=True, session_id=self.session_id)
        return context_messages

    def remember_assistant(self, assistant_text: str) -> None:
        assistant_text = assistant_text.strip()
        if not assistant_text:
            return

        self.recall_mem.insert("assistant", assistant_text, session_id=self.session_id)
        self.session_history.append({"role": "assistant", "content": assistant_text})
