"""Read-only SQL check.

Only a single, read-only statement passes: SELECT (including UNION, INTERSECT, EXCEPT),
MySQL SHOW, DESCRIBE, and EXPLAIN without ANALYZE. Anything the parser cannot fully
understand is refused. Refusing a harmless query is acceptable; allowing a harmful one
is not.
"""

from __future__ import annotations

import sqlglot
from sqlglot import TokenType, exp
from sqlglot.errors import SqlglotError

MAX_SQL_LENGTH = 10_000

SUPPORTED_DIALECTS = frozenset({"mysql", "postgres"})

_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.Show,
    exp.Describe,
)

_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Into,
    exp.Lock,
    exp.Set,
    exp.Use,
    exp.Copy,
)

# Allowlist of pure, cheap built-in functions (names as sqlglot reports them).
# Anything else, including user-defined and schema-qualified functions, is refused.
_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # sqlglot models these logical operators as functions.
        "and",
        "or",
        "xor",
        "exists",
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "group_concat",
        "string_agg",
        "coalesce",
        "nullif",
        "if",
        "case",
        "greatest",
        "least",
        "cast",
        "try_cast",
        "concat",
        "concat_ws",
        "lower",
        "upper",
        "length",
        "substring",
        "trim",
        "replace",
        "left",
        "right",
        "lpad",
        "rpad",
        "round",
        "floor",
        "ceil",
        "abs",
        "mod",
        "current_timestamp",
        "current_date",
        "current_time",
        "now",
        "unix_timestamp",
        "curdate",
        "utc_timestamp",
        "ts_or_ds_to_date",
        "ts_or_ds_to_timestamp",
        "time_to_str",
        "str_to_time",
        "unix_to_time",
        "date_add",
        "date_sub",
        "datediff",
        "timestamp_diff",
        "timestampdiff",
        "date_trunc",
        "extract",
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "dayofweek",
        "json_extract",
        "json_extract_scalar",
    }
)

# SHOW statements allowed (MySQL). PROCESSLIST and GRANTS can expose other sessions'
# queries and privileges, so they are not on the list.
_ALLOWED_SHOW: frozenset[str] = frozenset(
    {
        "TABLES",
        "FULL TABLES",
        "DATABASES",
        "COLUMNS",
        "FULL COLUMNS",
        "INDEX",
        "STATUS",
        "TABLE STATUS",
        "REPLICA STATUS",
        "CREATE TABLE",
        "CREATE VIEW",
        "ENGINES",
        "WARNINGS",
        "ERRORS",
        "CHARACTER SET",
        "COLLATION",
    }
)


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return str(node.sql_name()).lower()


def read_only_sql_reason(sql: str, dialect: str = "mysql") -> str | None:
    """Return why the SQL is not a single read-only statement, or None if it is."""
    if dialect not in SUPPORTED_DIALECTS:
        return f"dialect '{dialect}' is not supported"
    if not isinstance(sql, str) or not sql.strip():
        return "empty statement"
    if len(sql) > MAX_SQL_LENGTH:
        return "statement too long"
    if "\x00" in sql:
        return "control character in statement"
    # MySQL runs code inside /*! ... */ comments. A parser treats it as a comment.
    if "/*!" in sql or "/*M!" in sql.upper():
        return "MySQL executable comments are not allowed"
    # The mysql command-line client runs backslash commands (\! shell, \. source file)
    # even inside --execute. Refuse any backslash for MySQL; escapes are rarely needed
    # in diagnostic queries.
    if dialect == "mysql" and "\\" in sql:
        return "backslashes are not allowed in MySQL statements"

    try:
        tokens = sqlglot.tokenize(sql, read=dialect)
    except SqlglotError:
        return "statement could not be parsed"
    if any(t.token_type == TokenType.ANALYZE or t.text.upper() == "ANALYZE" for t in tokens):
        return "ANALYZE executes the statement"

    try:
        parsed = [p for p in sqlglot.parse(sql, read=dialect) if p is not None]
    except SqlglotError:
        return "statement could not be parsed"
    if len(parsed) != 1:
        return "exactly one statement is allowed"

    root = parsed[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        return f"'{type(root).__name__}' statements are not read-only"
    if isinstance(root, exp.Describe) and root.find(*_FORBIDDEN_NODES):
        return "DESCRIBE or EXPLAIN of a write statement"
    if isinstance(root, exp.Show):
        kind = str(root.this or "").upper()
        if kind not in _ALLOWED_SHOW:
            return f"SHOW {kind or '?'} is not on the allowed list"

    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            return f"'{type(node).__name__}' is not allowed in a read-only statement"
        if isinstance(node, exp.Dot) and node.find(exp.Func):
            return "schema-qualified function calls are not allowed"
        if isinstance(node, exp.Func) and _function_name(node) not in _ALLOWED_FUNCTIONS:
            return f"function '{_function_name(node)}' is not on the allowed list"
    return None


def is_read_only_sql(sql: str, dialect: str = "mysql") -> bool:
    return read_only_sql_reason(sql, dialect) is None
