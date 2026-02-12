import random

# -----------------------------
# NOUNS - singular, plural, genitive plural (множественный родительный), gender
# -----------------------------

NOUNS = {
    "dog":  {"sg": "собака", "pl": "собаки", "gen_pl": "собак",  "gender": "f"},
    "cat":  {"sg": "кошка",  "pl": "кошки",  "gen_pl": "кошек",  "gender": "f"},
    "car":  {"sg": "машина", "pl": "машины", "gen_pl": "машин",  "gender": "f"},
    "ball": {"sg": "мяч",    "pl": "мячи",   "gen_pl": "мячей",  "gender": "m"},
}

# -----------------------------
# ADJECTIVES masculine, feminine, neuter, plural
# -----------------------------

ADJECTIVES = {
    "red":     {"m": "красный",     "f": "красная",     "n": "красное",     "pl": "красные"},
    "blue":    {"m": "синий",       "f": "синяя",       "n": "синее",       "pl": "синие"},
    "light_blue": {"m": "голубой",  "f": "голубая",     "n": "голубое",     "pl": "голубые"},
    "green":   {"m": "зелёный",     "f": "зелёная",     "n": "зелёное",     "pl": "зелёные"},
#    "black":   {"m": "чёрный",      "f": "чёрная",      "n": "чёрное",      "pl": "чёрные"},
    "white":   {"m": "белый",       "f": "белая",       "n": "белое",       "pl": "белые"},
    "yellow":  {"m": "жёлтый",      "f": "жёлтая",      "n": "жёлтое",      "pl": "жёлтые"},
    "purple":  {"m": "фиолетовый",  "f": "фиолетовая",  "n": "фиолетовое",  "pl": "фиолетовые"},
    "pink":    {"m": "розовый",     "f": "розовая",     "n": "розовое",     "pl": "розовые"},
    "grey":    {"m": "серый",       "f": "серая",       "n": "серое",       "pl": "серые"},
    "brown":   {"m": "коричневый",  "f": "коричневая",  "n": "коричневое",  "pl": "коричневые"},
}

# -----------------------------
# COLOR RGB
# -----------------------------

COLOR_RGB = {
    "red":        (235, 60, 60),
    "blue":       (70, 130, 240),
    "light_blue": (135, 206, 250),
    "green":      (40, 190, 90),
#    "black":      (20, 20, 20),
    "white":      (240, 240, 240),
    "yellow":     (250, 220, 60),
    "purple":     (150, 80, 200),
    "pink":       (255, 140, 200),
    "grey":       (150, 150, 150),
    "brown":      (150, 100, 60),
}

# -----------------------------
# NUMBERS
# -----------------------------

NUM_WORD = {
    1: {"m": "один", "f": "одна", "n": "одно"},
    2: {"m": "два",  "f": "две",  "n": "два"},
    3: "три",
    4: "четыре",
    5: "пять",
}

# -----------------------------
# HELPERS
# -----------------------------

def quantity_prompt(noun_key):
    return f"Сколько {NOUNS[noun_key]['gen_pl']} на картинке?"

def color_prompt(noun_key, count):
    return f"Какого цвета {noun_form(noun_key, count)} на картинке?"

def noun_form(noun_key, count):
    if count == 1:
        return NOUNS[noun_key]["sg"]
    return NOUNS[noun_key]["pl"]

def adjective_form(adj_key, noun_key, count):
    forms = ADJECTIVES[adj_key]
    if count == 1:
        gender = NOUNS[noun_key]["gender"]
        return forms[gender]
    return forms["pl"]

def number_form(n, noun_key):
    val = NUM_WORD[n]
    if isinstance(val, dict):
        gender = NOUNS[noun_key]["gender"]
        return val[gender]
    return val

# -----------------------------
# ROUND GENERATOR
# -----------------------------

def generate_round(option_count=3, max_count=4):

    qtype = random.choice(["count", "color"]) # TODO: more later
    noun_key = random.choice(list(NOUNS.keys()))
    adj_key = random.choice(list(ADJECTIVES.keys()))
    count = random.randint(1, max_count)
    rgb = COLOR_RGB.get(adj_key)
    
    if qtype == "count":
        prompt = quantity_prompt(noun_key)
        correct = number_form(count, noun_key)

        all_options = [number_form(n, noun_key) for n in range(1, max_count + 1)]
        options = random.sample(all_options, min(option_count, len(all_options)))
        if correct not in options:
            options[0] = correct
        random.shuffle(options)

    elif qtype == "color":
        prompt = color_prompt(noun_key, count)
        correct = adjective_form(adj_key, noun_key, count)

        all_options = [
            adjective_form(k, noun_key, count)
            for k in ADJECTIVES.keys()
        ]
        options = random.sample(all_options, option_count)
        if correct not in options:
            options[0] = correct
        random.shuffle(options)
    return {
        "qtype": qtype,
        "noun_key": noun_key,
        "count": count,
        "adj_key": adj_key,
        "rgb": rgb,
        "prompt_text": prompt,
        "options": options,
        "correct": correct,
    }


# -----------------------------
# TEST
# -----------------------------

if __name__ == "__main__":
    for _ in range(6):
        print(generate_round())
