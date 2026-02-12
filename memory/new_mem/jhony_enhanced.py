"""
Jhony (Zhanibek) v1.0 - Russian Teacher for Toddlers
Optimized for 1-2B Parameter Models (Gemma/Qwen) on Jetson Orin Nano
"""
import json
import time
from collections import deque
from datetime import datetime
from config import conf

# Import Simplified Subsystems
from memory_system import Memory, RecallMemory, ArchivalMemory
from memory_tools import MemoryToolExecutor
from personality_system import PersonalityEngine
from context_manager import ContextManager, InteractionContext
from communication_tools import CommunicationExecutor, SendMessageArgs

# Initialize Client - Ollama is the recommended backend
from openai import OpenAI
print(f"🚀 Initializing Jhony's Brain with {conf.OLLAMA_MODEL}...")
client = OpenAI(base_url=f"{conf.OLLAMA_BASE_URL}/v1", api_key="ollama")
MODEL_NAME = conf.OLLAMA_MODEL

# Initialize Memory Systems
core_mem = Memory()
recall_mem = RecallMemory(use_semantic=conf.USE_SEMANTIC_SEARCH)
archival_mem = ArchivalMemory(use_semantic=conf.USE_SEMANTIC_SEARCH)
mem_exec = MemoryToolExecutor(core_mem, recall_mem, archival_mem)
personality = PersonalityEngine.load()
context_manager = ContextManager()
comm_exec = CommunicationExecutor()

class PerformanceTimer:
    def __init__(self):
        self.start_time = 0
        self.first_token_time = 0
        self.end_time = 0
        self.token_count = 0
    
    def start(self):
        self.start_time = time.perf_counter()
        print(f"\n⏱️  [Timer Started]", end="", flush=True)
        
    def mark_first_token(self):
        if self.first_token_time == 0:
            self.first_token_time = time.perf_counter()
            
    def stop(self):
        self.end_time = time.perf_counter()
    
    def report(self):
        if self.start_time == 0 or self.end_time == 0: return
        total_duration = self.end_time - self.start_time
        ttft = self.first_token_time - self.start_time if self.first_token_time > 0 else total_duration
        tps = self.token_count / total_duration if total_duration > 0 else 0
        print(f"\n   [⏱️ Metrics: TTFT: {ttft*1000:.0f}ms | Total: {total_duration:.2f}s | Speed: {tps:.1f} tok/s]")

def retrieve_relevant_context(query: str) -> str:
    """Simplified RAG for 1B models - only fetch top relevant teaching aids."""
    hits = recall_mem.search(query, limit=2)
    facts = archival_mem.search(query, limit=2)

    if not hits and not facts: return ""
    ctx = "\n[TEACHING CONTEXT]\n"
    for h in hits: ctx += f"- Last spoke: {h['content']}\n"
    for f in facts: ctx += f"- Russian Rule/Vocab: {f['content']}\n"
    return ctx + "\n"

def get_system_prompt():
    context_str = context_manager.get_context_string() 
    return f"""Your name is Jhony (short for Zhanibek). You are a kind Russian teacher for a toddler.
RULES:
1. Speak only simple Russian. Understand English perfectly.
2. Use 'Sandwiching': Russian word -> English word -> Russian word.
3. If the kid is stuck, use a simple Russian hint.
4. Keep responses under 10 words. Be very encouraging!
{context_str}
{core_mem.compile()}
"""

class ChatSession:
    def __init__(self):
        # Keep history short (5 messages) to fit small context windows
        self.history = deque(maxlen=5)
    
    def add(self, role, content, tool_calls=None):
        msg = {"role": role, "content": content}
        if tool_calls: msg["tool_calls"] = tool_calls
        self.history.append(msg)
    
    def add_tool_result(self, tool_id, name, content):
        self.history.append({"role": "tool", "tool_call_id": tool_id, "name": name, "content": content})

    def get_messages(self):
        return [{"role": "system", "content": get_system_prompt()}] + list(self.history)

session = ChatSession()

def chat(user_input: str):
    timer = PerformanceTimer()
    timer.start()

    # 1. Prepare Context
    context_manager.update_interaction(InteractionContext(last_interaction=datetime.now()))
    memory_context = retrieve_relevant_context(user_input)
    full_input = memory_context + user_input
    
    recall_mem.insert("user", user_input, defer_embedding=True)
    session.add("user", full_input)

    # 2. Simple Generation (No heartbeat loop, no inner monologue)
    tools = mem_exec.get_tool_schemas() # Memory tools only
    
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=session.get_messages(),
        tools=tools,
        tool_choice="auto"
    )

    msg = response.choices[0].message
    content = msg.content or ""
    tool_calls = msg.tool_calls

    # 3. Handle Single Turn Result
    if tool_calls:
        for tc in tool_calls:
            args = json.loads(tc.function.arguments)
            # Process Memory or Message delivery
            if tc.function.name == "send_message":
                print(f"🇷🇺 Jhony: {args['message']}")
                recall_mem.insert("assistant", args['message'])
            else:
                result = mem_exec.execute(tc.function.name, args)
                session.add_tool_result(tc.id, tc.function.name, str(result))
    
    # Fallback if no tool was called
    elif content:
        print(f"🇷🇺 Jhony: {content}")
        recall_mem.insert("assistant", content)

    timer.stop()
    timer.report()

def main():
    print(f"🎓 Jhony (Zhanibek) Online - Ready to teach Russian!")
    while True:
        try:
            u = input("\nChild: ").strip()
            if not u: continue
            if u.lower() in ['exit', 'quit']: break
            chat(u)
        except KeyboardInterrupt: break

if __name__ == "__main__":
    main()