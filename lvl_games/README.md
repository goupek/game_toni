# lvl_games

Connected versions of the level-identification game and the colour/count
practice game, sharing a single word-knowledge store so that results from
one game feed directly into the other.

---

## Overview

```
lvl_games/
├── README.md                        ← this file
├── word_knowledge.py                ← shared knowledge store (read/write)
├── word_knowledge.json              ← auto-generated; tracks known/unknown per word
├── vocab_db_extended.json           ← full vocabulary with gender + grammatical forms
├── lvl_game_connected.py            ← level-identification game (saves results on exit)
├── question_generation_filtered.py  ← knowledge-aware round generator for game2
└── game2_connected.py               ← colour/count game (only shows unknown words)
```

---

## Recommended workflow

```
# Step 1 – run the level-identification game (tkinter)
python lvl_games/lvl_game_connected.py

# Step 2 – run the practice game (pygame)
python lvl_games/game2_connected.py
```

Both scripts are run from the **repo root** so that shared assets
(`images/`, `audio/`, `tts_out/`) are found automatically.

After Step 1 finishes, `word_knowledge.json` is written (or updated) with
each word marked `known: true` or `known: false`.  
Step 2 reads that file and skips any word already marked as known.

If `word_knowledge.json` does not exist yet (Step 2 run first), every word
is treated as unknown so the game plays normally.

---

## Files in detail

### `word_knowledge.py`

Central module used by both games. Never run directly.

**Key public API**

| Symbol                                       | Type | Description                                                          |
| -------------------------------------------- | ---- | -------------------------------------------------------------------- |
| `GAME2_ADJECTIVES`                           | dict | Adj-key → `{en, topic, ru_base, ru_forms{m,f,n,pl}}`                 |
| `GAME2_NOUNS`                                | dict | Noun-key → `{en, topic, gender, ru_forms{sg,pl,gen_pl}}`             |
| `GAME2_COUNTS`                               | dict | Count int → `{en, topic, ru_base, ru_forms}`                         |
| `_RU_FORM_TO_EN`                             | dict | Any Russian surface form → English concept key (built at import)     |
| `ru_form_to_en(ru)`                          | fn   | Look up the English concept for any Russian form                     |
| `ensure_game2_words_present()`               | fn   | Add missing game2 words to `word_knowledge.json` (called on startup) |
| `update_from_level_game(history, db_topics)` | fn   | Persist known/unknown after level game ends                          |
| `unknown_adj_keys()`                         | fn   | Returns adj-keys not yet known (used by filtered generator)          |
| `unknown_counts()`                           | fn   | Returns count integers not yet known                                 |
| `noun_gender(noun_key)`                      | fn   | Returns grammatical gender ("m"/"f"/"n") for a game2 noun            |

**`word_knowledge.json` schema**

```json
{
  "words": {
    "red": {
      "known": true,
      "ru_base": "красный",
      "ru_forms": {
        "m": "красный",
        "f": "красная",
        "n": "красное",
        "pl": "красные"
      },
      "topic": "colors",
      "source": "game2"
    },
    "one": {
      "known": null,
      "ru_base": "один",
      "ru_forms": { "m": "один", "f": "одна", "n": "одно" },
      "topic": "numbers",
      "source": "game2"
    }
  }
}
```

| `known` value | Meaning                                                         |
| ------------- | --------------------------------------------------------------- |
| `true`        | Answered correctly at least once in the level game              |
| `false`       | Answered incorrectly, or present in vocab but never asked       |
| `null`        | Registered from game2 startup; not yet tested by the level game |

Words with `known: false` or `known: null` are treated as **unknown** by game2.

---

### `vocab_db_extended.json`

Extended version of `level/vocab_db.json`. Adds three new optional fields
to every entry where applicable:

| Field          | Applies to                               | Content                                          |
| -------------- | ---------------------------------------- | ------------------------------------------------ |
| `"gender"`     | all nouns                                | `"m"` / `"f"` / `"n"` / `"pl"` / `"indecl"`      |
| `"forms"`      | adjectives & numbers 1–2                 | `{ "m", "f", "n", "pl" }` or `{ "m", "f", "n" }` |
| `"noun_forms"` | game2 nouns (мяч, собака, кошка, машина) | `{ "sg", "pl", "gen_pl" }`                       |

Numbers 3 and above carry `"forms": { "all": "три" }` (no gender distinction).  
Verbs, interjections, and fixed phrases carry no extra fields.

