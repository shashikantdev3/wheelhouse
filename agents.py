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
import re
import asyncio
from core.command import run_command_async
from core.command_map import get_command
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load infra config
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'infra_config.json')
infra_config = {}

try:
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

llm = Ollama(
    model="mistral",
    temperature=0.2,  # Lower temperature for more consistent responses
    stop=["</s>", "```json"],  # Stop tokens to ensure clean JSON output
)
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
        ServerCommand("df -h", timeout=5),
        ServerCommand("cat /proc/loadavg", timeout=5)
    ],
    "service_status": [
        ServerCommand("systemctl status {service}", timeout=10)
    ],
    "process": [
        ServerCommand("top -b -n1", timeout=10)
    ],
    "tomcat": [
        ServerCommand("systemctl status tomcat", timeout=10)
    ],
    "mysql": [
        ServerCommand("systemctl status mariadb", timeout=10),
        ServerCommand("sudo tail -n 100 /var/log/mariadb/mariadb.log 2>/dev/null || sudo tail -n 100 /var/log/mysql/error.log 2>/dev/null", timeout=15),
        ServerCommand("sudo tail -n 50 /var/log/mariadb/mariadb-slow.log 2>/dev/null || sudo tail -n 50 /var/log/mysql/mysql-slow.log 2>/dev/null", timeout=15),
        ServerCommand("mysql -V", timeout=5),
        ServerCommand("sudo mysqladmin status", timeout=10),
        ServerCommand("sudo mysqladmin extended-status | grep -E 'Questions|Slow_queries|Threads|Connections'", timeout=10),
        ServerCommand("sudo find /var/log -name '*mysql*.log' -o -name '*mariadb*.log' -type f -exec ls -l {} \\;", timeout=10)
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
CATEGORY_DEFINITIONS = {
    "general_query": {
        "description": "Requests for information about infrastructure, system status, logs, metrics, or data retrieval",
        "patterns": {
            "infrastructure": [
                r"show (me |the )?status",
                r"check.*status",
                r"get.*status",
                r"monitor",
                r"health",
                r"list.*services",
                r"running",
                r"uptime",
                r"(cpu|memory|disk).*usage",
                r"how.*much.*cpu",
                r"performance",
                r"load",
                r"utilization"
            ],
            "targets": [
                r"server",
                r"service",
                r"process",
                r"port",
                r"connection",
                r"cpu",
                r"memory",
                r"disk"
            ]
        }
    },
    "knowledge_query": {
        "description": "Questions requiring general knowledge, explanations, or comparisons",
        "patterns": {
            "question_types": [
                r"what\s+is",
                r"how\s+does",
                r"explain",
                r"describe",
                r"difference\s+between",
                r"compare",
                r"what\s+are",
                r"how\s+to",
                r"why\s+does",
                r"when\s+to",
                r"tell\s+me\s+about"
            ],
            "learning_indicators": [
                r"understand",
                r"learn",
                r"concept",
                r"definition",
                r"meaning",
                r"purpose",
                r"benefits?"
            ]
        }
    },
    "api_query": {
        "description": "Questions about API endpoints, documentation, or integration details",
        "patterns": {
            "api_indicators": [
                r"api",
                r"endpoint",
                r"integration",
                r"interface",
                r"swagger",
                r"openapi",
                r"rest",
                r"soap",
                r"graphql"
            ],
            "api_actions": [
                r"authenticate",
                r"authorize",
                r"call",
                r"request",
                r"response",
                r"payload",
                r"parameter"
            ]
        },
        "services": {
            "servicenow": [r"service\s*now", r"snow"],
            "ansible": [r"ansible", r"tower", r"awx"],
            "kubernetes": [r"kubernetes", r"k8s", r"kubectl"],
            "docker": [r"docker", r"container"],
            "jenkins": [r"jenkins", r"ci", r"cd", r"pipeline"]
        }
    },
    "needs_resolution": {
        "description": "Issues requiring troubleshooting or fixing",
        "patterns": {
            "error_indicators": [
                r"error",
                r"fail(ed|ing)?",
                r"broken",
                r"not\s+working",
                r"issue",
                r"problem",
                r"crash(ed|ing)?",
                r"down",
                r"unavailable",
                r"fix",
                r"resolve",
                r"troubleshoot"
            ],
            "severity_indicators": [
                r"urgent",
                r"critical",
                r"emergency",
                r"asap",
                r"high\s+priority",
                r"production",
                r"outage"
            ]
        }
    }
}

def get_or_create_event_loop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop

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

def classify_issue(issue: str) -> Tuple[str, str, str]:
    """Classify the issue type and identify relevant service"""
    issue = issue.lower()
    
    # Check for API queries first
    for service, patterns in CATEGORY_DEFINITIONS["api_query"]["services"].items():
        if any(re.search(pattern, issue) for pattern in patterns):
            return "api_query", service, f"Matched patterns: api_indicators, api_indicators"
    
    # Check for infrastructure queries
    infra_patterns = CATEGORY_DEFINITIONS["general_query"]["patterns"]
    if (any(re.search(pattern, issue) for pattern in infra_patterns["infrastructure"]) and
        any(re.search(pattern, issue) for pattern in infra_patterns["targets"])):
        # Identify service if mentioned
        service = ""
        if "mysql" in issue or "database" in issue or "db" in issue:
            service = "mysql"
        elif "tomcat" in issue or "web server" in issue or "web" in issue or "nginx" in issue:
            service = "nginx"
        elif "memcache" in issue or "cache" in issue:
            service = "memcache"
        elif "rabbitmq" in issue or "queue" in issue or "rabbit" in issue:
            service = "rabbitmq"
        return "general_query", service, "Matched patterns: infrastructure, targets"
    
    # Check for knowledge queries
    knowledge_patterns = CATEGORY_DEFINITIONS["knowledge_query"]["patterns"]
    if (any(re.search(pattern, issue) for pattern in knowledge_patterns["question_types"]) or
        any(re.search(pattern, issue) for pattern in knowledge_patterns["learning_indicators"])):
        return "knowledge_query", "", "Matched patterns: question_types"
    
    # Check for issues needing resolution
    resolution_patterns = CATEGORY_DEFINITIONS["needs_resolution"]["patterns"]
    if (any(re.search(pattern, issue) for pattern in resolution_patterns["error_indicators"]) or
        any(re.search(pattern, issue) for pattern in resolution_patterns["severity_indicators"])):
        # Identify service if mentioned
        service = ""
        if "mysql" in issue or "database" in issue:
            service = "database"
        elif "tomcat" in issue or "web" in issue:
            service = "web"
        return "needs_resolution", service, "Matched patterns: error_indicators, severity_indicators"
    
    # Default to general query if no specific patterns match
    return "general_query", "", "No specific patterns matched"

def get_service_commands(service: str, is_cpu_query: bool = False) -> List[ServerCommand]:
    """Get list of commands to run for a given service"""
    commands = []
    
    # Always include basic health checks
    commands.extend(COMMAND_GROUPS["basic_health"])
    
    # Add service-specific commands
    if service in COMMAND_GROUPS:
        commands.extend(COMMAND_GROUPS[service])
    elif service:
        # If service exists but no specific commands, check its status
        commands.extend([
            ServerCommand(f"systemctl status {service}", timeout=10)
        ])
    
    # For CPU queries, add process monitoring
    if is_cpu_query:
        commands.extend(COMMAND_GROUPS["process"])
    
    return commands

def run_command_safely(cmd: str, timeout: int = 30) -> Tuple[bool, str, int]:
    """Run a command with safety checks and proper error handling"""
    try:
        # Execute command with timeout
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        # Check return code
        success = result.returncode == 0
        output = result.stdout if success else f"{result.stdout}\n{result.stderr}".strip()
        
        return success, output, result.returncode
        
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout} seconds", -1
    except Exception as e:
        return False, f"Error executing command: {str(e)}", -1

