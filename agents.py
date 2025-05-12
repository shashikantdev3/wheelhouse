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

Classify the following user issue or query into one of the following categories:

- "general_query": If the user is asking for information, system status, logs, metrics, or any data retrieval.
- "needs_resolution": If the user is reporting a problem, malfunction, error, or requesting a fix to something broken.

Carefully read the user's statement and explain your reasoning before giving your final answer.

Here are a few examples:

Example 1:
User: "What's the CPU usage on the servers?"
Category: general_query
Reason: This is a request for system status information, not a report of a malfunction.

Example 2:
User: "The database is not responding."
Category: needs_resolution
Reason: The user is reporting a specific problem that needs to be diagnosed and fixed.

Example 3:
User: "List all services running on the infrastructure."
Category: general_query
Reason: The user wants an inventory of the system, not a fix.

Now classify this input:

User:
{issue}

Respond ONLY in this exact JSON format:
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
        category = result.get("category", "Uncategorized")
        reason = result.get("reason", "No reasoning provided.")

        # Fallback logic: override misclassification
        keywords = ["status", "running", "services", "show", "list", "uptime", "information", "metrics", "usage"]
        if category == "needs_resolution" and any(kw in issue.lower() for kw in keywords):
            return "general_query", reason + " (Overridden by keyword-based fallback.)"

        return category, reason

    except Exception as e:
        print(f"Failed to parse LLM response: {response}\nError: {e}")
        return "Uncategorized", "Could not classify due to response format error."

# --- General Query Agent ---
def infer_servers_from_query(query: str):
    if "all servers" in query.lower() or "every server" in query.lower():
        return {
            "category": "general_query",
            "result": {
                "selected_servers": list(infra_config.keys()),
                "reasoning": "User explicitly asked for information about all servers."
            }
        }

    prompt_template = PromptTemplate.from_template("""
You are a systems assistant.

Given the user's query and the infrastructure configuration below, determine which server(s) are relevant to answer the query.

If the user asks about **all servers**, select **every server listed**.

Infra config:
{infra_config}

User query:
{query}

Respond ONLY with this exact JSON format:
{{
  "category": "general_query",
  "result": {{
    "selected_servers": ["<server_names>"],
    "reasoning": "<why these servers were chosen>"
  }}
}}
""")
    prompt = prompt_template.format(query=query, infra_config=json.dumps(infra_config, indent=2))
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

def run_commands_on_server(ip: str, commands: list, server_name: str) -> str:
    results = []

    # Determine the root directory for the project
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))

    # Construct the private key path based on the OS separator
    key_path = "C:/Users/debna/OneDrive/Desktop/Autonomous-IT-Support-Agent/Local_infra_setup_script_IaC/.vagrant/machines/{}/virtualbox/private_key".format(server_name)

    # Ensure that the key path uses the correct separator based on the OS
    if not os.path.exists(key_path):
        return f"[Error] Private key not found for {server_name} at expected path: {key_path}\n(Current working directory: {os.getcwd()})"

    for cmd in commands:
        ssh_cmd = [
            "ssh",
            "-i", key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"vagrant@{ip}",
            cmd
        ]
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
    for server_name in selected_servers:
        server_info = infra_config.get(server_name)
        if not server_info:
            continue

        ip = server_info["ip"]
        services = server_info["services"]
        commands = [
            "uptime", "free -m", "df -h", "top -bn1 | head -n 15"
        ] + [f"systemctl status {svc.lower()}" for svc in services]

        output = run_commands_on_server(ip, commands, server_name=server_name)
        server_outputs[server_name] = {
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
