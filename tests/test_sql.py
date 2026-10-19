import pytest

from wheelhouse.safety.sql import read_only_sql_reason

READ_ONLY = [
    ("SELECT 1", "mysql"),
    ("SELECT id, status FROM orders WHERE created_at > NOW() - INTERVAL 1 DAY", "mysql"),
    ("SELECT a FROM t UNION SELECT b FROM u", "mysql"),
    ("SHOW TABLES", "mysql"),
    ("DESCRIBE orders", "mysql"),
    ("EXPLAIN SELECT * FROM orders", "mysql"),
    ("WITH x AS (SELECT 1 AS a) SELECT a FROM x", "postgres"),
    ("SELECT count(*) FROM pg_stat_activity", "postgres"),
    ("SELECT DATE_FORMAT(NOW(), '%Y-%m-%d'), COALESCE(a, 0) FROM t GROUP BY a", "mysql"),
    ("SHOW TABLE STATUS", "mysql"),
    (
        "SELECT a, b + 1, -c, NOT d, a AND b OR c, a IN (1, 2), a BETWEEN 1 AND 2, a IS NULL, "
        "a LIKE 'x', a <> 2, a XOR b, EXISTS (SELECT 1), CASE WHEN a THEN 1 ELSE 0 END "
        "FROM t JOIN u ON t.id = u.id WHERE a > 1 GROUP BY a HAVING COUNT(*) > 1 "
        "ORDER BY a LIMIT 10",
        "mysql",
    ),
]

REFUSED = [
    ("", "mysql"),
    ("DELETE FROM orders", "mysql"),
    ("DROP TABLE orders", "mysql"),
    ("TRUNCATE TABLE orders", "mysql"),
    ("UPDATE t SET a = 1", "mysql"),
    ("INSERT INTO t VALUES (1)", "mysql"),
    ("SELECT 1; DROP TABLE t", "mysql"),
    ("SELECT 1 /*!50000 , (SELECT 1) */", "mysql"),
    ("/*!DROP TABLE t*/ SELECT 1", "mysql"),
    ("SELECT * FROM t INTO OUTFILE '/tmp/x'", "mysql"),
    ("SELECT 1 FOR UPDATE", "mysql"),
    ("SELECT SLEEP(10)", "mysql"),
    ("SELECT BENCHMARK(1000000, MD5('a'))", "mysql"),
    ("SELECT LOAD_FILE('/etc/passwd')", "mysql"),
    ("EXPLAIN ANALYZE SELECT * FROM t", "mysql"),
    ("LOCK TABLES t READ", "mysql"),
    ("CALL cleanup()", "mysql"),
    ("SET GLOBAL read_only = 0", "mysql"),
    ("GRANT ALL ON *.* TO x", "mysql"),
    ("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "postgres"),
    ("SELECT pg_sleep(10)", "postgres"),
    ("SELECT pg_terminate_backend(123)", "postgres"),
    ("SELECT pg_read_file('/etc/passwd')", "postgres"),
    ("SELECT nextval('s')", "postgres"),
    ("COPY t TO '/tmp/x'", "postgres"),
    ("SELECT 1", "oracle"),
    ("SELECT " + "1," * 6000 + "1", "mysql"),
    # From the security review.
    ("SHOW PROCESSLIST", "mysql"),
    ("SHOW GRANTS", "mysql"),
    ("SELECT MASTER_POS_WAIT('f', 1, 100)", "mysql"),
    ("SELECT WAIT_FOR_EXECUTED_GTID_SET('x', 100)", "mysql"),
    ("SELECT IS_FREE_LOCK('a')", "mysql"),
    ("SELECT my_udf(1)", "mysql"),
    ("SELECT sys.ps_setup_enable_consumer('x')", "mysql"),
    ("SELECT REGEXP_LIKE(REPEAT('a', 30), '(a+)+b')", "mysql"),
    ("SELECT 1 /* \\c */", "mysql"),
    ("SELECT 1 -- \\c", "mysql"),
    ("SELECT 'a\\'b'", "mysql"),
]


@pytest.mark.parametrize(("sql", "dialect"), READ_ONLY)
def test_read_only(sql: str, dialect: str) -> None:
    assert read_only_sql_reason(sql, dialect) is None


@pytest.mark.parametrize(("sql", "dialect"), REFUSED, ids=lambda v: str(v)[:40])
def test_refused(sql: str, dialect: str) -> None:
    assert read_only_sql_reason(sql, dialect) is not None
