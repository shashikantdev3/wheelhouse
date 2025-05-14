from agents import (
    classify_issue,
    general_query_handler,
    resolve_issue,
    validate_resolution,
    ExecutorAgent,
    infra_config
)
import json
import logging
import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SupportCrew:
    def __init__(self):
        self.ticket_log = []
        self.executor_agent = ExecutorAgent()  # Initialize the ExecutorAgent
        logger.info("SupportCrew initialized with ExecutorAgent")

    def handle_issue(self, user_input: str) -> dict:
        """Handle user issues and queries with improved error handling"""
        if not user_input or not user_input.strip():
            return {
                "status": "error",
                "error": "Empty query provided"
            }

        ticket = {
            "issue": user_input,
            "timestamp": datetime.datetime.now().isoformat()
        }
        logger.info(f"Processing new ticket: {user_input[:100]}...")

        try:
            # Step 1: Classify the issue
            category, reason, service = classify_issue(user_input)
            if category == "uncategorized":
                return {
                    "status": "error",
                    "error": reason
                }

            ticket["category"] = category
            ticket["classification_reason"] = reason
            ticket["service"] = service
            logger.info(f"Issue classified as: {category}")

            # Handle different query types
            if category in ["general_query", "api_query", "knowledge_query"]:
                result = general_query_handler(user_input)
                if not result:
                    return {
                        "status": "error",
                        "error": "Failed to process query"
                    }
                
                if result.get("status") == "error":
                    return result

                # If it's an infrastructure overview, return it directly
                if result.get("type") == "infrastructure_overview":
                    ticket["response"] = result
                    self.ticket_log.append(ticket)
                    return result

                # For other query types
                ticket["response"] = result
                self.ticket_log.append(ticket)
                return result

            elif category == "needs_resolution":
                # Step 2: Generate resolution plan
                resolution = resolve_issue(user_input)
                if not resolution or resolution.get("status") == "error":
                    return {
                        "status": "error",
                        "error": resolution.get("error", "Failed to generate resolution plan")
                    }

                ticket["resolution"] = resolution
                logger.info("Resolution plan generated")

                # Step 3: Validate the resolution
                validation = validate_resolution(resolution)
                if not validation:
                    return {
                        "status": "error",
                        "error": "Failed to validate resolution plan"
                    }

                ticket["validation"] = validation
                logger.info(f"Resolution validation: {'approved' if validation.get('approved') else 'rejected'}")

                # Add the ticket to the log
                self.ticket_log.append(ticket)

                return {
                    "status": "success",
                    "type": "resolution",
                    "resolution": resolution,
                    "validation": validation
                }

            else:
                return {
                    "status": "error",
                    "error": f"Unsupported query category: {category}"
                }

        except Exception as e:
            logger.error(f"Error in handle_issue: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }

    def execute_remediation(self, ticket_id: str, execution_data: dict) -> dict:
        """
        Execute approved remediation steps with proper logging and error handling
        """
        logger.info(f"Executing remediation for ticket {ticket_id}")
        try:
            result = self.executor_agent.execute_remediation(execution_data)
            logger.info(f"Remediation execution completed for ticket {ticket_id}")
            return result
        except Exception as e:
            logger.error(f"Error executing remediation for ticket {ticket_id}: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }

    def get_ticket_log(self) -> list:
        return self.ticket_log

# Example usage
if __name__ == "__main__":
    crew = SupportCrew()
    print("Autonomous IT Support Agent\nType 'exit' to quit.\n")
    
    while True:
        try:
            user_issue = input("Describe your issue: ")
            if user_issue.strip().lower() in ["exit", "quit"]:
                break
            result = crew.handle_issue(user_issue)
            print("\n--- Result ---")
            print(json.dumps(result, indent=2))
        except KeyboardInterrupt:
            print("\nExiting gracefully...")
            break
        except Exception as e:
            print(f"\nError: {str(e)}")
