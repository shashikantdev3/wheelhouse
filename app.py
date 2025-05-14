from flask import Flask, render_template, request, jsonify
import logging
from datetime import datetime
from orchestrator import SupportCrew

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
        return render_template(
            'index.html',
            ticket_log=support_crew.get_ticket_log()
        )
    except Exception as e:
        logger.error(f"Error rendering index: {str(e)}", exc_info=True)
        return render_template('error.html', error=str(e))

@app.route('/submit_issue', methods=['POST'])
def submit_issue():
    """Handle issue submission"""
    try:
        user_input = request.form.get('issue_description', '')
        if not user_input.strip():
            return jsonify({
                'status': 'error',
                'message': 'Issue description cannot be empty'
            }), 400

        # Process the issue
        result = support_crew.handle_issue(user_input)
        
        if result.get('type') == 'knowledge_query':
            return jsonify({
                'status': 'success',
                'type': 'knowledge_query',
                'data': {
                    'response': result.get('response', 'No information available.')
                }
            })
        
        elif result.get('type') == 'api_query':
            return jsonify({
                'status': 'success',
                'type': 'api_query',
                'data': {
                    'service': result.get('service'),
                    'response': result.get('response', 'No API information available.')
                }
            })
        
        elif result.get('type') == 'infrastructure_overview':
            # Return the infrastructure overview directly
            return jsonify({
                'status': result.get('status', 'success'),
                'type': 'infrastructure_overview',
                'overview': result.get('overview', {})
            })
        
        elif result.get('type') == 'infrastructure_query':
            # Return the infrastructure query result directly without wrapping in data
            return jsonify({
                'status': result.get('status', 'success'),
                'type': 'infrastructure_query',
                'results': result.get('results', {}),
                'errors': result.get('errors', []),
                'query': result.get('query', '')
            })
        
        elif result.get('type') == 'resolution':
            return jsonify({
                'status': 'success',
                'type': 'resolution',
                'data': {
                    'resolution': result.get('resolution', {}),
                    'validation': result.get('validation', {}),
                    'execution': result.get('execution', {})
                }
            })
        
        else:
            return jsonify({
                'status': 'error',
                'message': result.get('error', 'Unknown error occurred')
            }), 500

    except Exception as e:
        logger.error(f"Error processing issue: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Internal server error: {str(e)}'
        }), 500

@app.route('/approve_execution', methods=['POST'])
def approve_execution():
    """Handle execution approval"""
    try:
        ticket_id = request.form.get('ticket_id')
        execution_data = request.form.get('execution_data')
        
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
        return jsonify({
            'status': 'success',
            'tickets': support_crew.get_ticket_log()
        })
    except Exception as e:
        logger.error(f"Error fetching ticket log: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Error fetching ticket log: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
