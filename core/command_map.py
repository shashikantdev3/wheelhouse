COMMANDS = {
    'linux': {
        'cpu': 'top -b -n1 | grep "Cpu(s)"',
        'memory': 'free -m',
        'disk': 'df -h',
        'uptime': 'uptime',
        'load': 'cat /proc/loadavg',
        'tomcat': 'systemctl status tomcat',
        'nginx': 'systemctl status nginx',
        'mysql': 'systemctl status mysql',
        'rabbitmq': 'systemctl status rabbitmq-server',
        'memcache': 'systemctl status memcached',
        # Network diagnostic commands
        'ping': 'ping -c 4 localhost',
        'network': 'ip a',
        'netstat': 'netstat -tuln',
        'ports': 'ss -tuln',
        'dns': 'dig +short',
        'route': 'ip route',
        # Status command for default health check
        'status': 'uptime && free -m && df -h',
    },
    'centos/stream9': {
        'cpu': 'top -b -n1 | grep "Cpu(s)"',
        'memory': 'free -m',
        'disk': 'df -h',
        'uptime': 'uptime',
        'load': 'cat /proc/loadavg',
        'tomcat': 'systemctl status tomcat',
        'nginx': 'systemctl status nginx',
        'mysql': 'systemctl status mysqld',  # Note: MySQL service name in CentOS is mysqld
        'rabbitmq': 'systemctl status rabbitmq-server',
        'memcache': 'systemctl status memcached',
        # Network diagnostic commands
        'ping': 'ping -c 4 localhost',
        'network': 'ip a',
        'netstat': 'netstat -tuln',
        'ports': 'ss -tuln',
        'dns': 'dig +short',
        'route': 'ip route',
        # Status command for default health check
        'status': 'uptime && free -m && df -h',
    },
    'ubuntu/jammy64': {
        'cpu': 'top -b -n1 | grep "Cpu(s)"',
        'memory': 'free -m',
        'disk': 'df -h',
        'uptime': 'uptime',
        'load': 'cat /proc/loadavg',
        'tomcat': 'systemctl status tomcat',
        'nginx': 'systemctl status nginx',
        'mysql': 'systemctl status mysql',  # MySQL service name in Ubuntu
        'rabbitmq': 'systemctl status rabbitmq-server',
        'memcache': 'systemctl status memcached',
        # Network diagnostic commands
        'ping': 'ping -c 4 localhost',
        'network': 'ip a',
        'netstat': 'netstat -tuln',
        'ports': 'ss -tuln',
        'dns': 'dig +short',
        'route': 'ip route',
        # Status command for default health check
        'status': 'uptime && free -m && df -h',
    }
}

def get_command(os_type: str, metric: str) -> str:
    return COMMANDS.get(os_type, {}).get(metric, '') 