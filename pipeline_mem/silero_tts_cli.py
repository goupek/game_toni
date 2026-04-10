from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch


_ROOT = Path(__file__).resolve().parent.parent
_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)


def _sanitize(text: str) -> str:
    text = re.sub(r"[*_~`#>\[\]()]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    args = parser.parse_args()

    text = _sanitize(args.text)
    if not text:
        return 0
    if not _CYRILLIC_RE.search(text):
        return 0

    model_path = Path(
        os.getenv("BOXY_SILERO_MODEL", str(_ROOT / "models" / "silero" / "v5_ru.pt"))
    )
    speaker = os.getenv("BOXY_SILERO_SPEAKER", "xenia")
    sample_rate = int(os.getenv("BOXY_SILERO_SAMPLE_RATE", "8000"))

    importer = torch.package.PackageImporter(str(model_path))
    model = importer.load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))

    with torch.no_grad():
        audio = model.apply_tts(
            text=text,
            speaker=speaker,
            sample_rate=sample_rate,
        )

    wav = audio.detach().cpu().numpy().astype(np.float32, copy=False)
    proc = subprocess.Popen(
        ["aplay", "-q", "-r", str(sample_rate), "-f", "FLOAT_LE", "-c", "1", "-"],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _, err = proc.communicate(input=wav.tobytes())
    if proc.returncode != 0:
        print(err.decode(errors="replace").strip(), file=sys.stderr)
        return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
