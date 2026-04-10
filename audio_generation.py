import os
import re
import wave
from pathlib import Path

import numpy as np
import torch

from question_generation import NOUNS, ADJECTIVES, NUM_WORD


ROOT_DIR = Path(__file__).resolve().parent
OUT_DIR = ROOT_DIR / "tts_out"
MODEL_PATH = Path(
    os.getenv("BOXY_SILERO_MODEL", str(ROOT_DIR / "models" / "silero" / "v5_ru.pt"))
)
SPEAKER = os.getenv("BOXY_SILERO_SPEAKER", "xenia")
SAMPLE_RATE = int(os.getenv("BOXY_SILERO_SAMPLE_RATE", "8000"))


def _sanitize(text: str) -> str:
    text = re.sub(r"[*_~`#>\[\]()]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _write_wav(path: Path, wav: np.ndarray, sample_rate: int):
    wav = np.clip(wav, -1.0, 1.0)
    pcm16 = (wav * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm16.tobytes())


def _build_file_map():
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
        "q_tail.wav": "на картинке?",
    })
    return files


def main():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Silero model not found: {MODEL_PATH}")

    OUT_DIR.mkdir(exist_ok=True)

    importer = torch.package.PackageImporter(str(MODEL_PATH))
    model = importer.load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))

    saved = 0
    for filename, raw_text in _build_file_map().items():
        text = _sanitize(raw_text)
        if not text:
            continue

        with torch.no_grad():
            audio = model.apply_tts(
                text=text,
                speaker=SPEAKER,
                sample_rate=SAMPLE_RATE,
            )

        wav = audio.detach().cpu().numpy().astype(np.float32, copy=False)
        _write_wav(OUT_DIR / filename, wav, SAMPLE_RATE)
        saved += 1
        print(f"Saved {filename}: {text}")

    print(f"Saved {saved} files to: {OUT_DIR}")


if __name__ == "__main__":
    main()
