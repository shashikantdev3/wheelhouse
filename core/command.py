import subprocess
import asyncio
import logging
import os
import yaml
import json
from loguru import logger
from core.security import is_command_safe, sanitize_input
from core.remote import run_ssh_command
from core.command_map import get_command

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Audit log setup
logger.add('logs/audit.log', rotation='1 week', retention='1 month')

# Default infra config
DEFAULT_INFRA = {
    'servers': {
        'localhost': {
            'ip': '127.0.0.1',
            'user': 'local',
            'password': '',
            'os': 'linux'
        }
    }
}

# Load infra config
try:
    infra_path = 'infra_config.json'  # Change to use the actual JSON file now
    if os.path.exists(infra_path):
        with open(infra_path) as f:
            INFRA = {'servers': json.load(f)}  # Add a 'servers' key to maintain compatibility
            logger.info(f"Loaded infra config from {infra_path} with {len(INFRA['servers'])} servers")
    else:
        logger.warning(f"Infra config not found at {infra_path}, trying legacy path")
        infra_path = 'config/infra.yaml'
        if os.path.exists(infra_path):
            with open(infra_path) as f:
                INFRA = yaml.safe_load(f)
                logger.info(f"Loaded legacy infra config from {infra_path}")
        else:
            logger.warning(f"No infra config found, using defaults")
            INFRA = DEFAULT_INFRA
except Exception as e:
    logger.error(f"Error loading infra config: {str(e)}")
    INFRA = DEFAULT_INFRA

async def run_command_async(cmd: str, timeout: int = 30, user: str = None, server: str = None, metric: str = None) -> dict:
    # Log initial parameters
    logger.info(f"run_command_async called with: cmd='{cmd}', server={server}, metric={metric}")
    
    # Type check for cmd
    if not isinstance(cmd, str):
        logger.error(f"Invalid command type: {type(cmd)}, value: {cmd}")
        return {"success": False, "output": "Internal error: command is not a string", "return_code": -1}
        
    cmd = sanitize_input(cmd)
    logger.info(f"After sanitize_input, cmd='{cmd}'")
    
    # Security checks are now disabled in is_command_safe function
    # if not is_command_safe(cmd):
    #     logger.warning(f"Blocked unsafe command by {user}: '{cmd}'")
    #     return {"success": False, "output": "Command not allowed.", "return_code": -1}
    
    # We don't need legacy server mapping anymore as infra_config now uses these names directly
    # This section can be removed or simplified once all code is updated
    legacy_server_mapping = {
        'web-server-01': 'web01',
        'db-server-01': 'db01', 
        'app-server-01': 'app01'
    }
    
    # If the provided server name is a canonical name, convert it to the legacy name used in config
    if server in legacy_server_mapping:
        logger.info(f"Converting canonical server name '{server}' to legacy name '{legacy_server_mapping[server]}'")
        server = legacy_server_mapping[server]
    
    # If server is specified, use remote execution
    if server and server in INFRA.get('servers', {}):
        server_info = INFRA['servers'][server]
        os_type = server_info.get('os', 'linux')
        
        # If we have a metric but no command, get one based on the metric
        if metric and not cmd:
            try:
                logger.info(f"Getting command for OS {os_type}, metric {metric}")
                new_cmd = get_command(os_type, metric)
                # Ensure the returned command is a string
                if not isinstance(new_cmd, str):
                    logger.error(f"get_command returned non-string: {type(new_cmd)}, value: {new_cmd}")
                    return {"success": False, "output": "Internal error: invalid command format", "return_code": -1}
                if new_cmd:  # Only update if we got a valid command
                    cmd = new_cmd
                    logger.info(f"Using metric-based command: '{cmd}'")
                else:
                    logger.warning(f"No command found for OS {os_type} and metric {metric}")
                    # If metric is a service name, try a default service check command
                    if metric in ['nginx', 'tomcat', 'mysql', 'rabbitmq', 'memcache', 'memcached']:
                        cmd = f"systemctl status {metric}"
                        logger.info(f"Using fallback service status command: '{cmd}'")
            except Exception as e:
                logger.error(f"Error in get_command: {str(e)}")
                return {"success": False, "output": f"Error getting command: {str(e)}", "return_code": -1}
        
        # Special case for network diagnostic commands that need a target
        if cmd and cmd.startswith('ping') and 'localhost' in cmd and server:
            # Replace localhost with the actual server target
            cmd = cmd.replace('localhost', server)
            logger.info(f"Updated ping command to target server: '{cmd}'")
        # Handle case where user provided ping command with no target or with localhost
        elif cmd and cmd == 'ping' and server:
            # Add the server as the target
            cmd = f"ping -c 4 {server_info['ip']}"
            logger.info(f"Added target to ping command: '{cmd}'")
        # Handle user-supplied ping command that might have parameters but no explicit host
        elif cmd and cmd.startswith('ping') and ' ' in cmd and not any(part in cmd for part in ['.', 'localhost', '127.0.0.1']) and server:
            # Add the server as the target
            cmd = f"{cmd} {server_info['ip']}"
            logger.info(f"Added target to ping command with params: '{cmd}'")
                
        # Check again that the command is safe after substituting with metric
        # Security checks are now disabled
        # if cmd and not is_command_safe(cmd):
        #     logger.warning(f"Blocked unsafe metric-based command by {user}: '{cmd}'")
        #     return {"success": False, "output": "Command not allowed after metric substitution.", "return_code": -1}
                
        # Check if OS type is Linux or CentOS (which is also Linux-based)
        if os_type.lower() == 'linux' or 'centos' in os_type.lower() or 'ubuntu' in os_type.lower():
            try:
                if not cmd:
                    logger.warning("No command to execute after processing")
                    return {"success": False, "output": "No command specified or generated.", "return_code": -1}
                    
                logger.info(f"Executing command on {server} ({server_info['ip']}): '{cmd}'")
                ok, output = run_ssh_command(server_info['ip'], server_info['user'], server_info['password'], cmd, timeout, server)
                logger.info(f"User {user} ran remotely on {server}: '{cmd}', success={ok}")
                return {"success": ok, "output": output, "return_code": 0 if ok else 1}
            except Exception as e:
                logger.error(f"SSH execution error: {str(e)}")
                return {"success": False, "output": f"SSH error: {str(e)}", "return_code": -1}
        # For unsupported OS types
        else:
            logger.warning(f"Unsupported OS type for remote execution: {os_type}")
            return {"success": False, "output": f"Unsupported OS type: {os_type}", "return_code": -1}
    
    # Log what we're doing
    logger.info(f"No server specified or server not found, running local command: '{cmd}'")
    
    # Ensure we have a command to execute
    if not cmd:
        logger.warning("No command to execute locally")
        return {"success": False, "output": "No command specified for local execution.", "return_code": -1}
    
    # Fallback: local execution (for dev/testing)
    for attempt in range(3):  # Retry logic
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.error(f"Command timed out: '{cmd}'")
                return {"success": False, "output": "Timeout", "return_code": -1}
            rc = proc.returncode
            output = stdout.decode() + (stderr.decode() if rc != 0 else '')
            logger.info(f"User {user} ran locally: '{cmd}' (rc={rc})")
            return {"success": rc == 0, "output": output.strip(), "return_code": rc}
        except Exception as e:
            logger.error(f"Error running command (attempt {attempt+1}): '{cmd}' - {e}")
            await asyncio.sleep(1)
    return {"success": False, "output": "Failed after retries", "return_code": -1} 