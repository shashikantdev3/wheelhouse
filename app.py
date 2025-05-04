from flask import Flask, render_template, request
import uuid
import datetime
import json
import os

# Placeholder imports for your agent logic
# from agents.classifier_agent import classify_issue
# from agents.troubleshooter_agent import get_solution
# from agents.recorder_agent import log_ticket

app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    issue = request.form['issue']
    ticket_id = str(uuid.uuid4())
    timestamp = str(datetime.datetime.now())

    # Simulated classification and solution
    category = classify_issue(issue)  # Use your model here
    solution = get_solution(category)  # Use your model here

    ticket_data = {
        "ticket_id": ticket_id,
        "timestamp": timestamp,
        "issue": issue,
        "category": category,
        "solution": solution
    }

    # Save to JSON file
    log_ticket(ticket_data)

    return render_template('index.html', result=ticket_data)

# Dummy agent logic for now
def classify_issue(issue):
    if "vpn" in issue.lower():
        return "VPN Issue"
    elif "password" in issue.lower():
        return "Password Reset"
    return "General IT"

def get_solution(category):
    return {
        "VPN Issue": "Restart VPN service and check credentials.",
        "Password Reset": "Guide user to reset password via portal.",
        "General IT": "Escalate to IT Helpdesk."
    }.get(category, "Escalate to IT Helpdesk.")

def log_ticket(data):
    os.makedirs("tickets", exist_ok=True)
    file_path = "tickets/ticket_log.json"
    existing = []
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            existing = json.load(f)
    existing.append(data)
    with open(file_path, 'w') as f:
        json.dump(existing, f, indent=4)

if __name__ == '__main__':
    app.run(debug=True)
