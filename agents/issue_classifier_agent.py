from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
import json

llm = Ollama(model="mistral")

template = PromptTemplate.from_template("""
You are an experienced IT Support Agent.

Classify the following issue into a known IT support category and briefly explain your reasoning.

Issue:
{issue}

Return your answer strictly in this JSON format:
{{
"category": "<category_name>",
"reason": "<brief_reasoning>"
}}
""")

def classify_issue(issue: str):
    prompt = template.format(issue=issue)
    response = llm(prompt)
    try:
        result = json.loads(response)
        return result.get("category", "Uncategorized"), result.get("reason", "No reasoning provided.")
    except Exception as e:
        print(f"Failed to parse LLM response: {response}\nError: {e}")
        return "Uncategorized", "Could not classify due to response format error."
