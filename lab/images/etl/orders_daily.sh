#!/bin/sh
# Lab ETL job: summarises today's orders into app.orders_daily.
set -eu
mariadb --defaults-file=/etc/etl/etl.cnf app -e "
REPLACE INTO orders_daily (day, orders, revenue)
SELECT DATE(created_at), COUNT(*), SUM(amount) FROM orders
WHERE created_at >= CURRENT_DATE GROUP BY DATE(created_at);"
echo "orders_daily: loaded summary for $(date -u +%F)"
