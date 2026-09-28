"""Markdown table helpers for the generated reports."""

import pandas as pd


def _fmt(v, floatfmt: str) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return "" if pd.isna(v) else format(v, floatfmt)
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def markdown_table(headers: list[str], rows: list[list], floatfmt: str = ",.2f") -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_fmt(v, floatfmt) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def df_to_markdown(df: pd.DataFrame, floatfmt: str = ",.2f") -> str:
    rows = [[v.item() if hasattr(v, "item") else v for v in r] for r in df.itertuples(index=False)]
    return markdown_table([str(c) for c in df.columns], rows, floatfmt)
