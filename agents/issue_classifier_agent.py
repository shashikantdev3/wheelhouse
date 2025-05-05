from langchain.llms import Ollama
from langchain.prompts import PromptTemplate
import json

llm = Ollama(model="mistral")  # Or llama3 if installed

template = PromptTemplate.from_template("""
You are an IT support agent. Classify the following issue into a support category, and provide a short reason.

Issue: {issue}

Respond in JSON format:
{{
  "category": "...",
  "reason": "..."
}}
""")

def classify_issue(issue):
    prompt = template.format(issue=issue)
    response = llm(prompt)
    try:
        result = json.loads(response)
        return result["category"], result["reason"]
    except Exception as e:
        return "Uncategorized", "LLM response could not be parsed."
