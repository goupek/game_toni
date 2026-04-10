"""
Batch-trim leading and trailing silence from WAV files in a folder.
- No external libs (uses wave + audioop).
- Overwrites files by default (optionally backs up originals).

Tested logic: scans RMS energy in small windows, finds first/last window above threshold,
keeps a small padding so speech doesn't get cut.
"""

import os
import wave
import audioop
import shutil

IN_DIR = "tts_out"          # folder with your wav files
BACKUP_DIR = None #"tts_out_bak"  # set to None to disable backups

# Tuning knobs
WINDOW_MS = 10              # analysis window size
THRESHOLD_RMS = 120         # silence threshold (increase if it trims too little; decrease if it trims too much)
PAD_MS = 30                 # keep this much audio before/after detected speech
MIN_KEEP_MS = 80            # if speech is extremely short, keep at least this much

def trim_wav_file(path, threshold_rms=THRESHOLD_RMS, window_ms=WINDOW_MS, pad_ms=PAD_MS, min_keep_ms=MIN_KEEP_MS):
    with wave.open(path, "rb") as w:
        params = w.getparams()
        nchannels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        nframes = w.getnframes()
        audio = w.readframes(nframes)

    if nframes == 0:
        return False, "empty"

    bytes_per_frame = nchannels * sampwidth
    window_frames = max(1, int(framerate * window_ms / 1000))
    window_bytes = window_frames * bytes_per_frame

    # Compute RMS per window
    rms_vals = []
    positions = []  # byte start for each window
    for start in range(0, len(audio), window_bytes):
        chunk = audio[start:start + window_bytes]
        if not chunk:
            break
        # If chunk isn't aligned to frame boundary, drop the tail (rare)
        chunk = chunk[: (len(chunk) // bytes_per_frame) * bytes_per_frame]
        if not chunk:
            continue
        rms = audioop.rms(chunk, sampwidth)
        rms_vals.append(rms)
        positions.append(start)

    if not rms_vals:
        return False, "no windows"

    # Find first and last window above threshold
    first_idx = None
    last_idx = None
    for i, rms in enumerate(rms_vals):
        if rms >= threshold_rms:
            first_idx = i
            break
    for i in range(len(rms_vals) - 1, -1, -1):
        if rms_vals[i] >= threshold_rms:
            last_idx = i
            break

    if first_idx is None or last_idx is None:
        # Entire file considered silent -> keep as-is
        return False, "all silent (kept)"

    start_byte = positions[first_idx]
    end_byte = positions[last_idx] + window_bytes

    # Add padding
    pad_frames = int(framerate * pad_ms / 1000)
    pad_bytes = pad_frames * bytes_per_frame

    start_byte = max(0, start_byte - pad_bytes)
    end_byte = min(len(audio), end_byte + pad_bytes)

    # Ensure minimum keep duration
    min_keep_frames = int(framerate * min_keep_ms / 1000)
    min_keep_bytes = min_keep_frames * bytes_per_frame
    if end_byte - start_byte < min_keep_bytes:
        # expand around center
        center = (start_byte + end_byte) // 2
        start_byte = max(0, center - min_keep_bytes // 2)
        end_byte = min(len(audio), start_byte + min_keep_bytes)

    # Align to whole frames
    start_byte = (start_byte // bytes_per_frame) * bytes_per_frame
    end_byte = (end_byte // bytes_per_frame) * bytes_per_frame
    if end_byte <= start_byte:
        return False, "bad trim (kept)"

    trimmed = audio[start_byte:end_byte]

    # Write back (overwrite)
    with wave.open(path, "wb") as w:
        w.setparams(params)
        w.writeframes(trimmed)

    # Report how much we trimmed
    old_ms = (len(audio) / bytes_per_frame) * 1000 / framerate
    new_ms = (len(trimmed) / bytes_per_frame) * 1000 / framerate
    return True, f"{old_ms:.0f}ms -> {new_ms:.0f}ms"

def main():
    if not os.path.isdir(IN_DIR):
        raise RuntimeError(f"Folder not found: {IN_DIR}")

    wavs = [f for f in os.listdir(IN_DIR) if f.lower().endswith(".wav")]
    wavs.sort()

    if BACKUP_DIR:
        os.makedirs(BACKUP_DIR, exist_ok=True)

    changed = 0
    for fn in wavs:
        src = os.path.join(IN_DIR, fn)

        if BACKUP_DIR:
            dst = os.path.join(BACKUP_DIR, fn)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)

        ok, msg = trim_wav_file(src)
        print(f"{fn}: {msg}")
        if ok:
            changed += 1

    print(f"\nProcessed {len(wavs)} files. Trimmed {changed} files.")
    if BACKUP_DIR:
        print(f"Backups in: {os.path.abspath(BACKUP_DIR)}")

if __name__ == "__main__":
    main()