def run_commands_on_server(ip: str, commands: List[ServerCommand], server_name: str) -> Dict:
    """Execute commands on a server and return results"""
    results = []
    
    for cmd in commands:
        # Replace placeholders in command
        command_str = cmd.command.format(server=server_name)
        
        # Execute command
        success, output, return_code = run_command_safely(command_str, cmd.timeout)
        
        # Record result
        results.append({
            "command": command_str,
            "success": success and (return_code == cmd.expected_return_code),
            "output": output,
            "return_code": return_code,
            "timestamp": datetime.datetime.now().isoformat()
        })
    
    return {
        "status": "completed",
        "commands": results
    }

def format_service_summary(service_name: str, command_results: List[Dict]) -> str:
    """Format command outputs into a readable summary"""
    summary_parts = []
    
    # Add service name header
    summary_parts.append(f"Service: {service_name}")
    
    # Process each command result
    for result in command_results:
        if not result.get("success"):
            continue
            
        output = result.get("output", "").strip()
        if not output:
            continue
            
        # Format based on command type
        if "status" in result["command"]:
            # Parse systemctl status output
            status_lines = output.split("\n")
            service_info = []
            
            for line in status_lines:
                line = line.strip()
                if "Active:" in line:
                    service_info.append(f"Status: {line.split('Active:')[1].strip()}")
                elif "Memory:" in line:
                    service_info.append(f"Memory Usage: {line.split('Memory:')[1].strip()}")
                elif "CPU:" in line:
                    service_info.append(f"CPU Time: {line.split('CPU:')[1].strip()}")
                elif "Main PID:" in line:
                    service_info.append(f"Process ID: {line.split('Main PID:')[1].split()[0].strip()}")
            
            if service_info:
                summary_parts.extend(service_info)
        
        elif "free -m" in result["command"]:
            # Parse memory info
            try:
                lines = output.split("\n")
                headers = lines[0].split()
                values = lines[1].split()
                mem_info = dict(zip(headers, values[1:]))
                summary_parts.append(f"Memory Total: {mem_info['total']}MB")
                summary_parts.append(f"Memory Used: {mem_info['used']}MB")
                summary_parts.append(f"Memory Free: {mem_info['free']}MB")
            except Exception:
                summary_parts.append(output)
        
        elif "df -h" in result["command"]:
            # Parse disk usage
            try:
                lines = output.split("\n")[1:]  # Skip header
                for line in lines:
                    if line.strip():
                        parts = line.split()
                        if parts[-1] == "/":  # Root filesystem
                            summary_parts.append(f"Disk Usage: {parts[-2]} of {parts[1]} used")
                            break
            except Exception:
                summary_parts.append(output)
        
        elif "uptime" in result["command"]:
            # Parse uptime
            try:
                if "load average:" in output:
                    load = output.split("load average:")[1].strip()
                    summary_parts.append(f"Load Average: {load}")
            except Exception:
                summary_parts.append(output)
        
        elif "top" in result["command"]:
            # Parse top output for CPU usage
            try:
                cpu_line = None
                mem_line = None
                for line in output.split("\n"):
                    if "%Cpu" in line:
                        cpu_line = line
                    elif "MiB Mem" in line:
                        mem_line = line
                    if cpu_line and mem_line:
                        break
                
                if cpu_line:
                    summary_parts.append(f"CPU Usage: {cpu_line.strip()}")
                if mem_line:
                    summary_parts.append(f"Memory Status: {mem_line.strip()}")
            except Exception:
                summary_parts.append(output)
        
        else:
            # Default formatting for other commands
            summary_parts.append(f"Command '{result['command']}':")
            summary_parts.append(output)
    
    return "\n".join(summary_parts)

