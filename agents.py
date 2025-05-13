import os
import json
import subprocess
from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory
from langchain.chains import LLMChain

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

        keywords = ["status", "running", "services", "show", "list", "uptime", "information", "metrics", "usage"]
        if category == "needs_resolution" and any(kw in issue.lower() for kw in keywords):
            return "general_query", reason + " (Overridden by keyword-based fallback.)"

        return category, reason
    except Exception as e:
        print(f"Failed to parse LLM response: {response}\nError: {e}")
        return "Uncategorized", "Could not classify due to response format error."

# --- General Query Agent ---
keyword_command_map = {
    "uptime": ["uptime"],
    "cpu usage": ["top -bn1 | grep '%Cpu' || top -bn1 | head -n 15"],
    "memory usage": ["free -m"],
    "disk usage": ["df -h"],
    "list services": ["systemctl list-units --type=service --state=running"],
    "status": ["uptime", "free -m", "df -h"],
    "running services": ["systemctl list-units --type=service --state=running"]
}

def infer_query_commands(query: str, services: list) -> list:
    query_lower = query.lower()
    for keyword, commands in keyword_command_map.items():
        if keyword in query_lower:
            return commands
    return ["uptime"] + [f"systemctl status {svc.lower()}" for svc in services]

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
        return json.loads(response)
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
    key_path = f"C:/Users/debna/OneDrive/Desktop/Autonomous-IT-Support-Agent/Local_infra_setup_script_IaC/.vagrant/machines/{server_name}/virtualbox/private_key"
    if not os.path.exists(key_path):
        return f"[Error] Private key not found for {server_name} at expected path: {key_path}\n(Current working directory: {os.getcwd()})"

    results = []
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
        commands = infer_query_commands(user_query, services)

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

# --- LLM-Powered Validator Agent ---
validation_prompt = PromptTemplate.from_template("""
You are an IT operations expert responsible for reviewing automated resolution steps.

Resolution Details:
Service: {service}
Steps:
{steps}

Your job is to determine if these steps are safe and reasonable to execute automatically.

Respond strictly in this JSON format:
{{
  "approved": true or false,
  "review_notes": "Brief justification",
  "allow_delegation": true or false
}}
""")

validation_chain = LLMChain(llm=llm, prompt=validation_prompt)

def validate_resolution(resolution: dict):
    service = resolution.get("service", "")
    steps = resolution.get("steps", [])

    if not steps:
        return {
            "approved": False,
            "review_notes": "No resolution steps provided.",
            "allow_delegation": False
        }

    steps_text = "\n".join(f"- {step}" for step in steps)
    try:
        response = validation_chain.run(service=service, steps=steps_text)
        return json.loads(response)
    except Exception as e:
        print(f"[Validator Error] Failed to parse LLM output:\n{response}\nError: {e}")
        return {
            "approved": False,
            "review_notes": "Validation agent returned an invalid response.",
            "allow_delegation": False
        }

# --- Executor Agent ---
def executor_agent(resolution: dict, server_name: str, ip: str):
    script = " && ".join(resolution.get("steps", []))
    key_path = f"C:/Users/debna/OneDrive/Desktop/Autonomous-IT-Support-Agent/Local_infra_setup_script_IaC/.vagrant/machines/{server_name}/virtualbox/private_key"
    if not os.path.exists(key_path):
        return f"[Error] Private key not found for {server_name} at expected path: {key_path}"

    ssh_cmd = [
        "ssh",
        "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        f"vagrant@{ip}",
        script
    ]

    try:
        output = subprocess.check_output(ssh_cmd, stderr=subprocess.STDOUT, timeout=30)
        return output.decode()
    except subprocess.CalledProcessError as e:
        return f"Command failed:\n{e.output.decode()}"
    except Exception as e:
        return f"Unhandled exception:\n{str(e)}"
