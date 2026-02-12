"""
Jhony (Zhanibek) Memory Tools
Simplified for toddler SLA (Second Language Acquisition) and 1-2B LLMs.
"""
from typing import Dict, List, Any
from memory_system import Memory, RecallMemory, ArchivalMemory
from base_executor import BaseToolExecutor

def get_memory_tools() -> List[Dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "save_child_info",
                "description": "Save important info about the child (interests, name, family) to persona memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "enum": ["human"]},
                        "content": {"type": "string", "description": "e.g., 'Child loves blue trucks' or 'Has a cat named Barsik'"}
                    },
                    "required": ["label", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "record_learned_word",
                "description": "Save a Russian word the child successfully identified or learned.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": ["vocabulary", "grammar"]},
                        "content": {"type": "string", "description": "The word and context, e.g., 'Yabloko (Apple) - Level 1 success'"}
                    },
                    "required": ["category", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "consult_russian_teacher_manual",
                "description": "Search the Russian RAG database for hints, translations, or simple grammar rules.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The Russian word or concept to look up."},
                        "limit": {"type": "integer", "default": 1}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "send_message",
                "description": "Speak to the child in simple Russian.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "The Russian sentence to say."}
                    },
                    "required": ["message"]
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

    def _save_child_info(self, args):
        """Modified core_memory_append for child interests."""
        block = self.memory.get_block(args['label'])
        if not block: return "Block not found"
        success, msg = block.append("\n" + args['content'])
        if success: self.memory.save()
        return f"Saved interest: {msg}"

    def _record_learned_word(self, args):
        """Modified archival_insert for tracking progress."""
        # Set importance high for newly learned words to keep them in context
        self.archival.insert(args['category'], args['content'], importance=9)
        return "Word progress recorded in long-term memory."

    def _consult_russian_teacher_manual(self, args):
        """RAG lookup for Russian vocabulary and grammar."""
        res = self.archival.search(args.get('query'), args.get('limit', 1))
        return f"Teacher Manual Results: {res}"

    def get_tool_schemas(self) -> List[Dict]:
        """Return simplified schemas for 1-2B models."""
        return get_memory_tools()