from flask import Flask, render_template, request
import os
import json
from datetime import datetime
import uuid

app = Flask(__name__)

# Path for ticket log file
TICKET_FILE = 'tickets/ticket.json'
os.makedirs(os.path.dirname(TICKET_FILE), exist_ok=True)

# Helper to log ticket to JSON
def log_ticket(issue, category, solution):
    ticket = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "issue": issue,
        "category": category,
        "solution": solution
    }

    # Create file with first entry if new or empty
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
            f.truncate()

# Home page
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

# Handle form submission
@app.route('/submit', methods=['POST'])
def submit():
    issue = request.form['issue'].strip()

    # Simple mock logic for classification and resolution
    if 'vpn' in issue.lower():
        category = "VPN Issue"
        solution = "Try restarting your VPN and check your network access."
    elif 'disk' in issue.lower():
        category = "Disk Cleanup"
        solution = "Clear temporary files and run the Disk Cleanup utility."
    else:
        category = "General"
        solution = "Thank you for reporting. A technician will follow up soon."

    # Log the ticket
    log_ticket(issue, category, solution)

    result = {
        "category": category,
        "solution": solution
    }
    return render_template('index.html', result=result)

if __name__ == '__main__':
    app.run(debug=True)
