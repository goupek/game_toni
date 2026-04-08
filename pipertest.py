import wave
import traceback
from piper.voice import PiperVoice

MODEL = "models/piper/en_US-lessac-medium.onnx"
TEXT = "Hello. This is a direct Piper test."
print(" h   iiii")

voice = PiperVoice.load(MODEL)
print("Loaded voice")
print("sample rate:", getattr(getattr(voice, "config", None), "sample_rate", None))

try:
    with wave.open("direct_test.wav", "wb") as wav_file:
        if hasattr(voice, "synthesize_wav"):
            print("using synthesize_wav")
            voice.synthesize_wav(TEXT, wav_file)
        elif hasattr(voice, "synthesize"):
            print("using synthesize")
            result = voice.synthesize(TEXT, wav_file)
            if result is not None:
                try:
                    for _ in result:
                        pass
                except TypeError:
                    pass
        else:
            raise RuntimeError("No suitable synthesize method found")

    print("done")
except Exception:
    traceback.print_exc()