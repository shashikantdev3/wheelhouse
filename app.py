from flask import Flask, render_template, request, redirect, url_for, session
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
app.secret_key = 'your_secret_key_here'  # Required for session

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

    category = output.get("category", "Uncategorized")
    result = output.get("result", {})
    resolution = output.get("resolution", None)
    validation = output.get("validation", None)
    execution = output.get("execution", None)

    response = {
        "category": category,
        "result": result,
    }
    if resolution:
        response["resolution"] = resolution
    if validation:
        response["validation"] = validation
    if execution:
        response["execution"] = execution

    # If execution needs user confirmation, redirect to confirmation page
    if execution and isinstance(execution, dict) and execution.get("status") == "awaiting_user_approval":
        session['pending_action'] = {
            "issue": issue_text,
            "category": category,
            "resolution": resolution,
            "validation": validation,
            "execution": execution
        }
        return redirect(url_for('confirm'))

    # Otherwise, save and show result directly
    save_ticket(issue_text, response)
    return render_template("index.html", result=response)

@app.route("/confirm", methods=["GET"])
def confirm():
    data = session.get('pending_action')
    if not data:
        return redirect(url_for('home'))
    return render_template("confirm.html", data=data)

@app.route("/confirm_action", methods=["POST"])
def confirm_action():
    decision = request.form.get("decision")
    data = session.pop('pending_action', None)

    if not data:
        return redirect(url_for('home'))

    if decision == "yes":
        execution_result = crew.executor.execute_remediation(data["execution"])
        data["execution"] = execution_result
    else:
        data["execution"] = {"status": "cancelled_by_user", "message": "User declined execution."}

    save_ticket(data["issue"], data)
    return render_template("index.html", result=data)

def save_ticket(issue_text, response):
    ticket = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "issue": issue_text,
        "response": response
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

if __name__ == "__main__":
    app.run(debug=True)
