import paramiko
import logging
import random
import os
import glob
from typing import Tuple
from loguru import logger

# Configure logger
log = logging.getLogger(__name__)

# Check if we're in simulation mode (for development/testing)
SIMULATION_MODE = os.environ.get('SIMULATION_MODE', 'false').lower() in ('true', '1', 'yes')

# Base directory for vagrant private keys
VAGRANT_DIR = 'Local_infra_setup_script_IaC/.vagrant'

# Simulated responses for different commands
SIMULATED_RESPONSES = {
    'systemctl status nginx': (True, '''
● nginx.service - A high performance web server and a reverse proxy server
   Loaded: loaded (/lib/systemd/system/nginx.service; enabled; vendor preset: enabled)
   Active: active (running) since Thu 2025-05-16 00:10:31 UTC; 2h 42min ago
     Docs: man:nginx(8)
 Main PID: 1234 (nginx)
    Tasks: 2 (limit: 1153)
   Memory: 9.2M
   CGroup: /system.slice/nginx.service
           ├─1234 nginx: master process /usr/sbin/nginx -g daemon on; master_process on;
           └─1235 nginx: worker process
'''),
    'systemctl status tomcat': (True, '''
● tomcat.service - Apache Tomcat Web Application Container
   Loaded: loaded (/etc/systemd/system/tomcat.service; enabled; vendor preset: enabled)
   Active: active (running) since Thu 2025-05-16 00:15:23 UTC; 2h 37min ago
 Main PID: 1432 (java)
    Tasks: 29 (limit: 1153)
   Memory: 435.2M
   CGroup: /system.slice/tomcat.service
           └─1432 /usr/bin/java -Djava.util.logging.config.file=/opt/tomcat/conf/logging.properties...
'''),
    'systemctl status mysql': (True, '''
● mysql.service - MySQL Community Server
   Loaded: loaded (/lib/systemd/system/mysql.service; enabled; vendor preset: enabled)
   Active: active (running) since Thu 2025-05-16 00:05:41 UTC; 2h 47min ago
 Main PID: 1011 (mysqld)
    Tasks: 28 (limit: 1153)
   Memory: 325.0M
   CGroup: /system.slice/mysql.service
           └─1011 /usr/sbin/mysqld
'''),
    'systemctl status mysqld': (True, '''
● mysqld.service - MySQL Server
   Loaded: loaded (/usr/lib/systemd/system/mysqld.service; enabled; vendor preset: disabled)
   Active: active (running) since Thu 2025-05-16 00:05:41 UTC; 2h 47min ago
  Process: 957 ExecStartPre=/usr/bin/mysqld_pre_systemd (code=exited, status=0/SUCCESS)
 Main PID: 1011 (mysqld)
    Tasks: 28
   Memory: 325.0M
   CGroup: /system.slice/mysqld.service
           └─1011 /usr/sbin/mysqld
'''),
    'uptime': (True, '''
 00:53:02 up 2:47, 1 user, load average: 0.08, 0.12, 0.10
'''),
    'free -m': (True, '''
               total        used        free      shared  buff/cache   available
Mem:            8032        1234        3854          22        2944        6540
Swap:           2048           0        2048
'''),
    'df -h': (True, '''
Filesystem      Size  Used Avail Use% Mounted on
udev            3.9G     0  3.9G   0% /dev
tmpfs           795M  1.7M  793M   1% /run
/dev/sda1        98G   25G   69G  27% /
tmpfs           3.9G     0  3.9G   0% /dev/shm
tmpfs           5.0M     0  5.0M   0% /run/lock
'''),
    'top -b -n1 | grep "Cpu(s)"': (True, '''
%Cpu(s):  5.9 us,  3.4 sy,  0.0 ni, 89.5 id,  0.2 wa,  0.0 hi,  0.9 si,  0.0 st
'''),
    'cat /proc/loadavg': (True, '''
0.08 0.12 0.10 2/345 1011
'''),
}

