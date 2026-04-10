import random
from database.db_queries import get_game2_vocab_by_manifest

# Keep this as the game-side subset filter tied to available assets.
# DB can contain more vocabulary; gameplay should only use this subset.
ENABLED_WORDS = {
    "nouns": {"dog", "cat", "car", "ball"},
    "adjectives": {
        "red", "blue", "light blue", "green", "white",
        "yellow", "purple", "pink", "gray", "brown",
    },
    "numbers": {1, 2, 3, 4, 5},
}

# Load vocabulary from DB (with graceful fallback to base forms if forms missing)
_db_vocab = get_game2_vocab_by_manifest(ENABLED_WORDS)
NOUNS = _db_vocab["nouns"]
ADJECTIVES = _db_vocab["adjectives"]
NUM_WORD = _db_vocab["numbers"]

# COLOR RGB (not in DB, kept as hardcoded mapping)
COLOR_RGB = {
    "red":        (235, 60, 60),
    "blue":       (70, 130, 240),
    "light blue": (135, 206, 250),
    "green":      (40, 190, 90),
    "white":      (240, 240, 240),
    "yellow":     (250, 220, 60),
    "purple":     (150, 80, 200),
    "pink":       (255, 140, 200),
    "gray":       (150, 150, 150),
    "brown":      (150, 100, 60),
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


def get_enabled_words():
    """Return a copy of the enabled gameplay subset manifest."""
    return {
        "nouns": set(ENABLED_WORDS["nouns"]),
        "adjectives": set(ENABLED_WORDS["adjectives"]),
        "numbers": set(ENABLED_WORDS["numbers"]),
    }


def _enabled_noun_keys():
    keys = [k for k in NOUNS.keys() if k in ENABLED_WORDS["nouns"]]
    return keys or list(NOUNS.keys())


def _enabled_adjective_keys():
    keys = [k for k in ADJECTIVES.keys() if k in ENABLED_WORDS["adjectives"]]
    return keys or list(ADJECTIVES.keys())


def _enabled_number_values(max_count):
    allowed = [n for n in range(1, max_count + 1) if n in ENABLED_WORDS["numbers"] and n in NUM_WORD]
    return allowed or [n for n in range(1, max_count + 1) if n in NUM_WORD]

# -----------------------------
# ROUND GENERATOR
# -----------------------------

def generate_round(option_count=3, max_count=4):

    noun_keys = _enabled_noun_keys()
    adjective_keys = _enabled_adjective_keys()
    number_values = _enabled_number_values(max_count)

    qtype = random.choice(["count", "color"]) # TODO: more later
    noun_key = random.choice(noun_keys)
    adj_key = random.choice(adjective_keys)
    count = random.choice(number_values)
    rgb = COLOR_RGB.get(adj_key)
    
    if qtype == "count":
        prompt = quantity_prompt(noun_key)
        correct = number_form(count, noun_key)

        all_options = [number_form(n, noun_key) for n in number_values]
        options = random.sample(all_options, min(option_count, len(all_options)))
        if correct not in options:
            options[0] = correct
        random.shuffle(options)

    elif qtype == "color":
        prompt = color_prompt(noun_key, count)
        correct = adjective_form(adj_key, noun_key, count)

        all_options = [
            adjective_form(k, noun_key, count)
            for k in adjective_keys
        ]
        options = random.sample(all_options, min(option_count, len(all_options)))
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
