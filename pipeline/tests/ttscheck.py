import torch
import time
import soundfile as sf
from qwen_tts import Qwen3TTSModel

# 1. Load the CustomVoice model
model = Qwen3TTSModel.from_pretrained(
    "./Qwen3-TTS-0.6B-CustomVoice",
    device_map="cuda:0",
    dtype=torch.bfloat16, 
    attn_implementation="sdpa"
)

# 2. Your LLM output text
target_text = "Жили-были старик со старухой. Однажды просит старикю Испеки, старуха, колобок. Из чего испечь-то? Муки нет. Эх, старуха! По коробу поскреби, по сусеку помети, авось муки и наберется. Старуха по коробу поскребла, по сусеку помела, и набралось муки две пригоршни. Замесила на сметане, пожарила в масле и положила на окошечко остудить."
# --- START TIMING ---
start_time = time.time()

wavs, sr = model.generate_custom_voice(
    text=target_text,
    speaker="vivian"
)

end_time = time.time()
# --- END TIMING ---

generation_time = end_time - start_time
sf.write("kolobok.wav", wavs[0], sr)
print(f"⏱️ Time taken: {generation_time:.2f} seconds")
# 4. Save the output
print("Success!")