def find_private_key(server_name: str) -> str:
    """Find the private key file for a given server"""
    # Check for server-specific key first
    key_patterns = [
        f"{VAGRANT_DIR}/machines/{server_name}/*/private_key",
        f"{VAGRANT_DIR}/*/{server_name}/private_key",
        f"{VAGRANT_DIR}/**/{server_name}*/**/private_key"
    ]
    
    for pattern in key_patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            logger.info(f"Found private key for {server_name}: {matches[0]}")
            return matches[0]
    
    # Fallback to any available key
    all_keys = glob.glob(f"{VAGRANT_DIR}/**/private_key", recursive=True)
    if all_keys:
        logger.info(f"Using fallback private key for {server_name}: {all_keys[0]}")
        return all_keys[0]
    
    logger.warning(f"No private key found for {server_name}")
    return ""

def run_ssh_command(host: str, user: str, password: str = None, command: str = "", timeout: int = 30, server_name: str = "") -> Tuple[bool, str]:
    """Execute a command on a remote server via SSH"""
    if not host or not command:
        log.error(f"Missing required parameter: host={bool(host)}, command={bool(command)}")
        return False, "Missing required parameters for SSH connection"
    
    # Use simulation mode for development/testing
    if SIMULATION_MODE:
        logger.info(f"[SIMULATION MODE] Executing command on {host} ({server_name}): '{command}'")
        
        # Check for exact command match
        if command in SIMULATED_RESPONSES:
            success, output = SIMULATED_RESPONSES[command]
            logger.info(f"[SIMULATION MODE] Returning simulated response for '{command}'")
            return success, output
            
        # Check for command pattern match
        for cmd_pattern, (success, output) in SIMULATED_RESPONSES.items():
            if command.startswith(cmd_pattern.split()[0]):
                logger.info(f"[SIMULATION MODE] Returning simulated response for pattern '{cmd_pattern}'")
                return success, output
        
        # Default response for unknown commands
        if 'status' in command:
            logger.info(f"[SIMULATION MODE] Returning generic status response")
            return True, f"Service is running\nSimulated response for: {command}"
            
        logger.info(f"[SIMULATION MODE] No matching simulation, returning generic response")
        return True, f"Simulated output for: {command}\nServer: {host}\nUser: {user}"
        
    # Real SSH connection
    try:
        # Find private key for this server if server_name is provided
        key_file = ""
        if server_name:
            key_file = find_private_key(server_name)
        
        logger.info(f"Connecting to {host} as {user}" + (f" using key {key_file}" if key_file else ""))
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Use private key if available, fall back to password
        if key_file and os.path.exists(key_file):
            try:
                ssh.connect(
                    hostname=host,
                    username=user,
                    key_filename=key_file,
                    timeout=timeout
                )
            except paramiko.SSHException as e:
                logger.warning(f"Failed to connect with key, trying without key: {str(e)}")
                if password:
                    ssh.connect(host, username=user, password=password, timeout=timeout)
                else:
                    raise
        else:
            # Fall back to password authentication if no key available
            if password:
                ssh.connect(host, username=user, password=password, timeout=timeout)
            else:
                raise paramiko.AuthenticationException("No private key or password provided")
        
        logger.info(f"Executing command on {host}: {command}")
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        
        output = stdout.read().decode()
        error = stderr.read().decode()
        ssh.close()
        
        if error:
            logger.warning(f"Command returned error on {host}: {error.strip()}")
            return False, error.strip()
            
        logger.info(f"Command executed successfully on {host}")
        return True, output.strip()
    except paramiko.AuthenticationException:
        logger.error(f"Authentication failed for {user}@{host}")
        return False, "Authentication failed"
    except paramiko.SSHException as e:
        logger.error(f"SSH connection error to {host}: {str(e)}")
        return False, f"SSH connection error: {str(e)}"
    except Exception as e:
        logger.error(f"Error executing command on {host}: {str(e)}")
        return False, str(e) 