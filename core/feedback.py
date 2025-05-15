import json
import os
from datetime import datetime

FEEDBACK_FILE = 'logs/feedback.jsonl'

def submit_feedback(user: str, query: str, rating: int, comments: str = ""):
    entry = {
        'timestamp': datetime.now().isoformat(),
        'user': user,
        'query': query,
        'rating': rating,
        'comments': comments
    }
    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    with open(FEEDBACK_FILE, 'a') as f:
        f.write(json.dumps(entry) + '\n') 