class ClassifierAgent:
    """Agent responsible for classifying user queries into appropriate categories"""
    
    def classify(self, query: str) -> Dict:
        """Classify a user query into one of the supported query types"""
        try:
            category, service, reason = classify_issue(query)
            logger.info(f"Query classified as {category} for service {service}: {reason}")
            
            return {
                "status": "success",
                "category": category,
                "service": service,
                "reason": reason
            }
        except Exception as e:
            logger.error(f"Error classifying query: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Failed to classify query: {str(e)}"
            }

class InfrastructureQueryAgent:
    """Agent responsible for handling infrastructure-related queries"""
    
    def process_query(self, user_query: str, service: str = "") -> Dict:
        """Process queries related to infrastructure status"""
        try:
            logger.info(f"Processing infrastructure query for service: {service}")
            
            # Initialize server_name
            server_name = None
            
            # Check if a specific server was mentioned
            for server in infra_config.keys():
                if server.lower() in user_query.lower():
                    server_name = server
                    logger.info(f"Found server name in query: {server_name}")
                    break
            
            # Check for explicit commands like ping, ls, cat, etc.
            explicit_commands = ['ping', 'nslookup', 'traceroute', 'tracert', 'dig', 'netstat', 'ifconfig', 'ip a']
            command = ''
            for cmd in explicit_commands:
                if cmd in user_query.lower().split():
                    # Extract full command with arguments
                    query_words = user_query.lower().split()
                    cmd_index = query_words.index(cmd)
                    command_parts = []
                    
                    # First just extract the command itself
                    command_parts.append(query_words[cmd_index])
                    
                    # Check if this is in "command on server" format
                    if cmd_index + 2 < len(query_words) and query_words[cmd_index + 1] == "command" and query_words[cmd_index + 2] == "on":
                        # This is "ping command on server" format
                        # Skip "command on" and get the server
                        if cmd_index + 3 < len(query_words):
                            server_word = query_words[cmd_index + 3]
                            
                            # Since infra_config now uses legacy names directly, we can check there
                            if server_word in infra_config:
                                server_name = server_word
                                logger.info(f"Found server in 'command on server' format: {server_name}")
                            # Case where server name might be slightly different in query vs config
                            elif any(s for s in infra_config.keys() if server_word in s.lower()):
                                server_name = next(s for s in infra_config.keys() if server_word in s.lower())
                                logger.info(f"Found similar server in 'command on server' format: {server_name}")
                            
                            # Format the command without "command on"
                            command = f"{cmd}"
                            logger.info(f"Extracted command from 'command on' format: {command}")
                    else:
                        # Normal command extraction
                        for i in range(cmd_index, len(query_words)):
                            # Stop if we hit certain words
                            if query_words[i] in ['and', 'then', 'next', 'with', 'to', 'for', 'in', 'at', 'command', 'on']:
                                break
                            command_parts.append(query_words[i])
                        command = ' '.join(command_parts)
                        logger.info(f"Extracted explicit command: {command}")
                        
                        # Check if this command mentions any servers
                        target_server = None
                        for word in command_parts[1:]:  # Skip the command itself
                            # Check direct server names
                            for srv in infra_config.keys():
                                if word == srv.lower():
                                    target_server = srv
                                    server_name = target_server
                                    logger.info(f"Command targets server: {target_server}")
                                    break
                    break
            
            # Check for service mentions
            if not service:
                for server_config in infra_config.values():
                    for svc in server_config.get("services", []):
                        if svc.lower() in user_query.lower():
                            service = svc
                            break
                    if service:
                        break
            
            results = {}
            # Execute on relevant servers
            for server, config in infra_config.items():
                # If a specific server was mentioned, only query that one
                if server_name and server != server_name:
                    continue
                    
                # If service was specified, only query servers with that service
                if service and service not in config["services"]:
                    continue
                
                # Use LLM to generate appropriate commands based on query and server context
                if not command:
                    command = generate_commands_with_llm(user_query, server, config)
                    logger.info(f"Using LLM-generated command: '{command}' for server {server}")
                    
                # Use new async remote/OS-aware runner
                loop = get_or_create_event_loop()
                cmd_result = loop.run_until_complete(
                    run_command_async(command, user='system', server=server, metric=None)
                )
                results[server] = {
                    "ip": config["ip"],
                    "services": config["services"],
                    "commands": [cmd_result]
                }
                    
            if not results:
                return {
                    "status": "error",
                    "type": "infrastructure_query",
                    "error": "No matching servers found for the query. Try specifying a different server or service."
                }
                
            return {
                "status": "success",
                "type": "infrastructure_query",
                "results": results
            }
        except Exception as e:
            logger.error(f"Error processing infrastructure query: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "type": "infrastructure_query",
                "error": f"Failed to process infrastructure query: {str(e)}"
            }

