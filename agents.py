import os
import json
import subprocess
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory
from langchain.chains import LLMChain
import datetime
import requests
from urllib.parse import quote_plus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load infra config
try:
    CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'infra_config.json')
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Configuration file not found: {CONFIG_FILE}")
        
    with open(CONFIG_FILE, 'r') as f:
        infra_config = json.load(f)
        
    if not isinstance(infra_config, dict):
        raise ValueError("Invalid configuration format: expected a dictionary")
        
    # Validate the configuration
    required_fields = ["ip", "os", "services"]
    for server, config in infra_config.items():
        missing_fields = [field for field in required_fields if field not in config]
        if missing_fields:
            raise ValueError(f"Missing required fields {missing_fields} in configuration for server {server}")
            
    logger.info(f"Successfully loaded configuration for {len(infra_config)} servers")
except Exception as e:
    logger.error(f"Error loading infrastructure configuration: {str(e)}", exc_info=True)
    infra_config = {}  # Initialize with empty dict to prevent NoneType errors

llm = Ollama(model="mistral")
memory = ConversationBufferMemory()

@dataclass
class ServerCommand:
    command: str
    timeout: int = 30
    expected_return_code: int = 0

# Enhanced command mapping with timeouts and expected return codes
COMMAND_GROUPS = {
    "basic_health": [
        ServerCommand("uptime", timeout=5),
        ServerCommand("free -m", timeout=5),
        ServerCommand("df -h", timeout=5)
    ],
    "service_status": [
        ServerCommand("systemctl status {service} || service {service} status", timeout=10),
        ServerCommand("ps aux | grep -i {service} || true", timeout=10)
    ],
    "logs": [
        ServerCommand("journalctl -u {service} --no-pager -n 50", timeout=15),
        ServerCommand("tail -n 50 /var/log/{service}/*.log 2>/dev/null || true", timeout=10)
    ],
    "network": [
        ServerCommand("ss -tunlp", timeout=10),
        ServerCommand("netstat -nlp", timeout=10)
    ],
    "process": [
        ServerCommand("top -bn1 | head -n 15", timeout=10),
        ServerCommand("ps aux | sort -rk 3,3 | head -n 10", timeout=10)
    ],
    "nginx": [
        ServerCommand("nginx -t", timeout=5),
        ServerCommand("systemctl status nginx || service nginx status", timeout=10),
        ServerCommand("curl -I localhost", timeout=5),
        ServerCommand("cat /etc/nginx/nginx.conf", timeout=5),
        ServerCommand("nginx -V", timeout=5)
    ]
}

# Knowledge Base for Common APIs and Services
KNOWLEDGE_BASE = {
    "servicenow": {
        "base_url": "https://instance.service-now.com/api",
        "common_endpoints": {
            "incident": "/now/table/incident",
            "problem": "/now/table/problem",
            "change_request": "/now/table/change_request",
            "user": "/now/table/sys_user",
            "group": "/now/table/sys_user_group"
        },
        "auth_method": "Basic/OAuth",
        "docs_url": "https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/"
    },
    "ansible": {
        "base_url": "http://ansible-tower/api/v2",
        "common_endpoints": {
            "inventory": "/inventories/",
            "job_templates": "/job_templates/",
            "projects": "/projects/",
            "jobs": "/jobs/",
            "hosts": "/hosts/"
        },
        "auth_method": "OAuth2/Token",
        "docs_url": "https://docs.ansible.com/ansible-tower/latest/html/towerapi/api_ref.html"
    }
}

# --- Issue Classifier Agent ---
classifier_template = PromptTemplate.from_template("""You are an experienced IT Support Agent.

Classify the following user issue or query into one of the following categories:

- "general_query": If the user is asking for information about infrastructure, system status, logs, metrics, or any data retrieval.
- "knowledge_query": If the user is asking any general question that requires searching the internet or knowledge bases.
- "api_query": If the user is asking about API endpoints, documentation, or integration details.
- "needs_resolution": If the user is reporting a problem, malfunction, error, or requesting a fix to something broken.

Consider these examples:
1. "Show me the status of nginx" → general_query
2. "What are the ServiceNow API endpoints?" → api_query
3. "Nginx is returning 502 errors" → needs_resolution
4. "How do I integrate with Ansible Tower API?" → api_query
5. "What's the CPU usage on app01?" → general_query
6. "What is the difference between Docker and Kubernetes?" → knowledge_query
7. "Explain how load balancing works" → knowledge_query
8. "MySQL keeps crashing on db01" → needs_resolution

User Issue: {issue}

Respond ONLY in this exact JSON format:
{{
  "category": "<category_name>",
  "reason": "<brief_reasoning>",
  "confidence": <0.0-1.0>,
  "service": "<service_name_if_applicable>",
  "search_query": "<search_query_if_knowledge_query>"
}}""")

