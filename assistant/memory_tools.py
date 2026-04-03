"""
Jhony (Zhanibek) Memory Tools
Simplified for toddler SLA (Second Language Acquisition) and 1-2B LLMs.

send_message is intentionally NOT included here — it lives in communication_tools.py
so that the tool-routing logic in jhony_enhanced.py stays clean.
"""
from typing import Dict, List, Any
from datetime import datetime
from memory_system import Memory, RecallMemory, ArchivalMemory
from base_executor import BaseToolExecutor
from config import conf


def get_memory_tools() -> List[Dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "save_child_info",
                "description": (
                    "Save NEW information about the child (interests, name, family members) "
                    "to memory. Use this the first time you learn something about the child."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "e.g. 'Child loves blue trucks' or 'Has a cat named Barsik'"
                        }
                    },
                    "required": ["content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_child_info",
                "description": (
                    "Correct or update previously saved information about the child. "
                    "Use this when something has changed or was wrong before."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "old_content": {
                            "type": "string",
                            "description": "The exact text currently stored that needs to be changed"
                        },
                        "new_content": {
                            "type": "string",
                            "description": "The corrected or updated text to replace it with"
                        }
                    },
                    "required": ["old_content", "new_content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "record_learned_word",
                "description": (
                    "Save a Russian word the child successfully identified or repeated. "
                    "Call this after the child shows they understood a word."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "russian_word": {
                            "type": "string",
                            "description": "The Russian word in Cyrillic, e.g. 'яблоко'"
                        },
                        "english_word": {
                            "type": "string",
                            "description": "The English translation, e.g. 'apple'"
                        }
                    },
                    "required": ["russian_word", "english_word"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "consult_russian_teacher_manual",
                "description": (
                    "Search stored Russian vocabulary and grammar rules. "
                    "Use this when you need a hint about a word or grammar rule."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The Russian word or grammar concept to look up."
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]


class MemoryToolExecutor(BaseToolExecutor):
    """Executor for Jhony's educational memory tools."""

    def __init__(self, memory: Memory, recall: RecallMemory, archival: ArchivalMemory):
        self.memory = memory
        self.recall = recall
        self.archival = archival

    # --- Jhony-specific tools ---

    def _save_child_info(self, args: Dict) -> str:
        """Append new info about the child to the human block."""
        content = args.get("content", "").strip()
        if not content:
            return "Error: no content provided."
        block = self.memory.get_block("human")
        if not block:
            return "Error: human block not found."
        if content in block.value:
            return f"Already saved: {content}"
        success, msg = block.append("\n" + content)
        if success:
            self.memory.save()
            return f"Saved: {content}"
        return f"Failed to save: {msg}"

    def _update_child_info(self, args: Dict) -> str:
        """Replace outdated info in the human block. Uses key-based update when applicable."""
        old = args.get("old_content", "").strip()
        new = args.get("new_content", "").strip()
        if not old or not new:
            return "Error: both old_content and new_content are required."
        block = self.memory.get_block("human")
        if not block:
            return "Error: human block not found."
        # Key-based replace only for single-line key "Child's name:" (no exact substring needed)
        if old.startswith("Child's name:") and new.startswith("Child's name:"):
            success, msg = block.replace_line_by_key("Child's name:", new)
            if success:
                self.memory.save()
                return "Updated child info."
            return f"Update failed: {msg}"
        success, msg = block.replace(old, new)
        if success:
            self.memory.save()
            return "Updated child info."
        return f"Update failed: {msg}"

    def _record_learned_word(self, args: Dict) -> str:
        """
        Record a newly learned word in two places:
          1. Archival memory — full searchable history
          2. learned_words core block — immediately visible to the LLM in context
        """
        russian = args.get("russian_word", "").strip()
        english = args.get("english_word", "").strip()
        if not russian or not english:
            return "Error: russian_word and english_word are required."

        entry = f"{russian} ({english})"

        # 1. Full record in archival for semantic search history
        if self.archival:
            self.archival.insert("vocabulary", entry, importance=9)

        # 2. Compact entry in core memory with line cap: drop oldest when over limit
        learned_block = self.memory.get_block("learned_words")
        if learned_block:
            max_lines = getattr(conf, "LEARNED_WORDS_MAX_LINES", 80)
            lines = [ln.strip() for ln in learned_block.value.splitlines() if ln.strip()]
            if entry not in lines:
                lines.append(entry)
            if len(lines) > max_lines:
                lines = lines[-max_lines:]
            new_value = "\n".join(lines)
            if len(new_value) <= learned_block.limit:
                learned_block.value = new_value
                learned_block.metadata["last_modified"] = datetime.now().isoformat()
            else:
                learned_block.append(f"\n{entry}" if learned_block.value else entry)
            self.memory.save()

        return f"Recorded: {entry}"

    def _consult_russian_teacher_manual(self, args: Dict) -> str:
        """Search archival memory for Russian vocabulary and grammar hints."""
        query = args.get("query", "").strip()
        if not query:
            return "Error: query is required."
        if not self.archival:
            return "Error: archival memory not available."
        results = self.archival.search(query, limit=3)
        if not results:
            return f"No entries found for: '{query}'"
        lines = [f"- {r['content']}" for r in results]
        return "Teacher Manual:\n" + "\n".join(lines)

    # --- Standard memory tools (used by tests and generic tooling) ---

    def _core_memory_append(self, args: Dict) -> str:
        label = args.get("label")
        content = args.get("content", "")
        block = self.memory.get_block(label)
        if not block:
            return f"Memory block '{label}' not found."
        success, message = block.append("\n" + content)
        if success:
            self.memory.save()
            return f"Success: appended to {label} ({block.chars_current}/{block.limit} chars)"
        return f"Failed: {message}"

    def _core_memory_replace(self, args: Dict) -> str:
        label = args.get("label")
        old_content = args.get("old_content")
        new_content = args.get("new_content")
        block = self.memory.get_block(label)
        if not block:
            return f"Memory block '{label}' not found."
        success, message = block.replace(old_content, new_content)
        if success:
            self.memory.save()
            return f"Success: replaced content in {label} ({block.chars_current}/{block.limit} chars)"
        return f"Failed: {message}"

    def _archival_memory_insert(self, args: Dict) -> str:
        category = args.get("category")
        content = args.get("content")
        importance = args.get("importance", 5)
        if not self.archival:
            return "Archival memory not available."
        self.archival.insert(category, content, importance)
        return f"Saved to archival [{category}] (importance: {importance}/10)"

    def _archival_memory_search(self, args: Dict) -> str:
        query = args.get("query")
        limit = args.get("limit", 5)
        if not self.archival:
            return "Archival memory not available."
        results = self.archival.search(query, limit)
        if not results:
            return f"No archival memories found for: '{query}'"
        lines = [
            f"{i}. [{r['category']}] {r['content'][:200]}"
            for i, r in enumerate(results, 1)
        ]
        return f"Found {len(results)} results:\n" + "\n".join(lines)

    def _recall_memory_search(self, args: Dict) -> str:
        query = args.get("query")
        limit = args.get("limit", 10)
        if not self.recall:
            return "Recall memory not available."
        results = self.recall.search(query, limit)
        if not results:
            return "No recall memories found."
        lines = [
            f"{i}. [{r['role']}] {r['content'][:150]}"
            for i, r in enumerate(results, 1)
        ]
        return f"Found {len(results)} results:\n" + "\n".join(lines)

    def get_tool_schemas(self) -> List[Dict]:
        """Return tool schemas for 1-2B models (memory tools only, no send_message)."""
        return get_memory_tools()
