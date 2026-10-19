CREATE DATABASE IF NOT EXISTS app;
USE app;
CREATE TABLE IF NOT EXISTS orders (
  id INT PRIMARY KEY AUTO_INCREMENT,
  status VARCHAR(16) NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO orders (status, amount) SELECT 'paid', 120.50 FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM orders);
INSERT INTO orders (status, amount) SELECT 'new', 42.00 FROM DUAL
  WHERE (SELECT COUNT(*) FROM orders) < 2;
CREATE TABLE IF NOT EXISTS orders_daily (day DATE PRIMARY KEY, orders INT, revenue DECIMAL(12,2));
-- The account Wheelhouse uses: read-only on app.*, nothing else (no access to mysql.*),
-- and only through the local socket as the OS user 'wheelhouse', so no password exists.
CREATE USER IF NOT EXISTS 'wheelhouse'@'localhost' IDENTIFIED VIA unix_socket;
GRANT SELECT, SHOW VIEW ON app.* TO 'wheelhouse'@'localhost';
-- Server-side limit: any statement from this account stops after 30 seconds.
ALTER USER 'wheelhouse'@'localhost' WITH MAX_STATEMENT_TIME 30;
FLUSH PRIVILEGES;
