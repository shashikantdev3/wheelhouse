from flask import Flask, render_template, request
import os
import json
from datetime import datetime
import uuid
import sys

Add agents path
sys.path.append('./.agents')
from issue_classifier_agent import classify_issue

app = Flask(name)

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
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    issue = request.form['issue']
    category, reason = classify_issue(issue)
    solution = f"Category: {category}\nReason: {reason}"


    log_ticket(issue, category, solution)

    result = {
        "category": category,
        "solution": solution
    }
    return render_template('index.html', result=result)
if __name__ == 'main':
    app.run(debug=True)