class GeneralKnowledgeAgent:
    """Agent responsible for handling general knowledge queries using LLM"""
    
    def process_query(self, user_query: str) -> Dict:
        """Process general knowledge queries using the LLM's inherent knowledge"""
        try:
            logger.info(f"Processing knowledge query: {user_query}")
            
            # Create a prompt for the LLM
            prompt = PromptTemplate(
                input_variables=["query"],
                template="""
                You are an expert IT support professional. Please answer the following question with detailed, accurate information:
                
                Question: {query}
                
                Provide a clear, concise, and technically accurate response that demonstrates expert knowledge on the topic.
                """
            )
            
            # Generate answer using LLM
            chain = LLMChain(llm=llm, prompt=prompt)
            answer = chain.run(query=user_query)
            
            # Format the response
            return {
                "status": "success",
                "type": "knowledge_query",
                "query": user_query,
                "results": {
                    "summary": answer.strip(),
                    "related_topics": [],
                    "query": user_query,
                    "source": "llm_knowledge"
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing knowledge query: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "type": "knowledge_query", 
                "error": f"Failed to process knowledge query: {str(e)}"
            }
    
    def _format_knowledge_response(self, results: Dict, query: str) -> Dict:
        """Format search results into a structured knowledge response"""
        # Extract abstract text if available
        abstract = results.get("AbstractText", "")
        
        # Extract related topics
        related_topics = []
        for topic in results.get("RelatedTopics", []):
            if "Text" in topic:
                related_topics.append({
                    "text": topic["Text"],
                    "url": topic.get("FirstURL", "")
                })
        
        # Create a formatted response
        return {
            "summary": abstract if abstract else "No direct answer found.",
            "related_topics": related_topics[:5],  # Limit to top 5 related topics
            "query": query
        }

class ResolverAgent:
    """Agent responsible for generating resolution plans for identified issues"""
    
    def generate_resolution(self, issue: str, service: str) -> Dict:
        """Generate resolution steps for an issue"""
        try:
            # Get relevant server information
            target_server = None
            for server, config in infra_config.items():
                if service in config["services"]:
                    target_server = server
                    break
            
            if not target_server:
                return {
                    "status": "error",
                    "error": f"No server found running service: {service}"
                }
            
            # Generate resolution steps using LLM
            prompt = PromptTemplate(
                input_variables=["issue", "service", "server"],
                template="""
                Given the following issue with {service} on {server}, provide a detailed resolution plan:
                
                Issue: {issue}
                
                Your response should include:
                1. Issue analysis
                2. Step-by-step resolution with commands
                3. Validation steps
                4. Rollback procedures
                5. Risk assessment
                
                Format as JSON with the following structure:
                {{
                    "issue_summary": "Brief description of the issue",
                    "severity": "high|medium|low",
                    "service": "affected service name",
                    "server": "affected server name",
                    "resolution_steps": [
                        {{
                            "step": "description of the step",
                            "purpose": "why this step is needed",
                            "validation": "command to validate the step",
                            "rollback": "command to undo this step if needed"
                        }}
                    ],
                    "risks": ["list of potential risks"],
                    "prerequisites": ["required preparations"]
                }}
                """
            )
            
            # Generate resolution plan
            chain = LLMChain(llm=llm, prompt=prompt)
            response = chain.run(issue=issue, service=service, server=target_server)
            
            try:
                resolution = json.loads(response)
            except json.JSONDecodeError:
                logger.error("Failed to parse LLM response as JSON", exc_info=True)
                return {
                    "status": "error",
                    "error": "Failed to generate valid resolution plan"
                }
            
            return {
                "status": "success",
                "resolution": resolution
            }
            
        except Exception as e:
            logger.error(f"Error generating resolution: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Failed to generate resolution: {str(e)}"
            }

class ValidatorAgent:
    """Agent responsible for validating proposed solutions for safety and effectiveness"""
    
    def validate_resolution(self, resolution: Dict) -> Dict:
        """Validate a proposed resolution plan"""
        try:
            validation_score = 0.0
            risks_identified = []
            suggested_modifications = []
            
            # Check required fields
            required_fields = [
                "issue_summary", "severity", "service", "server",
                "resolution_steps", "risks", "prerequisites"
            ]
            
            missing_fields = [field for field in required_fields if field not in resolution]
            if missing_fields:
                return {
                    "approved": False,
                    "confidence": 0.0,
                    "reason": f"Missing required fields: {', '.join(missing_fields)}",
                    "risks_identified": ["Incomplete resolution plan"],
                    "suggested_modifications": ["Add missing fields: " + ", ".join(missing_fields)]
                }
            
            # Validate severity
            if resolution["severity"] not in ["high", "medium", "low"]:
                suggested_modifications.append("Use valid severity level: high, medium, or low")
                validation_score -= 0.2
            
            # Validate server exists
            if resolution["server"] not in infra_config:
                return {
                    "approved": False,
                    "confidence": 0.0,
                    "reason": f"Server {resolution['server']} not found in configuration",
                    "risks_identified": ["Invalid target server"],
                    "suggested_modifications": ["Verify server name"]
                }
            
            # Validate service runs on server
            server_services = infra_config[resolution["server"]]["services"]
            if resolution["service"] not in server_services:
                return {
                    "approved": False,
                    "confidence": 0.0,
                    "reason": f"Service {resolution['service']} not found on server {resolution['server']}",
                    "risks_identified": ["Invalid service for target server"],
                    "suggested_modifications": [f"Available services: {', '.join(server_services)}"]
                }
            
            # Validate resolution steps
            if not resolution["resolution_steps"]:
                return {
                    "approved": False,
                    "confidence": 0.0,
                    "reason": "No resolution steps provided",
                    "risks_identified": ["Empty resolution plan"],
                    "suggested_modifications": ["Add detailed resolution steps"]
                }
            
            # Check each step
            for i, step in enumerate(resolution["resolution_steps"]):
                step_issues = []
                
                # Check required step fields
                step_fields = ["step", "purpose", "validation"]
                missing_step_fields = [field for field in step_fields if not step.get(field)]
                if missing_step_fields:
                    step_issues.append(f"Missing fields: {', '.join(missing_step_fields)}")
                
                # Check if validation command exists
                if not step.get("validation"):
                    step_issues.append("No validation command")
                
                # Suggest adding rollback for risky operations
                risky_terms = ["remove", "delete", "drop", "truncate", "restart", "stop"]
                if any(term in step["step"].lower() for term in risky_terms) and not step.get("rollback"):
                    step_issues.append("Missing rollback procedure for risky operation")
                    risks_identified.append(f"Step {i+1} involves risky operation without rollback")
                
                if step_issues:
                    suggested_modifications.append(f"Step {i+1}: {'; '.join(step_issues)}")
                    validation_score -= 0.1
            
            # Validate risks and prerequisites
            if not resolution["risks"]:
                suggested_modifications.append("Add potential risks assessment")
                validation_score -= 0.1
            
            if not resolution["prerequisites"]:
                suggested_modifications.append("Add prerequisites")
                validation_score -= 0.1
            
            # Calculate final confidence score
            base_confidence = 1.0
            final_confidence = max(0.0, min(1.0, base_confidence + validation_score))
            
            # Determine approval
            approved = final_confidence >= 0.7 and not risks_identified
            
            return {
                "approved": approved,
                "confidence": final_confidence,
                "reason": "Resolution plan looks good" if approved else "Issues found in resolution plan",
                "risks_identified": risks_identified,
                "suggested_modifications": suggested_modifications
            }
            
        except Exception as e:
            logger.error(f"Error validating resolution: {str(e)}", exc_info=True)
            return {
                "approved": False,
                "confidence": 0.0,
                "reason": f"Validation error: {str(e)}",
                "risks_identified": ["Validation failed"],
                "suggested_modifications": ["Fix validation errors"]
            }

class ApiQueryAgent:
    """Agent responsible for handling API-related queries and documentation"""
    
    def process_query(self, service: str, query: str) -> Dict:
        """Process API queries and return relevant documentation"""
        try:
            logger.info(f"Processing API query for service: {service}")
            
            # Check knowledge base first
            if service.lower() in KNOWLEDGE_BASE:
                return {
                    "status": "success",
                    "type": "api_query",
                    "service": service,
                    "data": KNOWLEDGE_BASE[service.lower()]
                }
            
            # If not in knowledge base, search online
            search_query = f"{service} API documentation endpoints"
            search_url = f"https://api.duckduckgo.com/?q={quote_plus(search_query)}&format=json"
            response = requests.get(search_url)
            
            if response.status_code == 200:
                return {
                    "status": "success",
                    "type": "api_query",
                    "service": service,
                    "data": {
                        "search_results": response.json(),
                        "query": search_query
                    }
                }
            else:
                return {
                    "status": "error",
                    "type": "api_query",
                    "error": "Failed to fetch online documentation"
                }
                
        except Exception as e:
            logger.error(f"Error processing API query: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "type": "api_query",
                "error": f"Failed to process API query: {str(e)}"
            }

class ExecutorAgent:
    """Agent responsible for executing approved resolutions"""
    
    def __init__(self):
        self.execution_log = []
    
    def execute_remediation(self, execution_data: Dict) -> Dict:
        """Execute approved remediation steps with safety checks"""
        try:
            server_name = execution_data.get("server")
            steps = execution_data.get("resolution_steps", [])
            service = execution_data.get("service", "")

            if not server_name or not steps:
                logger.error("Missing server name or resolution steps")
                return {
                    "status": "error",
                    "error": "Missing server name or resolution steps"
                }

            server_info = infra_config.get(server_name)
            if not server_info:
                logger.error(f"Server {server_name} not found in configuration")
                return {
                    "status": "error",
                    "error": f"Server {server_name} not found in configuration"
                }

            # Verify service is running on server
            if service and service.lower() not in [s.lower() for s in server_info["services"]]:
                logger.error(f"Service {service} not found on server {server_name}")
                return {
                    "status": "error",
                    "error": f"Service {service} is not configured on {server_name}"
                }

            results = []
            execution_successful = True
            
            for step in steps:
                step_cmd = step.get("validation", "")  # Use validation command as the actual command
                if not step_cmd:
                    logger.warning(f"No validation command for step: {step.get('step', 'Unknown step')}")
                    continue

                logger.info(f"Executing step: {step.get('step')} on {server_name}")
                
                # Execute the validation command
                cmd_result = self._execute_step(
                    server_info["ip"],
                    step_cmd,
                    server_name,
                    timeout=300  # 5 minutes max per step
                )

                step_result = {
                    "step": step.get("step", ""),
                    "command": step_cmd,
                    "result": cmd_result,
                    "timestamp": datetime.datetime.now().isoformat()
                }

                # If step failed and has rollback, execute rollback
                if not cmd_result.get("success") and step.get("rollback"):
                    logger.warning(f"Step failed, executing rollback: {step.get('rollback')}")
                    rollback_result = self._execute_step(
                        server_info["ip"],
                        step["rollback"],
                        server_name,
                        timeout=300
                    )
                    step_result["rollback_result"] = rollback_result
                    execution_successful = False

                results.append(step_result)

            # Log the execution
            execution_record = {
                "server": server_name,
                "service": service,
                "timestamp": datetime.datetime.now().isoformat(),
                "results": results,
                "successful": execution_successful
            }
            self.execution_log.append(execution_record)

            return {
                "status": "completed",
                "successful": execution_successful,
                "execution": execution_record
            }

        except Exception as e:
            logger.error(f"Error executing remediation: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Execution failed: {str(e)}"
            }
    
    def _execute_step(self, ip: str, command: str, server_name: str, timeout: int = 300) -> Dict:
        """Execute a single step and return the result"""
        success, output, return_code = run_command_safely(command, timeout)
        return {
            "success": success,
            "output": output,
            "return_code": return_code,
            "timestamp": datetime.datetime.now().isoformat()
        }
    
    def get_execution_log(self) -> List[Dict]:
        """Return the execution log"""
        return self.execution_log 

class SupportCrew:
    """Main orchestrator for the multi-agent IT support system"""
    
    def __init__(self):
        self.classifier = ClassifierAgent()
        self.infra_agent = InfrastructureQueryAgent()
        self.knowledge_agent = GeneralKnowledgeAgent()
        self.resolver = ResolverAgent()
        self.validator = ValidatorAgent()
        self.executor = ExecutorAgent()
        self.api_agent = ApiQueryAgent()
        
    def process_request(self, query: str) -> Dict:
        """Process a user request through the appropriate agent pipeline"""
        try:
            # Step 1: Classify the query
            classification = self.classifier.classify(query)
            
            if classification["status"] != "success":
                return classification
                
            category = classification["category"]
            service = classification["service"]
            
            # Step 2: Route to appropriate agent
            if category == "general_query":
                return self.infra_agent.process_query(query, service)
                
            elif category == "knowledge_query":
                return self.knowledge_agent.process_query(query)
                
            elif category == "api_query":
                return self.api_agent.process_query(service, query)
                
            elif category == "needs_resolution":
                # Generate resolution
                resolution_result = self.resolver.generate_resolution(query, service)
                
                if resolution_result["status"] != "success":
                    return resolution_result
                    
                # Validate resolution
                validation = self.validator.validate_resolution(resolution_result["resolution"])
                
                return {
                    "status": "success",
                    "type": "resolution",
                    "resolution": resolution_result["resolution"],
                    "validation": validation
                }
                
            else:
                return {
                    "status": "error",
                    "error": f"Unknown query category: {category}"
                }
                
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Failed to process request: {str(e)}"
            }
            
    def execute_resolution(self, resolution_data: Dict) -> Dict:
        """Execute an approved resolution plan"""
        return self.executor.execute_remediation(resolution_data)
        
