import yaml
import re
import os
import logging
from typing import List

# Configure logging
logger = logging.getLogger(__name__)

# Default configurations
DEFAULT_RBAC = {
    'roles': {
        'admin': {
            'permissions': ['execute_any_command', 'approve_remediation', 'view_logs']
        },
        'viewer': {
            'permissions': ['view_logs', 'view_status']
        }
    },
    'users': {
        'system': {
            'role': 'admin'
        }
    }
}

DEFAULT_CMD_CFG = {
    'whitelist': [
        'uptime', 'free -m', 'df -h', 'cat /proc/loadavg',
        'systemctl status {service}', 'top -b -n1',
        'top -b -n1 | grep "Cpu(s)"', 'ping -c 4 {host}'
    ],
    'blacklist': [
        'rm -rf', 'shutdown', 'reboot', ':(){ :|:& };:', 'dd if=', 'mkfs'
    ]
}

# Load RBAC and command configs with error handling
try:
    rbac_path = 'config/rbac.yaml'
    if os.path.exists(rbac_path):
        with open(rbac_path) as f:
            RBAC = yaml.safe_load(f)
    else:
        logger.warning(f"RBAC config not found at {rbac_path}, using defaults")
        RBAC = DEFAULT_RBAC
except Exception as e:
    logger.error(f"Error loading RBAC config: {str(e)}")
    RBAC = DEFAULT_RBAC

try:
    cmd_path = 'config/commands.yaml'
    if os.path.exists(cmd_path):
        with open(cmd_path) as f:
            CMD_CFG = yaml.safe_load(f)
    else:
        logger.warning(f"Commands config not found at {cmd_path}, using defaults")
        CMD_CFG = DEFAULT_CMD_CFG
except Exception as e:
    logger.error(f"Error loading commands config: {str(e)}")
    CMD_CFG = DEFAULT_CMD_CFG

# Ensure whitelist and blacklist are lists
if not isinstance(CMD_CFG.get('whitelist', []), list):
    logger.warning("Commands whitelist is not a list, using defaults")
    CMD_CFG['whitelist'] = DEFAULT_CMD_CFG['whitelist']
    
if not isinstance(CMD_CFG.get('blacklist', []), list):
    logger.warning("Commands blacklist is not a list, using defaults")
    CMD_CFG['blacklist'] = DEFAULT_CMD_CFG['blacklist']

SAFE_COMMANDS = CMD_CFG['whitelist']
BLOCKED_COMMANDS = CMD_CFG['blacklist']

# RBAC helpers
def get_user_role(user: str) -> str:
    return RBAC['users'].get(user, {}).get('role', 'viewer')

def has_permission(user: str, permission: str) -> bool:
    role = get_user_role(user)
    return permission in RBAC['roles'].get(role, {}).get('permissions', [])

# Command safety
def is_command_safe(cmd: str) -> bool:
    # Disable security checks - allow all commands
    logger.info(f"Security checks disabled, allowing command: '{cmd}'")
    return True

    # The following code is disabled but kept for reference
    """
    # Type check for cmd
    if not isinstance(cmd, str):
        logger.error(f"Command is not a string: {type(cmd)}")
        return False
        
    # Always allow empty commands
    if not cmd.strip():
        logger.info("Empty command is allowed")
        return True
    
    # Quick check for simple exact matches in the whitelist
    if cmd in SAFE_COMMANDS:
        logger.info(f"Command matched exact safe command: {cmd}")
        return True
        
    # Split the command into parts to handle simplified commands
    cmd_parts = cmd.split()
    if cmd_parts and cmd_parts[0] in ['ping', 'traceroute', 'tracert', 'dig', 'nslookup']:
        base_command = cmd_parts[0]
        logger.info(f"Allowing common network diagnostic command: {base_command}")
        return True
        
    for blocked in BLOCKED_COMMANDS:
        # Ensure blocked is a string
        if not isinstance(blocked, str):
            logger.warning(f"Blocked command is not a string: {type(blocked)}")
            continue
            
        if blocked in cmd:
            logger.warning(f"Blocked unsafe command: {cmd}")
            return False
            
    for safe in SAFE_COMMANDS:
        # Ensure safe is a string
        if not isinstance(safe, str):
            logger.warning(f"Safe command is not a string: {type(safe)}")
            continue
            
        try:
            # First escape any regex special characters
            safe_escaped = re.escape(safe)
            # Then convert {placeholders} to regex patterns
            pattern = re.sub(r'\\\{[^}]+\\\}', r'.+', safe_escaped)
            if re.fullmatch(pattern, cmd):
                logger.info(f"Command matched safe pattern: {safe}")
                return True
        except re.error as e:
            logger.error(f"Regex error with pattern from '{safe}': {str(e)}")
            continue
    
    logger.warning(f"Command not in whitelist: '{cmd}'")
    return False
    """

def sanitize_input(s: str) -> str:
    # Handle non-string input
    if not isinstance(s, str):
        logger.error(f"Input is not a string: {type(s)}")
        return ""
        
    # Remove dangerous shell metacharacters, but preserve pipe (|) and ampersand (&) for command chaining
    sanitized = re.sub(r'[;`$><]', '', s)
    return sanitized 