This file is used by `lvl_game_connected.py` automatically. The original
`level/vocab_db.json` is **not modified**.

---

### `lvl_game_connected.py`

Copy of `level/lvl_game_improved_Fazli_version.py` with one addition:

- When the diagnostic session ends (`_finish_and_show_result`), calls
  `word_knowledge.update_from_level_game(history, db_topics)` before
  destroying the window.
- Defaults to `vocab_db_extended.json`; falls back to the original
  `level/vocab_db.json` if the extended file is missing.

**What gets saved**

For every word tested during the session:

- answered **correctly** at least once → `known: true`
- answered **incorrectly** on every attempt → `known: false`

Words in the vocab that were never asked in this session are seeded with
`known: false` (treated as unknown until proven otherwise).

Reverse-lookup via `_RU_FORM_TO_EN` ensures that a declined form tested by
the level game (e.g. `"красная"` shown as `ru_to_en`) is correctly mapped to
the concept `"red"` rather than creating an orphan entry.

---

### `question_generation_filtered.py`

Drop-in alternative to `question_generation.generate_round()`.

Exposes a single function:

```python
generate_round_filtered(option_count=3, max_count=4) -> dict
```

**Filtering logic**

| Question type | Filtered by                                        |
| ------------- | -------------------------------------------------- |
| `"color"`     | Only adj-keys returned by `unknown_adj_keys()`     |
| `"count"`     | Only count integers returned by `unknown_counts()` |

If one category is fully known its question type is skipped.  
If **both** categories are fully known, falls back to the original
`generate_round()` so the game never gets stuck.

**Grammar handling**

Correct answers are always in the proper grammatical form:

- Color answers use `adjective_form(adj_key, noun_key, count)` which selects
  masculine / feminine / plural based on the noun's gender and count.
  Example: `собака` (f) + `"red"` + count 1 → `"красная"`
- Count answers use `number_form(count, noun_key)` which selects the
  gendered numeral form.
  Example: `собака` (f) + count 2 → `"две"`; `мяч` (m) + count 2 → `"два"`

Distractor options are also produced in the same grammatical form so all
answer buttons are grammatically consistent.

---

### `game2_connected.py`

Copy of `game2.py` with two changes:

1. Imports `generate_round_filtered` instead of `generate_round`.
2. Calls `ensure_game2_words_present()` on startup so game2's vocabulary
   (10 colours, counts 1–4, 4 nouns) is registered in `word_knowledge.json`
   even if the level game has never been run.

Everything else — pygame rendering, audio, button layout, progress bar,
menu / finish screens — is identical to the original.

---

## Grammatical forms reference

### Colour adjectives (game2 uses these as answers)

| English    | Masculine  | Feminine   | Neuter     | Plural     |
| ---------- | ---------- | ---------- | ---------- | ---------- |
| red        | красный    | красная    | красное    | красные    |
| blue       | синий      | синяя      | синее      | синие      |
| light blue | голубой    | голубая    | голубое    | голубые    |
| green      | зелёный    | зелёная    | зелёное    | зелёные    |
| white      | белый      | белая      | белое      | белые      |
| yellow     | жёлтый     | жёлтая     | жёлтое     | жёлтые     |
| purple     | фиолетовый | фиолетовая | фиолетовое | фиолетовые |
| pink       | розовый    | розовая    | розовое    | розовые    |
| gray       | серый      | серая      | серое      | серые      |
| brown      | коричневый | коричневая | коричневое | коричневые |

### Numbers 1–4 (game2 uses these as answers)

| English | Masculine | Feminine | Neuter |
| ------- | --------- | -------- | ------ |
| one     | один      | одна     | одно   |
| two     | два       | две      | два    |
| three   | три       | три      | три    |
| four    | четыре    | четыре   | четыре |

### Game2 nouns (appear in question text, not as answers)

| English | Gender | Singular | Plural | Genitive plural |
| ------- | ------ | -------- | ------ | --------------- |
| dog     | f      | собака   | собаки | собак           |
| cat     | f      | кошка    | кошки  | кошек           |
| car     | f      | машина   | машины | машин           |
| ball    | m      | мяч      | мячи   | мячей           |

The noun gender determines which adjective / numeral form is chosen as the
correct answer (see Grammar handling above).

---

## Dependencies

Same as the parent project:

```
pygame
Pillow
requests   (for lvl_game_connected.py — Ollama embeddings)
tkinter    (stdlib, for lvl_game_connected.py)
```
