from flask import Flask, render_template, request
import os
import json
from datetime import datetime
import uuid
import sys

# Setup path to custom agents
BASE_DIR = os.path.dirname(__file__)
AGENT_PATH = os.path.abspath(os.path.join(BASE_DIR, 'agents'))
sys.path.append(AGENT_PATH)

# Import agents
from issue_classifier_agent import classify_issue
from resolver_agent import resolve_issue

app = Flask(__name__)

TICKET_FILE = 'tickets/ticket.json'
os.makedirs(os.path.dirname(TICKET_FILE), exist_ok=True)

def log_ticket(issue, category, solution):
    ticket = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "issue": issue,
        "category": category,
        "solution": solution
    }

    if not os.path.exists(TICKET_FILE) or os.path.getsize(TICKET_FILE) == 0:
        with open(TICKET_FILE, 'w') as f:
            json.dump([ticket], f, indent=4)
    else:
        with open(TICKET_FILE, 'r+') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
            data.append(ticket)
            f.seek(0)
            json.dump(data, f, indent=4)

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html", result=None)

@app.route("/submit", methods=["POST"])
def submit():
    issue_text = request.form.get("issue")
    if not issue_text:
        return render_template("index.html", result={"category": "Invalid Input", "solution": "No issue provided. Human Level intervention needed!"})

    category, reason = classify_issue(issue_text)
    resolution = resolve_issue(issue_text)

    solution = {
        "category": category,
        "solution": {
            "service": resolution.get("service"),
            "summary": resolution.get("summary"),
            "steps": resolution.get("steps"),
            "reasoning": resolution.get("reasoning")
        }
    }

    # Log the ticket
    log_ticket(issue_text, category, solution)

    return render_template("index.html", result=solution)

if __name__ == "__main__":
    app.run(debug=True)
