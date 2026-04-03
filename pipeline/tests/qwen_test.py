from ollama import chat

stream = chat(
    model="qwen2.5:1.5b-instruct",
    messages=[{"role": "user", "content": "Say hello in simple English, 1 sentence."}],
    stream=True,
)

for chunk in stream:
    print(chunk["message"]["content"], end="", flush=True)
