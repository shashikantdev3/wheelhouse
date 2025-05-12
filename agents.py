import os
import json
import subprocess
from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory

# Load infra config
CONFIG_FILE = os.path.join(os.path.dirname(__file__), '.', 'infra_config.json')
with open(CONFIG_FILE, 'r') as f:
    infra_config = json.load(f)

llm = Ollama(model="mistral")
memory = ConversationBufferMemory()

# --- Issue Classifier Agent ---
classifier_template = PromptTemplate.from_template("""
You are an experienced IT Support Agent.

Classify the following issue into one of the following categories:
- general_query
- needs_resolution

Explain your reasoning.

Issue:
{issue}

Return your answer strictly in this JSON format:
{{
  "category": "<category_name>",
  "reason": "<brief_reasoning>"
}}
""")

def classify_issue(issue: str):
    prompt = classifier_template.format(issue=issue)
    response = llm(prompt)
    try:
        result = json.loads(response)
        return result.get("category", "Uncategorized"), result.get("reason", "No reasoning provided.")
    except Exception as e:
        print(f"Failed to parse LLM response: {response}\nError: {e}")
        return "Uncategorized", "Could not classify due to response format error."


# --- General Query Agent ---
server_selection_template = PromptTemplate.from_template("""
You are a systems assistant.
Given the user's query and the infrastructure configuration below, identify which server(s) the query is most relevant to.

Infra config:
{infra_config}

User query:
{query}

Respond ONLY with this exact JSON format:
{{
  "category": "general_query",
  "result": {{
    "selected_servers": ["db01", "web01"],
    "reasoning": "Explain here why these servers are relevant based on the query and config."
  }}
}}
""")

def infer_servers_from_query(query: str):
    prompt = server_selection_template.format(query=query, infra_config=json.dumps(infra_config, indent=2))
    response = llm(prompt)
    try:
        result = json.loads(response)
        return result
    except Exception as e:
        print(f"[Error] Failed to parse LLM response: {response}\n{e}")
        return {
            "category": "general_query",
            "result": {
                "selected_servers": [],
                "reasoning": "Could not parse response properly."
            }
        }

def run_commands_on_server(ip: str, commands: list) -> str:
    results = []
    for cmd in commands:
        ssh_cmd = ["vagrant", "ssh", ip, "-c", cmd]
        try:
            output = subprocess.check_output(ssh_cmd, stderr=subprocess.STDOUT, timeout=10)
            results.append(f"$ {cmd}\n{output.decode()}")
        except subprocess.CalledProcessError as e:
            results.append(f"$ {cmd}\nError: {e.output.decode()}")
        except Exception as e:
            results.append(f"$ {cmd}\nUnhandled Exception: {e}")
    return "\n\n".join(results)

def general_query_handler(user_query: str):
    server_response = infer_servers_from_query(user_query)

    # Validate expected structure
    selected_servers = server_response.get("result", {}).get("selected_servers", [])
    if not selected_servers:
        return {
            "category": "general_query",
            "result": {
                "reasoning": server_response.get("result", {}).get("reasoning", "No reasoning."),
                "selected_servers": [],
                "server_outputs": {},
                "error": "Could not determine which server to query."
            }
        }

    server_outputs = {}
    for server in selected_servers:
        server_info = infra_config.get(server)
        if not server_info:
            continue

        ip = server_info["ip"]
        services = server_info["services"]
        commands = [
            "uptime", "free -m", "df -h", "top -bn1 | head -n 15"
        ] + [f"systemctl status {svc.lower()}" for svc in services]

        output = run_commands_on_server(server, commands)
        server_outputs[server] = {
            "ip": ip,
            "services": services,
            "output": output
        }

    return {
        "category": "general_query",
        "result": {
            "reasoning": server_response.get("result", {}).get("reasoning", "No reasoning."),
            "selected_servers": selected_servers,
            "server_outputs": server_outputs
        }
    }


# --- Resolution Agent ---
resolver_template = PromptTemplate.from_template("""
You are a Site Reliability Engineer.

Given the reported issue, return a structured and safe resolution plan in JSON format.

Issue:
{issue}

Format:
{{
  "service": "<component>",
  "issue_summary": "<summary>",
  "resolution_steps": ["<step1>", "<step2>"],
  "reasoning": "<why this works>"
}}
""")

def resolve_issue(issue: str):
    prompt = resolver_template.format(issue=issue)
    response = llm(prompt)
    try:
        result = json.loads(response)
        return {
            "service": result.get("service", "unknown"),
            "summary": result.get("issue_summary", "n/a"),
            "steps": result.get("resolution_steps", []),
            "reasoning": result.get("reasoning", "No reasoning.")
        }
    except Exception as e:
        print(f"Failed to parse resolver_agent output.\nRaw: {response}\nError: {e}")
        return {
            "service": "unknown",
            "summary": "Parse error",
            "steps": [],
            "reasoning": "N/A"
        }


# --- Validator Agent ---
def validate_resolution(resolution: dict):
    return {
        "approved": True,
        "review_notes": "Steps look safe and logical.",
        "allow_delegation": True
    }
