from flask import Flask, render_template, request, redirect, url_for, session
from agents import (
    classify_issue,
    general_query_handler,
    resolve_issue,
    validate_resolution,
    ExecutorAgent,
    infra_config
)

app = Flask(__name__)
executor_agent = ExecutorAgent()

# --- Route: Landing page ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user_input = request.form['query']
        session['user_input'] = user_input

        category, reason = classify_issue(user_input)

        if category == "general_query":
            result = general_query_handler(user_input)
            return render_template('result.html', category="general_query", result=result)

        elif category == "needs_resolution":
            resolution = resolve_issue(user_input)
            validation = validate_resolution(resolution)

            session['resolution'] = resolution
            session['validation'] = validation

            if validation['approved']:
                # Find which server the service is on
                target_server = next(
                    (server for server, data in infra_config.items()
                     if resolution['service'].lower() in [svc.lower() for svc in data.get("services", [])]),
                    None
                )

                if not target_server:
                    return render_template('result.html', category="needs_resolution", result={
                        "error": "Could not find a server responsible for the affected service.",
                        "resolution": resolution,
                        "validation": validation
                    })

                session['target_server'] = target_server
                session['ip'] = infra_config[target_server]['ip']

                return render_template('permission.html',
                                       resolution=resolution,
                                       validation=validation,
                                       server=target_server)

            else:
                return render_template('result.html', category="needs_resolution", result={
                    "error": "Resolution was not approved.",
                    "resolution": resolution,
                    "validation": validation
                })

        else:
            return render_template('result.html', category="unknown", result={
                "error": "Could not classify the issue.",
                "reason": reason
            })

    return render_template('index.html')

# --- Route: Handle user permission to execute resolution ---
@app.route('/execute', methods=['POST'])
def execute_resolution():
    decision = request.form.get("decision")
    if decision == "yes":
        resolution = session.get("resolution")
        server = session.get("target_server")
        ip = session.get("ip")

        execution_result = executor_agent.execute_remediation({
            "resolution": resolution,
            "server": server,
            "ip": ip
        })

        return render_template('execution_result.html',
                               result=execution_result,
                               resolution=resolution,
                               server=server)

    return render_template('execution_result.html',
                           result="User declined to execute remediation.",
                           resolution=session.get("resolution"),
                           server=session.get("target_server"))

# --- Main ---
if __name__ == '__main__':
    app.run(debug=True)
