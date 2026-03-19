import pyttsx3
import os

# filename -> text
files = {'1_m.wav': 'один', '1_f.wav': 'одна', '1_n.wav': 'одно', '2_m.wav': 'два', '2_f.wav': 'две', '2_n.wav': 'два', '3.wav': 'три', '4.wav': 'четыре', '5.wav': 'пять', 'dog_sg.wav': 'собака', 'dog_pl.wav': 'собаки', 'dog_gen_pl.wav': 'собак', 'cat_sg.wav': 'кошка', 'cat_pl.wav': 'кошки', 'cat_gen_pl.wav': 'кошек', 'car_sg.wav': 'машина', 'car_pl.wav': 'машины', 'car_gen_pl.wav': 'машин', 'ball_sg.wav': 'мяч', 'ball_pl.wav': 'мячи', 'ball_gen_pl.wav': 'мячей', 'red_m.wav': 'красный', 'red_f.wav': 'красная', 'red_n.wav': 'красное', 'red_pl.wav': 'красные', 'blue_m.wav': 'синий', 'blue_f.wav': 'синяя', 'blue_n.wav': 'синее', 'blue_pl.wav': 'синие', 'light_blue_m.wav': 'голубой', 'light_blue_f.wav': 'голубая', 'light_blue_n.wav': 'голубое', 'light_blue_pl.wav': 'голубые', 'green_m.wav': 'зелёный', 'green_f.wav': 'зелёная', 'green_n.wav': 'зелёное', 'green_pl.wav': 'зелёные', 'white_m.wav': 'белый', 'white_f.wav': 'белая', 'white_n.wav': 'белое', 'white_pl.wav': 'белые', 'yellow_m.wav': 'жёлтый', 'yellow_f.wav': 'жёлтая', 'yellow_n.wav': 'жёлтое', 'yellow_pl.wav': 'жёлтые', 'purple_m.wav': 'фиолетовый', 'purple_f.wav': 'фиолетовая', 'purple_n.wav': 'фиолетовое', 'purple_pl.wav': 'фиолетовые', 'pink_m.wav': 'розовый', 'pink_f.wav': 'розовая', 'pink_n.wav': 'розовое', 'pink_pl.wav': 'розовые', 'gray_m.wav': 'серый', 'gray_f.wav': 'серая', 'gray_n.wav': 'серое', 'gray_pl.wav': 'серые', 'brown_m.wav': 'коричневый', 'brown_f.wav': 'коричневая', 'brown_n.wav': 'коричневое', 'brown_pl.wav': 'коричневые', 'q_color.wav': 'Какого цвета', 'q_count.wav': 'Сколько', 'q_tail.wav': 'на картинке?'}

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
