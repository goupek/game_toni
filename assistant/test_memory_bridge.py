import json
import sys
import tempfile
import unittest
from pathlib import Path


ASSISTANT_DIR = Path(__file__).resolve().parent
if str(ASSISTANT_DIR) not in sys.path:
    sys.path.insert(0, str(ASSISTANT_DIR))

from memory_bridge import PipelineMemoryBridge  # noqa: E402


class SequenceTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        if not self.responses:
            raise AssertionError("No mocked responses left for completion transport")
        return self.responses.pop(0)


def _message_response(content: str):
    return {"choices": [{"message": {"content": content}}]}


class PipelineMemoryBridgeTests(unittest.TestCase):
    def test_text_tool_loop_saves_child_info_and_reply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transport = SequenceTransport(
                [
                    _message_response(
                        'save_child_info\n{"content":"Child likes: trucks."}\n'
                        'send_message\n{"message":"Я запомнила, что тебе нравятся грузовики."}'
                    )
                ]
            )

            bridge = PipelineMemoryBridge(
                Path(tmpdir),
                base_system_prompt="You are Boxy.",
                model_name="ggml-org/gemma-3-1b-it-GGUF",
                completion_transport=transport,
            )

            reply = bridge.generate_reply("I like trucks")

            self.assertEqual(reply, "Я запомнила, что тебе нравятся грузовики.")
            self.assertIn("Child likes: trucks.", bridge.core_mem.get_block("human").value)
            self.assertEqual(bridge.recall_mem.get_count(), 2)
            self.assertEqual(len(transport.payloads), 1)

    def test_text_tool_loop_can_consult_memory_then_answer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transport = SequenceTransport(
                [
                    _message_response(
                        'consult_russian_teacher_manual\n{"query":"яблоко"}'
                    ),
                    _message_response(
                        'send_message\n{"message":"Это слово переводится как яблоко. Попробуй повторить."}'
                    ),
                ]
            )

            bridge = PipelineMemoryBridge(
                Path(tmpdir),
                base_system_prompt="You are Boxy.",
                model_name="ggml-org/gemma-3-1b-it-GGUF",
                completion_transport=transport,
            )
            bridge.archival_mem.insert("vocabulary", "яблоко (apple)", importance=9)

            reply = bridge.generate_reply("How do you say apple in Russian?")

            self.assertEqual(reply, "Это слово переводится как яблоко. Попробуй повторить.")
            self.assertEqual(len(transport.payloads), 2)
            second_payload = transport.payloads[1]
            serialized = json.dumps(second_payload, ensure_ascii=False)
            self.assertIn("TOOL RESULT consult_russian_teacher_manual", serialized)

    def test_export_backup_writes_memory_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transport = SequenceTransport(
                [
                    _message_response(
                        'send_message\n{"message":"Привет. Давай учить русский."}'
                    )
                ]
            )

            bridge = PipelineMemoryBridge(
                Path(tmpdir),
                base_system_prompt="You are Boxy.",
                model_name="ggml-org/gemma-3-1b-it-GGUF",
                completion_transport=transport,
            )
            bridge.generate_reply("Hello")

            export_path = Path(tmpdir) / "memory-backup.json"
            bridge.export_backup(str(export_path))

            self.assertTrue(export_path.exists())
            payload = json.loads(export_path.read_text(encoding="utf-8"))
            self.assertIn("core", payload)
            self.assertIn("recall", payload)
            self.assertIn("archival", payload)


if __name__ == "__main__":
    unittest.main()
