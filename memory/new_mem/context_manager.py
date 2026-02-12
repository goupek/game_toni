# context_manager.py
from datetime import datetime
from dataclasses import dataclass, field

@dataclass
class InteractionContext:
    last_interaction: datetime = field(default_factory=datetime.now)
    interaction_count: int = 0

class ContextManager:
    def __init__(self):
        self.interaction = InteractionContext()

    def update_interaction(self, context):
        self.interaction = context

    def get_context_string(self) -> str:
        # Simple info for the teacher to know how long it's been
        if not self.interaction.last_interaction:
            return ""
        
        diff = datetime.now() - self.interaction.last_interaction
        mins = int(diff.total_seconds() / 60)
        return f"\n[CONTEXT] We last spoke {mins} minutes ago.\n"