from crewai import Task
from agents import (
    classify_issue,
    general_query_handler,
    resolve_issue,
    validate_resolution
)

class TaskFactory:
    def __init__(self):
        pass

    def create_issue_classification_task(self, user_input: str):
        return Task(
            description="Classify the issue as general_query or needs_resolution",
            expected_output="A JSON object with category and reasoning",
            agent="classifier_agent",
            async_execution=False,
            allow_delegation=True,
            run=lambda: classify_issue(user_input)
        )

    def create_general_query_task(self, user_query: str):
        return Task(
            description="Handle general infrastructure query and respond with information",
            expected_output="A dictionary with infrastructure status output",
            agent="general_query_agent",
            async_execution=False,
            allow_delegation=True,
            run=lambda: general_query_handler(user_query)
        )

    def create_resolution_task(self, issue_text: str):
        return Task(
            description="Generate a resolution plan for the given issue",
            expected_output="A JSON resolution plan including summary, steps, and reasoning",
            agent="resolver_agent",
            async_execution=False,
            allow_delegation=True,
            run=lambda: resolve_issue(issue_text)
        )

    def create_validation_task(self, resolution: dict):
        return Task(
            description="Validate the resolution steps and confirm safety",
            expected_output="Validation result and notes",
            agent="validator_agent",
            async_execution=False,
            allow_delegation=True,
            run=lambda: validate_resolution(resolution)
        )