# Replace the old general_query_handler with the new multi-agent system
def general_query_handler(user_query: str) -> Dict:
    """Handle all user queries using the new multi-agent system"""
    crew = SupportCrew()
    return crew.process_request(user_query)

def generate_commands_with_llm(user_query: str, server_name: str, server_info: Dict) -> str:
    """Generate appropriate commands for a server using LLM based on query context"""
    try:
        os_type = server_info.get('os', 'linux')
        services = server_info.get('services', [])
        
        prompt = PromptTemplate(
            input_variables=["query", "server", "os", "services"],
            template="""
            You are an expert IT administrator. Given the following information:
            
            Query: {query}
            Server: {server}
            Operating System: {os}
            Running Services: {services}
            
            Generate a single Linux shell command that best addresses the query.
            The command should be appropriate for the server's OS and services.
            Use only standard Linux commands that are available on most distributions without
            additional packages (e.g., use top, ps, free, vmstat, cat /proc/* files).
            DO NOT use specialized tools like sar, iostat, or other sysstat tools.
            
            Return ONLY the command with no explanations, no backticks, and no markdown formatting.
            """
        )
        
        # Generate command using LLM
        chain = LLMChain(llm=llm, prompt=prompt)
        generated_command = chain.run(
            query=user_query,
            server=server_name,
            os=os_type,
            services=", ".join(services)
        ).strip()
        
        logger.info(f"LLM generated command for {server_name}: {generated_command}")
        
        # Remove any markdown formatting if present
        if generated_command.startswith("```") and generated_command.endswith("```"):
            # Extract content between first and last ```
            lines = generated_command.split("\n")
            if len(lines) > 2:
                # Skip first line with ``` and language name
                start_index = 1 if lines[0].startswith("```") else 0
                # Skip last line with ```
                end_index = -1 if lines[-1].strip() == "```" else None
                # Join the content lines
                generated_command = "\n".join(lines[start_index:end_index]).strip()
            else:
                generated_command = generated_command.strip("```").strip()
        
        # Remove any remaining backticks
        generated_command = generated_command.strip("`").strip()
        
        # Remove any language specification at the beginning like "bash" or "sh"
        if generated_command.startswith("bash") or generated_command.startswith("sh"):
            generated_command = generated_command[4:].strip()
            
        # Replace multiple newlines with spaces to ensure single-line command
        generated_command = re.sub(r'\s*\n\s*', ' ', generated_command)
            
        return generated_command
    except Exception as e:
        logger.error(f"Error generating command with LLM: {str(e)}", exc_info=True)
        # Fallback to a basic status command
        return "uptime" 