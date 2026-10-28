"""Fail-closed T-SQL subset for a single approved semantic view."""

from dataclasses import dataclass
import re
import sqlglot
from sqlglot import exp, ErrorLevel
from sqlglot.tokens import TokenType
from src.services.errors import ServiceError

COLUMN_NAMES = (
    "Timestamp",
    "Latitude",
    "Longitude",
    "Current_Temperature_C",
    "Cargo_Condition_Code",
    "Risk_Classification",
    "Delay_Probability",
    "Port_Congestion_Level",
    "Route_Risk_Index",
)
COLUMNS = {name.lower() for name in COLUMN_NAMES}

ALLOWED_NODES = {
    exp.Select,
    exp.From,
    exp.Table,
    exp.TableAlias,
    exp.Identifier,
    exp.Column,
    exp.Star,
    exp.Alias,
    exp.Literal,
    exp.Boolean,
    exp.Null,
    exp.Where,
    exp.And,
    exp.Or,
    exp.Not,
    exp.Paren,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Between,
    exp.In,
    exp.Is,
    exp.Like,
    exp.Order,
    exp.Ordered,
    exp.Limit,
    exp.Group,
    exp.Having,
    exp.Distinct,
    exp.Count,
    exp.Sum,
    exp.Min,
    exp.Max,
    exp.Avg,
    exp.Neg,
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
}


class SqlPolicyError(ServiceError):
    pass


@dataclass(frozen=True)
class ValidatedQuery:
    expression: exp.Select
    sql: str


def validate_query(sql: str, *, row_limit=10, max_chars=8000) -> ValidatedQuery:
    def reject(reason):
        raise SqlPolicyError("SECURITY BLOCK: " + reason)

    if not isinstance(sql, str) or not sql.strip() or len(sql) > max_chars:
        reject("Query is empty or exceeds the SQL size limit.")
    try:
        tokens = sqlglot.tokenize(sql, read="tsql")
        # Reject non-SELECT syntax before the parser's unsupported-command fallback can log raw text.
        if not tokens or tokens[0].token_type != TokenType.SELECT:
            reject("Only one SELECT against the approved fleet view is supported.")
        statements = sqlglot.parse(sql, read="tsql", error_level=ErrorLevel.RAISE)
    except SqlPolicyError:
        raise
    except Exception:
        reject("Invalid or unsupported T-SQL.")
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        reject("Exactly one SELECT statement is required.")
    tree = statements[0]
    nodes = list(tree.walk())
    if len(nodes) > 200 or sum(isinstance(node, exp.Select) for node in nodes) != 1:
        reject("Query complexity or nested SELECT is not supported.")
    if any(type(node) not in ALLOWED_NODES for node in nodes):
        reject(
            "Unsupported SQL construct. Use simple filters, sorting, or COUNT/SUM/MIN/MAX/AVG."
        )
    if any(node.comments for node in nodes) or any(token.comments for token in tokens):
        reject("SQL comments are not supported.")
    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1:
        reject("Exactly one approved fleet view must be referenced.")
    table = tables[0]
    if (
        table.name.lower() != "vw_active_fleet"
        or table.db.lower() != "fde_views"
        or table.catalog
    ):
        reject("Only FDE_VIEWS.VW_ACTIVE_FLEET is accessible.")
    if table.args.get("alias") and table.args["alias"].args.get("columns"):
        reject("Table column aliases are unsupported.")
    aliases = {
        item.alias.lower() for item in tree.expressions if isinstance(item, exp.Alias)
    }
    qualifiers = {table.name.lower()}
    if table.alias:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", table.alias):
            reject("Invalid table alias.")
        qualifiers.add(table.alias.lower())
    for alias in aliases:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", alias):
            reject("Invalid output alias.")
    for column in tree.find_all(exp.Column):
        if (
            column.catalog
            or column.db
            or (column.table and column.table.lower() not in qualifiers)
        ):
            reject("Invalid column qualification.")
        # Output aliases are permitted only in ORDER BY; other columns must come from the view.
        ordered = column.find_ancestor(exp.Order) is not None
        if (
            not column.is_star
            and column.name.lower() not in COLUMNS
            and not (ordered and column.name.lower() in aliases)
        ):
            reject("Column is outside the approved fleet schema.")
    for literal in tree.find_all(exp.Literal):
        if len(literal.this) > 256:
            reject("SQL literal exceeds the size limit.")
    limit = tree.args.get("limit")
    maximum = row_limit
    if limit:
        value = limit.expression
        if (
            not isinstance(value, exp.Literal)
            or value.is_string
            or not value.this.isdigit()
            or int(value.this) < 1
        ):
            reject("TOP must be a positive integer literal.")
        maximum = min(maximum, int(value.this))
    # Wildcards expand to the fixed contract, not any columns later added to the view.
    for star in tree.find_all(exp.Star):
        if any(star.args.values()):
            reject("Wildcard modifiers are unsupported.")
    projections = []
    for projection in tree.expressions:
        if isinstance(projection, exp.Star) or (
            isinstance(projection, exp.Column) and projection.is_star
        ):
            qualifier = projection.table if isinstance(projection, exp.Column) else None
            projections.extend(
                exp.column(name, table=qualifier) for name in COLUMN_NAMES
            )
        else:
            projections.append(projection)
    tree.set("expressions", projections)
    # Canonicalize from the validated AST; never forward the original model text.
    tree = tree.limit(maximum)
    try:
        canonical = tree.sql(dialect="tsql", unsupported_level=ErrorLevel.RAISE)
    except Exception:
        reject("Cannot safely generate supported T-SQL.")
    return ValidatedQuery(tree, canonical)