def get_api_information(service: str, query: str) -> Dict:
    """Get API information from knowledge base or web search"""
    service = service.lower()
    
    # Check knowledge base first
    if service in KNOWLEDGE_BASE:
        return {
            "status": "success",
            "source": "knowledge_base",
            "data": KNOWLEDGE_BASE[service]
        }
    
    # If not in knowledge base, search online
    try:
        search_query = f"{service} API documentation endpoints"
        search_url = f"https://api.duckduckgo.com/?q={quote_plus(search_query)}&format=json"
        response = requests.get(search_url)
        
        if response.status_code == 200:
            return {
                "status": "success",
                "source": "web_search",
                "data": {
                    "search_results": response.json(),
                    "query": search_query
                }
            }
        else:
            return {
                "status": "error",
                "error": "Failed to fetch online documentation"
            }
    except Exception as e:
        logger.error(f"Error searching API documentation: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }

def get_knowledge_information(query: str) -> Dict:
    """Get information from web search for knowledge queries"""
    try:
        # Perform web search
        search_url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json"
        response = requests.get(search_url)
        
        if response.status_code == 200:
            data = response.json()
            
            # Initialize response structure
            formatted_response = {
                "main_answer": "",
                "related_information": []
            }
            
            # Try different fields in order of relevance
            if data.get('Abstract'):
                formatted_response["main_answer"] = data['Abstract']
            elif data.get('AbstractText'):
                formatted_response["main_answer"] = data['AbstractText']
            elif data.get('Definition'):
                formatted_response["main_answer"] = data['Definition']
            elif data.get('Answer'):
                formatted_response["main_answer"] = data['Answer']
            
            # If no direct answer found, try to extract from RelatedTopics
            if not formatted_response["main_answer"] and data.get('RelatedTopics'):
                for topic in data['RelatedTopics']:
                    if isinstance(topic, dict) and topic.get('Text'):
                        formatted_response["main_answer"] = topic['Text']
                        break
            
            # If still no answer, set a default message
            if not formatted_response["main_answer"]:
                formatted_response["main_answer"] = "No direct answer found for your query."
            
            # Add related information
            if data.get('RelatedTopics'):
                for topic in data['RelatedTopics']:
                    if isinstance(topic, dict) and topic.get('Text'):
                        formatted_response["related_information"].append(topic['Text'])
                    elif isinstance(topic, dict) and topic.get('Topics'):
                        for subtopic in topic['Topics']:
                            if isinstance(subtopic, dict) and subtopic.get('Text'):
                                formatted_response["related_information"].append(subtopic['Text'])
            
            # Limit related information to avoid overwhelming response
            formatted_response["related_information"] = formatted_response["related_information"][:5]
            
            return {
                "status": "success",
                "source": "web_search",
                "data": formatted_response
            }
        else:
            logger.error(f"DuckDuckGo API request failed with status code: {response.status_code}")
            return {
                "status": "error",
                "error": f"Failed to fetch information (HTTP {response.status_code})"
            }
    except requests.RequestException as e:
        logger.error(f"Network error during web search: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": f"Network error: {str(e)}"
        }
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing DuckDuckGo API response: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": "Invalid response format from search API"
        }
    except Exception as e:
        logger.error(f"Unexpected error during knowledge search: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }

def format_api_response(api_info: Dict) -> str:
    """Format API information for display"""
    if api_info["source"] == "knowledge_base":
        data = api_info["data"]
        response = [
            f"## {data['base_url']}",
            "\n### Common Endpoints:",
        ]
        
        for endpoint, path in data["common_endpoints"].items():
            response.append(f"- {endpoint}: `{path}`")
        
        response.extend([
            f"\n### Authentication Method: {data['auth_method']}",
            f"\n### Documentation: {data['docs_url']}"
        ])
        
        return "\n".join(response)
    
    elif api_info["source"] == "web_search":
        data = api_info["data"]["search_results"]
        response = ["### Search Results:"]
        
        for result in data.get("RelatedTopics", [])[:5]:
            if "Text" in result:
                response.append(f"- {result['Text']}")
        
        return "\n".join(response)
    
    return "No API information available."

def format_knowledge_response(knowledge_info: Dict) -> str:
    """Format knowledge query response with improved error handling"""
    try:
        if knowledge_info["status"] != "success":
            error_msg = knowledge_info.get("error", "Unknown error occurred")
            logger.error(f"Knowledge query failed: {error_msg}")
            return f"Sorry, I couldn't find the information you requested. Error: {error_msg}"
        
        data = knowledge_info.get("data", {})
        if not isinstance(data, dict):
            logger.error(f"Invalid data format in knowledge_info: {type(data)}")
            return "Sorry, there was an error processing the response data."
        
        response_parts = []
        
        # Add main answer if available
        main_answer = data.get("main_answer", "").strip()
        if main_answer:
            response_parts.append("### Answer:")
            response_parts.append(main_answer)
        
        # Add related information if available
        related_info = data.get("related_information", [])
        if related_info and isinstance(related_info, list):
            response_parts.append("\n### Related Information:")
            for info in related_info:
                if info and isinstance(info, str):
                    response_parts.append(f"- {info.strip()}")
        
        # If no content was added, return a helpful message
        if not response_parts:
            return "I apologize, but I couldn't find any relevant information for your query. Please try rephrasing your question or being more specific."
        
        return "\n".join(response_parts)
        
    except Exception as e:
        logger.error(f"Error formatting knowledge response: {str(e)}", exc_info=True)
        return "Sorry, there was an error formatting the response. Please try again."

def classify_issue(issue: str) -> Tuple[str, str, str]:
    """Classify the issue and return category, reason, and service"""
    try:
        prompt = classifier_template.format(issue=issue)
        response = llm(prompt)
        
        if not response:
            logger.error("Empty response from classifier LLM")
            return "uncategorized", "Failed to get response from classifier", ""
            
        try:
            result = json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse classifier response: {str(e)}")
            return "uncategorized", "Failed to parse classifier response", ""
            
        category = result.get("category", "uncategorized")
        reason = result.get("reason", "No reasoning provided.")
        confidence = float(result.get("confidence", 0.0))
        service = result.get("service", "").lower()

        # Extract service name from query if not provided by classifier
        if not service and "status" in issue.lower():
            services = ["nginx", "mysql", "tomcat", "memcache", "rabbitmq"]
            for svc in services:
                if svc in issue.lower():
                    service = svc
                    break

        # Fallback to keyword-based classification if LLM confidence is low
        if confidence < 0.7:
            keywords = {
                "general_query": ["status", "running", "show", "list", "uptime", "information", "metrics", "usage"],
                "api_query": ["api", "endpoint", "integration", "swagger", "documentation", "rest", "http"]
            }
            
            for cat, kw_list in keywords.items():
                if any(kw in issue.lower() for kw in kw_list):
                    return cat, f"{reason} (Overridden by keyword matching)", service

        logger.info(f"Classified issue as {category} with confidence {confidence}")
        return category, reason, service

    except Exception as e:
        logger.error(f"Classification error: {str(e)}", exc_info=True)
        return "uncategorized", f"Classification failed: {str(e)}", ""

# --- General Query Agent ---
def get_service_commands(service: str) -> List[ServerCommand]:
    """Get relevant commands for a specific service"""
    commands = []
    
    # Always include basic health checks
    commands.extend(COMMAND_GROUPS["basic_health"])
    
    # Add service-specific commands if available
    if service.lower() in [s.lower() for s in COMMAND_GROUPS.keys()]:
        service_key = next(k for k in COMMAND_GROUPS.keys() if k.lower() == service.lower())
        commands.extend(COMMAND_GROUPS[service_key])
    
    # Add generic service status commands
    for cmd in COMMAND_GROUPS["service_status"]:
        commands.append(ServerCommand(
            cmd.command.format(service=service),
            timeout=cmd.timeout
        ))
    
    # Add log commands if applicable
    for cmd in COMMAND_GROUPS["logs"]:
        commands.append(ServerCommand(
            cmd.command.format(service=service),
            timeout=cmd.timeout
        ))
    
    return commands

def run_command_safely(cmd: str, timeout: int = 30) -> Tuple[bool, str, int]:
    """Run a command with timeout and safety checks"""
    try:
        # Use universal_newlines=True and specify encoding
        result = subprocess.run(
            cmd,
            shell=True,
            timeout=timeout,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'  # Replace invalid characters
        )
        return True, result.stdout or result.stderr or "No output", result.returncode
    except subprocess.TimeoutExpired as e:
        return False, f"Command timed out after {timeout} seconds", -1
    except subprocess.CalledProcessError as e:
        return False, str(e.output or e.stderr or "Unknown error"), e.returncode
    except UnicodeDecodeError as e:
        return False, "Error decoding command output (invalid characters)", -1
    except Exception as e:
        return False, f"Error executing command: {str(e)}", -1

def run_commands_on_server(ip: str, commands: List[ServerCommand], server_name: str) -> Dict:
    """Run commands on a remote server with proper error handling"""
    # Get the current working directory and construct the key path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    key_path = os.path.join(current_dir, 'Local_infra_setup_script_IaC', '.vagrant', 'machines', server_name, 'virtualbox', 'private_key')
    
    if not os.path.exists(key_path):
        logger.error(f"SSH key not found for {server_name}: {key_path}")
        return {
            "status": "error",
            "error": "Server authentication failed - SSH key not found",
            "details": {
                "server": server_name,
                "ip": ip,
                "key_path": key_path
            }
        }

    results = []
    # First, test SSH connectivity
    test_cmd = [
        "ssh",
        "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=5",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PubkeyAuthentication=yes",
        "-o", "PasswordAuthentication=no",
        f"vagrant@{ip}",
        "echo 'SSH connection test'"
    ]
    
    try:
        success, output, return_code = run_command_safely(" ".join(test_cmd), timeout=10)
        if not success:
            logger.error(f"Failed to establish SSH connection to {server_name}: {output}")
            return {
                "status": "error",
                "error": "Failed to establish SSH connection",
                "details": {
                    "server": server_name,
                    "ip": ip,
                    "output": output
                }
            }
    except Exception as e:
        logger.error(f"SSH connection test failed for {server_name}: {str(e)}")
        return {
            "status": "error",
            "error": f"SSH connection test failed: {str(e)}",
            "details": {
                "server": server_name,
                "ip": ip
            }
        }

    # If SSH test successful, run the actual commands
    for cmd in commands:
        ssh_cmd = [
            "ssh",
            "-i", key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-o", "PreferredAuthentications=publickey",
            "-o", "PubkeyAuthentication=yes",
            "-o", "PasswordAuthentication=no",
            f"vagrant@{ip}",
            f"LC_ALL=C.UTF-8 {cmd.command}"  # Force UTF-8 encoding
        ]
        
        try:
            success, output, return_code = run_command_safely(" ".join(ssh_cmd), cmd.timeout)
            
            results.append({
                "command": cmd.command,
                "success": success and (return_code == cmd.expected_return_code),
                "output": output.strip(),  # Remove extra whitespace
                "return_code": return_code,
                "timestamp": datetime.datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error running command on {server_name}: {str(e)}", exc_info=True)
            results.append({
                "command": cmd.command,
                "success": False,
                "output": f"Error: {str(e)}",
                "return_code": -1,
                "timestamp": datetime.datetime.now().isoformat()
            })

    return {
        "status": "completed",
        "commands": results,
        "server_info": {
            "name": server_name,
            "ip": ip
        }
    }

def general_query_handler(user_query: str) -> Dict:
    """Handle general queries with improved error handling and logging"""
    try:
        category, reason, service = classify_issue(user_query)
        logger.info(f"Query classified as: {category} (service: {service})")
        
        # Handle knowledge queries
        if category == "knowledge_query":
            logger.info(f"Processing knowledge query: {user_query}")
            try:
                knowledge_info = get_knowledge_information(user_query)
                if knowledge_info.get("status") != "success":
                    error_msg = knowledge_info.get("error", "Unknown error occurred")
                    logger.error(f"Knowledge query failed: {error_msg}")
                    return {
                        "status": "error",
                        "type": "knowledge_query",
                        "error": error_msg
                    }
                
                formatted_response = format_knowledge_response(knowledge_info)
                if formatted_response.startswith("Sorry,"):
                    logger.warning(f"Knowledge query returned no useful information: {user_query}")
                    return {
                        "status": "error",
                        "type": "knowledge_query",
                        "error": "No relevant information found"
                    }
                
                return {
                    "status": "success",
                    "type": "knowledge_query",
                    "response": formatted_response
                }
            except Exception as e:
                logger.error(f"Error processing knowledge query: {str(e)}", exc_info=True)
                return {
                    "status": "error",
                    "type": "knowledge_query",
                    "error": f"Failed to process knowledge query: {str(e)}"
                }
        
        # Handle API queries
        if category == "api_query" and service:
            api_info = get_api_information(service, user_query)
            return {
                "status": "success",
                "type": "api_query",
                "service": service,
                "response": format_api_response(api_info)
            }
        
        # Handle infrastructure queries
        if category == "general_query":
            logger.info("Processing infrastructure query...")
            
            # Check if this is an infrastructure overview request
            if "overview" in user_query.lower():
                overview = {
                    "servers": {},
                    "total_servers": len(infra_config),
                    "services_summary": {}
                }
                
                # Collect information about each server
                for server_name, server_info in infra_config.items():
                    overview["servers"][server_name] = {
                        "ip": server_info["ip"],
                        "os": server_info["os"],
                        "services": server_info["services"]
                    }
                    
                    # Update services summary
                    for service in server_info["services"]:
                        if service not in overview["services_summary"]:
                            overview["services_summary"][service] = []
                        overview["services_summary"][service].append(server_name)
                
                return {
                    "status": "success",
                    "type": "infrastructure_overview",
                    "overview": overview
                }
            
            # Handle specific server/service queries
            server_response = infer_servers_from_query(user_query)
            logger.info(f"Server inference result: {json.dumps(server_response, indent=2)}")
            
            # Check if server inference was successful
            if server_response.get("status") != "success":
                logger.error(f"Server inference failed: {server_response.get('error', 'Unknown error')}")
                return {
                    "status": "error",
                    "type": "infrastructure_query",
                    "error": f"Failed to determine target servers: {server_response.get('error', 'Unknown error')}"
                }

            selected_servers = server_response.get("result", {}).get("selected_servers", [])
            logger.info(f"Selected servers: {selected_servers}")

            if not selected_servers:
                # If no specific servers are selected, try web search for general IT information
                logger.info("No servers selected, falling back to knowledge query")
                knowledge_info = get_knowledge_information(user_query)
                return {
                    "status": "success",
                    "type": "knowledge_query",
                    "response": format_knowledge_response(knowledge_info)
                }

            results = {}
            errors = []
            for server_name in selected_servers:
                logger.info(f"Processing server: {server_name}")
                server_info = infra_config.get(server_name)
                if not server_info:
                    logger.warning(f"Server {server_name} not found in config")
                    errors.append(f"Server {server_name} not found in configuration")
                    continue

                # Get commands based on services running on the server
                commands = []
                service_filter = server_response.get("result", {}).get("service_filter")
                logger.info(f"Service filter: {service_filter}")
                
                if service_filter and service_filter.lower() in [s.lower() for s in COMMAND_GROUPS.keys()]:
                    # Use service-specific commands if available
                    service_key = next(k for k in COMMAND_GROUPS.keys() if k.lower() == service_filter.lower())
                    commands.extend(COMMAND_GROUPS[service_key])
                    logger.info(f"Using service-specific commands for {service_filter}")
                else:
                    # Use generic commands for all services on the server
                    for service in server_info["services"]:
                        commands.extend(get_service_commands(service.lower()))
                    logger.info(f"Using generic commands for services: {server_info['services']}")

                # Execute commands
                logger.info(f"Executing {len(commands)} commands on {server_name}")
                output = run_commands_on_server(
                    server_info["ip"],
                    commands,
                    server_name=server_name
                )

                if output.get("status") == "error":
                    error_msg = f"Error on {server_name}: {output.get('error')}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    continue

                results[server_name] = {
                    "ip": server_info["ip"],
                    "services": server_info["services"],
                    "commands": output
                }
                logger.info(f"Successfully executed commands on {server_name}")

            response = {
                "status": "success" if results else "error",
                "type": "infrastructure_query",
                "results": results,
                "query": user_query
            }

            if errors:
                response["errors"] = errors
                if not results:
                    response["error"] = "Failed to execute commands on all target servers"
                logger.warning(f"Query completed with errors: {errors}")
            else:
                logger.info("Query completed successfully")

            return response

    except Exception as e:
        logger.error(f"Error in general query handler: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }

# --- Resolution Agent ---
resolver_template = PromptTemplate.from_template("""
You are a skilled Site Reliability Engineer.

Given the reported issue, generate a safe and effective resolution plan.
Consider potential risks and include necessary validation steps.

Issue:
{issue}

Infrastructure Configuration:
{infra_config}

Format your response EXACTLY as follows:
{
  "service": "<affected_service>",
  "server": "<target_server>",
  "issue_summary": "<brief_description>",
  "severity": "<high|medium|low>",
  "resolution_steps": [
    {
      "step": "<command or action>",
      "purpose": "<why this step>",
      "validation": "<how to verify>",
      "rollback": "<how to undo if needed>"
    }
  ],
  "reasoning": "<explanation of approach>",
  "risks": ["<potential_risk_1>", "<potential_risk_2>"],
  "prerequisites": ["<requirement_1>", "<requirement_2>"]
}
""")

def resolve_issue(issue: str) -> Dict:
    """Generate a resolution plan for an issue"""
    try:
        prompt = resolver_template.format(
            issue=issue,
            infra_config=json.dumps(infra_config, indent=2)
        )
        response = llm(prompt)
        resolution = json.loads(response)

        # Validate resolution format
        required_fields = ["service", "server", "issue_summary", "resolution_steps"]
        missing_fields = [field for field in required_fields if field not in resolution]
        
        if missing_fields:
            logger.error(f"Resolution plan missing required fields: {missing_fields}")
            return {
                "status": "error",
                "error": f"Invalid resolution plan format. Missing: {missing_fields}"
            }

        # Validate server exists
        if resolution["server"] not in infra_config:
            logger.error(f"Resolution targets non-existent server: {resolution['server']}")
            return {
                "status": "error",
                "error": f"Invalid target server: {resolution['server']}"
            }

        # Validate service runs on target server
        server_services = infra_config[resolution["server"]]["services"]
        if not any(svc.lower() == resolution["service"].lower() for svc in server_services):
            logger.error(f"Service {resolution['service']} not found on server {resolution['server']}")
            return {
                "status": "error",
                "error": f"Service {resolution['service']} is not configured on {resolution['server']}"
            }

        logger.info(f"Generated resolution plan for {resolution['service']} on {resolution['server']}")
        return {
            "status": "success",
            "plan": resolution
        }

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse resolution plan: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": "Generated resolution plan was not in valid JSON format"
        }
    except Exception as e:
        logger.error(f"Error generating resolution plan: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": f"Failed to generate resolution plan: {str(e)}"
        }

# --- Validator Agent ---
validator_template = PromptTemplate.from_template("""
You are a cautious Security and Operations Validator.

Review the proposed resolution plan below and assess its safety and effectiveness.
Consider potential risks, side effects, and whether the steps are appropriate for the issue.

Resolution Plan:
{resolution_plan}

Infrastructure Context:
{infra_config}

Respond EXACTLY in this format:
{
  "approved": <true|false>,
  "reason": "<detailed explanation>",
  "risks_identified": ["<risk1>", "<risk2>"],
  "suggested_modifications": ["<suggestion1>", "<suggestion2>"],
  "required_backups": ["<backup1>", "<backup2>"],
  "confidence": <0.0-1.0>
}
""")

def validate_resolution(resolution: Dict) -> Dict:
    """Validate a proposed resolution plan"""
    try:
        prompt = validator_template.format(
            resolution_plan=json.dumps(resolution, indent=2),
            infra_config=json.dumps(infra_config, indent=2)
        )
        response = llm(prompt)
        validation = json.loads(response)

        # Add validation metadata
        validation["timestamp"] = datetime.datetime.now().isoformat()
        validation["resolution_id"] = resolution.get("id", "unknown")

        logger.info(
            f"Validation result: {'APPROVED' if validation['approved'] else 'REJECTED'} "
            f"with confidence {validation.get('confidence', 0.0)}"
        )

        return validation

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse validation response: {str(e)}", exc_info=True)
        return {
            "approved": False,
            "reason": "Validation response was not in valid JSON format",
            "error": str(e)
        }
    except Exception as e:
        logger.error(f"Error during validation: {str(e)}", exc_info=True)
        return {
            "approved": False,
            "reason": f"Validation failed: {str(e)}",
            "error": str(e)
        }

# --- Executor Agent ---
class ExecutorAgent:
    def __init__(self):
        self.execution_log = []
        logger.info("ExecutorAgent initialized")

    def execute_remediation(self, execution_data: Dict) -> Dict:
        """Execute approved remediation steps with safety checks"""
        try:
            server_name = execution_data.get("server")
            steps = execution_data.get("resolution_steps", [])

            if not server_name or not steps:
                return {
                    "status": "error",
                    "error": "Missing server name or resolution steps"
                }

            server_info = infra_config.get(server_name)
            if not server_info:
                return {
                    "status": "error",
                    "error": f"Server {server_name} not found in configuration"
                }

            results = []
            for step in steps:
                step_cmd = step.get("step", "")
                if not step_cmd:
                    continue

                # Execute the step
                cmd_result = self._execute_step(
                    server_info["ip"],
                    step_cmd,
                    server_name,
                    timeout=300  # 5 minutes max per step
                )

                # Validate the step
                validation_cmd = step.get("validation")
                validation_result = None
                if validation_cmd:
                    validation_result = self._execute_step(
                        server_info["ip"],
                        validation_cmd,
                        server_name,
                        timeout=60
                    )

                results.append({
                    "step": step_cmd,
                    "result": cmd_result,
                    "validation": validation_result,
                    "timestamp": datetime.datetime.now().isoformat()
                })

                # If step failed and has rollback, execute rollback
                if not cmd_result.get("success") and step.get("rollback"):
                    rollback_result = self._execute_step(
                        server_info["ip"],
                        step["rollback"],
                        server_name,
                        timeout=300
                    )
                    results[-1]["rollback_result"] = rollback_result

            # Log the execution
            self.execution_log.append({
                "server": server_name,
                "timestamp": datetime.datetime.now().isoformat(),
                "results": results
            })

            return {
                "status": "completed",
                "results": results
            }

        except Exception as e:
            logger.error(f"Error during remediation execution: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }

    def _execute_step(self, ip: str, command: str, server_name: str, timeout: int = 300) -> Dict:
        """Execute a single command step"""
        key_path = f"C:/Users/debna/OneDrive/Desktop/Autonomous-IT-Support-Agent/Local_infra_setup_script_IaC/.vagrant/machines/{server_name}/virtualbox/private_key"
        
        if not os.path.exists(key_path):
            return {
                "success": False,
                "error": f"SSH key not found: {key_path}"
            }

        ssh_cmd = [
            "ssh",
            "-i", key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            f"vagrant@{ip}",
            command
        ]

        try:
            success, output, return_code = run_command_safely(" ".join(ssh_cmd), timeout)
            return {
                "success": success,
                "output": output,
                "return_code": return_code
            }
        except Exception as e:
            logger.error(f"Error executing step on {server_name}: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def get_execution_log(self) -> List[Dict]:
        """Get the execution history"""
        return self.execution_log

def infer_servers_from_query(query: str) -> Dict:
    """Infer which servers to query based on the user's input"""
    try:
        if not infra_config:
            raise ValueError("Infrastructure configuration is not available")

        # Extract service name from query
        services = ["nginx", "mysql", "tomcat", "memcache", "rabbitmq"]
        service_filter = next((svc for svc in services if svc in query.lower()), None)

        # Extract server name from query
        server_filter = next((server for server in infra_config.keys() if server in query.lower()), None)

        selected_servers = []

        # If specific server mentioned, use it
        if server_filter:
            if service_filter:
                # Check if the server runs the service
                if any(svc.lower() == service_filter for svc in infra_config[server_filter]["services"]):
                    selected_servers.append(server_filter)
            else:
                selected_servers.append(server_filter)

        # If no server found but service mentioned, find servers running that service
        if not selected_servers and service_filter:
            for server, info in infra_config.items():
                if any(svc.lower() == service_filter for svc in info["services"]):
                    selected_servers.append(server)

        if not selected_servers:
            # If service mentioned but no servers found
            if service_filter:
                return {
                    "status": "error",
                    "error": f"No servers found running service: {service_filter}"
                }
            # If neither service nor server mentioned
            return {
                "status": "error",
                "error": "Could not determine which servers to query. Please specify a server or service."
            }

        return {
            "status": "success",
            "result": {
                "selected_servers": selected_servers,
                "reasoning": f"Selected servers running {service_filter}" if service_filter else "Selected specifically mentioned servers",
                "service_filter": service_filter
            }
        }

    except Exception as e:
        logger.error(f"Error inferring servers: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }
