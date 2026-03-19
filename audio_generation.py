import pyttsx3
import os
from question_generation import NOUNS, ADJECTIVES, NUM_WORD

# Build filename → text mapping from DB-backed vocab
files = {}

for noun_key, forms in NOUNS.items():
    for form_type, form_value in forms.items():
        if form_type != "gender":
            files[f"{noun_key}_{form_type}.wav"] = form_value

for adj_key, forms in ADJECTIVES.items():
    adj_filename = adj_key.replace(" ", "_")
    for gender, form_value in forms.items():
        files[f"{adj_filename}_{gender}.wav"] = form_value

for num_key, forms in NUM_WORD.items():
    values = list(forms.values())
    if len(set(values)) == 1:
        files[f"{num_key}.wav"] = values[0]
    else:
        for gender, form_value in forms.items():
            files[f"{num_key}_{gender}.wav"] = form_value

files.update({
    "q_color.wav": "Какого цвета",
    "q_count.wav": "Сколько",
    "q_tail.wav":  "на картинке?",
})

OUT_DIR = "tts_out"  # change if you want
os.makedirs(OUT_DIR, exist_ok=True)

engine = pyttsx3.init()

# Pick Microsoft Irina automatically if present
irina_id = None
for v in engine.getProperty("voices"):
    if "Irina" in (v.name or "") or "IRINA" in (v.id or ""):
        irina_id = v.id
        break

if irina_id is None:
    raise RuntimeError(
        "Microsoft Irina voice not found. Install it in Windows Settings or print voices to see available IDs."
    )

engine.setProperty("voice", irina_id)

# Optional tuning
engine.setProperty("rate", 170)   # try 150-190
engine.setProperty("volume", 1.0) # 0.0-1.0

# Queue all files, then render
for filename, text in files.items():
    out_path = os.path.join(OUT_DIR, filename)
    engine.save_to_file(text, out_path)

engine.runAndWait()
print(f"Saved {len(files)} files to: {os.path.abspath(OUT_DIR)}")
