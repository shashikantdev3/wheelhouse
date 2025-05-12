from crewai import Crew, Task
from agents import (
    classify_issue,
    general_query_handler,
    resolve_issue,
    validate_resolution
)
import json

class SupportCrew:
    def __init__(self):
        self.ticket_log = []

    def handle_issue(self, user_input: str) -> dict:
        ticket = {"issue": user_input}

        # Step 1: Classify the issue
        category, reason = classify_issue(user_input)
        ticket["category"] = category
        ticket["classification_reason"] = reason

        if category == "general_query":
            result = general_query_handler(user_input)
            ticket["response"] = result
            self.ticket_log.append(ticket)
            return result

        elif category == "needs_resolution":
            resolution = resolve_issue(user_input)
            ticket["resolution"] = resolution

            # Step 2: Validate the resolution
            validation = validate_resolution(resolution)
            ticket["validation"] = validation

            if validation.get("approved"):
                ticket["execution"] = "Resolution approved. No further steps required."
            else:
                ticket["execution"] = "Resolution not approved."

            self.ticket_log.append(ticket)
            return ticket

        else:
            ticket["error"] = "Uncategorized issue."
            self.ticket_log.append(ticket)
            return {"error": "Could not classify the issue."}

    def get_ticket_log(self) -> list:
        return self.ticket_log


# Example usage
if __name__ == "__main__":
    crew = SupportCrew()
    print("Autonomous IT Support Agent\nType 'exit' to quit.\n")
    while True:
        user_issue = input("Describe your issue: ")
        if user_issue.strip().lower() in ["exit", "quit"]:
            break
        result = crew.handle_issue(user_issue)
        print("\n--- Result ---")
        print(json.dumps(result, indent=2))
