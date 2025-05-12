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

# Import orchestrator
from orchestrator import SupportCrew

app = Flask(__name__)

TICKET_FILE = 'tickets/ticket.json'
os.makedirs(os.path.dirname(TICKET_FILE), exist_ok=True)

crew = SupportCrew()

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html", result=None)

@app.route("/submit", methods=["POST"])
def submit():
    issue_text = request.form.get("issue")
    if not issue_text:
        return render_template("index.html", result={
            "category": "Invalid Input",
            "result": {"reasoning": "No issue provided. Human intervention required."}
        })

    output = crew.handle_issue(issue_text)

    # Normalize output to include expected structure
    result = {
        "category": output.get("category", "Uncategorized"),
        "result": output.get("result", {}),
        "resolution": output.get("resolution"),
        "validation": output.get("validation"),
        "execution": output.get("execution")
    }

    # Print the normalized result object for debugging
    print("Result object:", json.dumps(result, indent=2))

    # Log ticket
    ticket = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "issue": issue_text,
        "result": result
    }

    try:
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
    except Exception as e:
        print(f"Failed to log ticket: {e}")

    return render_template("index.html", result=result)

if __name__ == "__main__":
    app.run(debug=True)
