from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
import json

llm = Ollama(model="mistral")

template = PromptTemplate.from_template("""
You are an elite Site Reliability Engineer (SRE) AI agent.

Your task is to troubleshoot and resolve complex IT infrastructure issues across operating systems, cloud platforms (AWS, GCP, Azure), databases, containers, networks, DevOps pipelines, application servers, and security.

Given the reported issue below, return a structured, safe resolution plan.

Issue:
{issue}

Respond only in valid JSON format:
{{
  "service": "<name of the primary affected component or system>",
  "issue_summary": "<brief root cause in plain English>",
  "resolution_steps": [
    "<Shell, CLI, API, or config steps to fix>",
    "<Make sure commands are idempotent and non-destructive>"
  ],
  "reasoning": "<why these steps will likely fix the issue>"
}}
""")

def resolve_issue(issue: str):
    prompt = template.format(issue=issue)
    response = llm(prompt)
    try:
        result = json.loads(response)
        return {
            "service": result.get("service", "unknown"),
            "summary": result.get("issue_summary", "not available"),
            "steps": result.get("resolution_steps", []),
            "reasoning": result.get("reasoning", "No reasoning provided.")
        }
    except Exception as e:
        print(f"Failed to parse resolver_agent LLM output.\nRaw output:\n{response}\nError: {e}")
        return {
            "service": "unknown",
            "summary": "Could not parse issue",
            "steps": [],
            "reasoning": "Format error"
        }
