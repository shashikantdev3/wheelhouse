from flask import Flask, render_template, request, jsonify
import logging
from datetime import datetime
from agents import (
    SupportCrew as AgentCrew,
    infra_config
)
import json
import os
from pathlib import Path
from typing import Dict, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SupportCrew:
    def __init__(self):
        """Initialize the support crew with necessary agents"""
        self.agent_crew = AgentCrew()
        self.ticket_log = []
        self._load_tickets()
        logger.info("SupportCrew initialized with ExecutorAgent")

    def process_issue(self, issue_description: str) -> Dict:
        """Process a new issue and generate appropriate response"""
        try:
            # Create new ticket
            ticket = {
                "id": f"TICKET-{len(self.ticket_log) + 1}",
                "issue": issue_description,
                "timestamp": datetime.now().isoformat(),
                "status": "pending"
            }

            # Process the issue using the multi-agent system
            result = self.agent_crew.process_request(issue_description)
            
            # Extract category information from the result
            if result.get("status") == "success":
                ticket.update({
                    "category": result.get("type", "unknown"),
                    "service": result.get("service", "")
                })
            
            # Update ticket with result
            ticket["status"] = result.get("status", "error")
            ticket["response"] = result

            # Add to ticket log
            self.ticket_log.append(ticket)
            self._save_tickets()

            return result

        except Exception as e:
            logger.error(f"Error processing issue: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }

    def execute_remediation(self, ticket_id: str, execution_data: dict) -> dict:
        """Execute approved remediation steps"""
        try:
            # Validate ticket exists
            ticket = next((t for t in self.ticket_log if t["id"] == ticket_id), None)
            if not ticket:
                raise ValueError(f"Ticket {ticket_id} not found")

            # Execute remediation
            result = self.agent_crew.execute_resolution(execution_data)
            
            # Update ticket with execution result
            if ticket:
                ticket["execution_result"] = result
                ticket["status"] = "completed" if result.get("status") == "completed" else "failed"
                self._save_tickets()

            return result

        except Exception as e:
            logger.error(f"Error during remediation execution: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }

    def get_ticket_log(self) -> List[Dict]:
        """Get the ticket history"""
        return self.ticket_log

    def _load_tickets(self):
        """Load tickets from file"""
        try:
            ticket_file = os.path.join(os.path.dirname(__file__), 'tickets', 'ticket.json')
            os.makedirs(os.path.dirname(ticket_file), exist_ok=True)
            
            if os.path.exists(ticket_file):
                with open(ticket_file, 'r') as f:
                    self.ticket_log = json.load(f)
            else:
                self.ticket_log = []
                
        except Exception as e:
            logger.error(f"Error loading tickets: {str(e)}", exc_info=True)
            self.ticket_log = []

    def _save_tickets(self):
        """Save tickets to file"""
        try:
            ticket_file = os.path.join(os.path.dirname(__file__), 'tickets', 'ticket.json')
            os.makedirs(os.path.dirname(ticket_file), exist_ok=True)
            
            with open(ticket_file, 'w') as f:
                json.dump(self.ticket_log, f, indent=2)
            logger.info(f"Saved {len(self.ticket_log)} tickets to {ticket_file}")
            
        except Exception as e:
            logger.error(f"Error saving tickets: {str(e)}", exc_info=True)

# Example usage
if __name__ == "__main__":
    crew = SupportCrew()
    print("Autonomous IT Support Agent\nType 'exit' to quit.\n")
    
    while True:
        try:
            user_issue = input("Describe your issue: ")
            if user_issue.strip().lower() in ["exit", "quit"]:
                break
            result = crew.process_issue(user_issue)
            print("\n--- Result ---")
            print(json.dumps(result, indent=2))
        except KeyboardInterrupt:
            print("\nExiting gracefully...")
            break
        except Exception as e:
            print(f"\nError: {str(e)}")
