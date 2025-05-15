from flask import Flask, render_template, request, jsonify
import logging
from datetime import datetime
from orchestrator import SupportCrew
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
support_crew = SupportCrew()

@app.route('/')
def index():
    """Render the main dashboard"""
    try:
        tickets = support_crew.get_ticket_log()
        return render_template(
            'index.html',
            ticket_log=tickets
        )
    except Exception as e:
        logger.error(f"Error rendering index: {str(e)}", exc_info=True)
        return render_template('error.html', error=str(e))

@app.route('/submit_issue', methods=['POST'])
def submit_issue():
    """Handle issue submission"""
    try:
        issue_description = request.form.get('issue_description')
        if not issue_description:
            return jsonify({
                'status': 'error',
                'message': 'No issue description provided'
            }), 400

        # Process the issue
        result = support_crew.process_issue(issue_description)
        logger.info(f"Received result from support_crew: {result}")

        # Prepare response
        response = {
            'status': result.get('status', 'error'),
            'type': result.get('type', 'unknown'),
            'ticket_log': support_crew.get_ticket_log()
        }
        
        # Add type-specific data
        if result.get('type') == 'knowledge_query':
            summary = result.get('results', {}).get('summary', 'No answer available')
            # Format summary for HTML display if from knowledge base or LLM (preserve line breaks)
            source = result.get('results', {}).get('source', 'web search')
            if source in ['built-in knowledge base', 'llm_knowledge']:
                summary = summary.replace('\n', '<br>')
            
            response['data'] = {
                'summary': summary,
                'related_topics': result.get('results', {}).get('related_topics', []),
                'query': result.get('query', issue_description),
                'source': source
            }
        elif result.get('type') == 'api_query':
            response.update({
                'service': result.get('service', ''),
                'data': result.get('data', {})
            })
        elif result.get('type') == 'infrastructure_query':
            # Extract command results for better formatting
            infrastructure_data = []
            for server_name, server_info in result.get('results', {}).items():
                server_data = {
                    'server': server_name,
                    'ip': server_info.get('ip', 'Unknown'),
                    'services': server_info.get('services', []),
                    'status': 'error',
                    'output': 'No output available'
                }
                
                # Process command outputs
                commands = server_info.get('commands', [])
                if commands:
                    cmd_result = commands[0]  # Usually just one command per query
                    server_data['status'] = 'success' if cmd_result.get('success', False) else 'error'
                    server_data['output'] = cmd_result.get('output', 'No output available')
                
                infrastructure_data.append(server_data)
                
            response.update({
                'results': result.get('results', {}),
                'data': infrastructure_data,
                'service': result.get('service', '')
            })
        elif result.get('type') == 'resolution':
            resolution_data = result.get('resolution', {})
            validation_data = result.get('validation', {})
            
            response['data'] = {
                'resolution': resolution_data,
                'validation': validation_data,
                'approved': validation_data.get('approved', False),
                'confidence': validation_data.get('confidence', 0.0),
                'risks': validation_data.get('risks_identified', []),
                'suggestions': validation_data.get('suggested_modifications', [])
            }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error processing issue: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/approve_execution', methods=['POST'])
def approve_execution():
    """Handle execution approval"""
    try:
        ticket_id = request.form.get('ticket_id')
        execution_data = json.loads(request.form.get('execution_data'))
        
        if not ticket_id or not execution_data:
            return jsonify({
                'status': 'error',
                'message': 'Missing ticket ID or execution data'
            }), 400

        # Execute the approved steps
        result = support_crew.execute_remediation(ticket_id, execution_data)
        
        return jsonify({
            'status': 'success',
            'data': result
        })

    except Exception as e:
        logger.error(f"Error during execution: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Execution error: {str(e)}'
        }), 500

@app.route('/ticket_log')
def ticket_log():
    """Get the ticket history"""
    try:
        tickets = support_crew.get_ticket_log()
        return jsonify({
            'status': 'success',
            'tickets': tickets
        })
    except Exception as e:
        logger.error(f"Error fetching ticket log: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Error fetching ticket log: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
