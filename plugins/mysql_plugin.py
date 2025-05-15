def register():
    return {
        'service': 'mysql',
        'commands': [
            'systemctl status mysql',
            'mysql -V',
            'mysqladmin status',
            'tail -n 100 /var/log/mysql/error.log',
        ],
        'handlers': {
            'check_logs': lambda: 'tail -n 100 /var/log/mysql/error.log',
        }
    } 