"""
Knowledge-aware wrapper around question_generation.generate_round().

generate_round_filtered() behaves exactly like generate_round() except:

  COLOR questions
    - Only picks adj_keys the kid does NOT yet know (unknown_adj_keys()).
    - Correct answer uses the adjective's grammatical form that matches
      the chosen noun's gender and count (adjective_form from q_generation).

  COUNT questions
    - Only picks counts (1-4) the kid does NOT yet know (unknown_counts()).
    - Correct answer uses the number form that matches the noun's gender
      (number_form from q_generation, which reads NOUNS[noun_key]["gender"]).

  Fallback
    - If no unknown words remain in a category that category is skipped.
    - If ALL categories are exhausted the original generate_round() is used
      so the game never gets stuck.

Grammar handling
----------------
Grammatical gender for nouns comes from question_generation.NOUNS[noun_key]["gender"].
question_generation.py is authoritative for the answer text
(adjective_form / number_form call it directly), and word_knowledge.py
is used only for filtering decisions.
"""

import random
import sys
from pathlib import Path

# Allow imports from the parent game directory
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from question_generation import (
    NOUNS,
    ADJECTIVES,
    COLOR_RGB,
    quantity_prompt,
    color_prompt,
    adjective_form,
    number_form,
)
from word_knowledge import (
    unknown_adj_keys,
    unknown_counts,
    noun_gender,
)


# ── public API ────────────────────────────────────────────────────────────────

def generate_round_filtered(option_count: int = 3, max_count: int = 4) -> dict:
    """
    Return a round dict identical in structure to question_generation.generate_round(),
    constrained to words the kid has not yet mastered.

    Round dict keys
    ---------------
    qtype, noun_key, count, adj_key, rgb, prompt_text, options, correct
    """

    unk_adjs   = unknown_adj_keys()   # e.g. ["blue", "green", "brown", …]
    unk_counts = unknown_counts()     # e.g. [1, 2, 4]

    possible_qtypes = []
    if unk_adjs:
        possible_qtypes.append("color")
    if unk_counts:
        possible_qtypes.append("count")

    # Full fallback: nothing left to learn → use original unfiltered generator
    if not possible_qtypes:
        from question_generation import generate_round
        return generate_round(option_count=option_count, max_count=max_count)

    qtype    = random.choice(possible_qtypes)
    noun_key = random.choice(list(NOUNS.keys()))

    # Noun gender used for choosing the correct adjective/number form.
    # question_generation.NOUNS is authoritative for answer generation.
    gender = NOUNS[noun_key]["gender"]   # "m" | "f"  (game2 only has m/f nouns)

    if qtype == "count":
        count   = random.choice(unk_counts)
        # adj_key is not part of a count answer but needed for rgb in the round dict
        adj_key = random.choice(list(ADJECTIVES.keys()))
        rgb     = COLOR_RGB.get(adj_key)

        prompt  = quantity_prompt(noun_key)

        # number_form uses NOUNS[noun_key]["gender"] internally to pick
        # "один"/"одна" vs "два"/"две" etc.
        correct = number_form(count, noun_key)

        # Option pool: all gendered number forms for this noun (1..max_count)
        all_options = [number_form(n, noun_key) for n in range(1, max_count + 1)]
        options = random.sample(all_options, min(option_count, len(all_options)))
        if correct not in options:
            options[0] = correct
        random.shuffle(options)

    else:  # "color"
        adj_key = random.choice(unk_adjs)
        count   = random.randint(1, max_count)
        rgb     = COLOR_RGB.get(adj_key)

        prompt  = color_prompt(noun_key, count)

        # adjective_form picks m/f/n/pl based on noun gender and count
        correct = adjective_form(adj_key, noun_key, count)

        # Build option pool: all adjectives in the correct grammatical form
        # for this noun/count so the distractors are grammatically plausible
        all_options = [
            adjective_form(k, noun_key, count)
            for k in ADJECTIVES.keys()
        ]
        options = random.sample(all_options, min(option_count, len(all_options)))
        if correct not in options:
            options[0] = correct
        random.shuffle(options)

    return {
        "qtype":       qtype,
        "noun_key":    noun_key,
        "count":       count,
        "adj_key":     adj_key,
        "rgb":         rgb,
        "prompt_text": prompt,
        "options":     options,
        "correct":     correct,
    }
