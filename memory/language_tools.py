# language_tools.py

import json
from memory_system import Memory

def get_language_tools() -> list:
    """Returns the tool definitions for the LLM."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_next_word_to_learn",
                "description": "Fetches the very next word the user needs to learn from the curriculum. Call this to start a new lesson or continue an existing one.",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "mark_word_as_learned",
                "description": "Marks a specific word as 'learned' in the user's progress after they have successfully practiced it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "word_id": {
                            "type": "string",
                            "description": "The unique ID of the word to mark as learned (e.g., 'L1_W2')."
                        }
                    },
                    "required": ["word_id"]
                }
            }
        }
    ]

class LanguageToolExecutor:
    """Executes the curriculum and progress tracking functions."""
    
    def __init__(self, memory: Memory):
        self.memory = memory
        with open("lessons_db.json", 'r', encoding='utf-8') as f:
            self.lessons_db = json.load(f)

    def execute(self, function_name: str, args: dict) -> str:
        if function_name == "get_next_word_to_learn":
            return self._get_next_word()
        elif function_name == "mark_word_as_learned":
            return self._mark_as_learned(args.get("word_id"))
        return f"❌ Unknown language tool: {function_name}"

    def _get_progress(self) -> dict:
        """Helper to get and parse the current progress from core memory."""
        progress_block = self.memory.get_block("lesson_progress")
        return json.loads(progress_block.value)

    def _get_next_word(self) -> str:
        """Finds and returns the next unlearned word."""
        progress = self._get_progress()
        current_lesson_id = progress.get("current_lesson_id", 1)
        learned_ids = progress.get("learned_word_ids", [])

        # Find the current lesson in the database
        current_lesson = next((lesson for lesson in self.lessons_db["lessons"] if lesson["lesson_id"] == current_lesson_id), None)

        if not current_lesson:
            return "🎉 You have completed all available lessons! Congratulations!"

        # Find the first word in this lesson that has not been learned
        for word in current_lesson["words"]:
            if word["word_id"] not in learned_ids:
                # Return the word data as a JSON string for the AI to parse
                return json.dumps(word)
        
        # If all words in the current lesson are learned, advance to the next one
        next_lesson_id = current_lesson_id + 1
        next_lesson = next((lesson for lesson in self.lessons_db["lessons"] if lesson["lesson_id"] == next_lesson_id), None)

        if not next_lesson:
            return "🎉 You have completed all available lessons! Congratulations!"

        # Update the user's progress to the new lesson
        new_progress = {"current_lesson_id": next_lesson_id, "learned_word_ids": learned_ids}
        progress_block = self.memory.get_block("lesson_progress")
        progress_block.value = json.dumps(new_progress) # Direct replacement is easier here
        self.memory.save()
        
        # Return the first word of the new lesson
        first_word_of_new_lesson = next_lesson["words"][0]
        return f"LESSON {current_lesson_id} COMPLETE! Moving to Lesson {next_lesson_id}: {next_lesson['title']}. Your first word is: {json.dumps(first_word_of_new_lesson)}"

    def _mark_as_learned(self, word_id: str) -> str:
        """Adds a word_id to the learned list in core memory."""
        if not word_id:
            return "❌ Error: word_id was not provided."

        progress = self._get_progress()
        learned_ids = progress.get("learned_word_ids", [])

        if word_id not in learned_ids:
            learned_ids.append(word_id)
            progress["learned_word_ids"] = learned_ids
            
            # Update the memory block
            progress_block = self.memory.get_block("lesson_progress")
            success, msg = progress_block.replace(progress_block.value, json.dumps(progress))
            
            if success:
                self.memory.save()
                return f"✅ Progress updated. Word {word_id} marked as learned."
            else:
                return f"❌ Failed to update progress in memory: {msg}"
        else:
            return f"ℹ️  Info: Word {word_id} was already marked as learned."