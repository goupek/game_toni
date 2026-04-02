import unittest

from config import Config


class TestLlamaCppConfig(unittest.TestCase):
    def test_openai_base_url_appends_v1_once(self):
        conf = Config(LLAMA_CPP_BASE_URL="http://localhost:8080")
        self.assertEqual(conf.openai_base_url(), "http://localhost:8080/v1")

        conf = Config(LLAMA_CPP_BASE_URL="http://localhost:8080/v1")
        self.assertEqual(conf.openai_base_url(), "http://localhost:8080/v1")

    def test_resolve_model_prefers_small_gemma_when_auto(self):
        conf = Config(LLAMA_CPP_MODEL="auto")
        conf.fetch_available_models = lambda: [  # type: ignore[method-assign]
            "some-other-model",
            "ggml-org/gemma-3-1b-it-GGUF:Q4_K_M",
            "ggml-org/gemma-3-4b-it-GGUF:Q4_K_M",
        ]

        self.assertEqual(conf.resolve_model(refresh=True), "ggml-org/gemma-3-1b-it-GGUF:Q4_K_M")

    def test_resolve_model_uses_requested_substring_match(self):
        conf = Config(LLAMA_CPP_MODEL="gemma-3-1b")
        conf.fetch_available_models = lambda: [  # type: ignore[method-assign]
            "ggml-org/gemma-3-1b-it-GGUF:Q4_K_M",
        ]

        self.assertEqual(conf.resolve_model(refresh=True), "ggml-org/gemma-3-1b-it-GGUF:Q4_K_M")

    def test_small_gemma_defaults_to_text_tool_calls(self):
        conf = Config()
        self.assertTrue(conf.should_use_text_tool_calls("ggml-org/gemma-3-1b-it-GGUF:Q4_K_M"))
        self.assertTrue(conf.should_use_text_tool_calls("google/gemma-2-2b-it"))
        self.assertFalse(conf.should_use_text_tool_calls("qwen2.5-1.5b"))


if __name__ == "__main__":
    unittest.main()
