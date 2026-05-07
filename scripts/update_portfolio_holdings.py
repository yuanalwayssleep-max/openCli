#!/usr/bin/env python3
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from fetch_eastmoney_stock_data import fetch_daily_k, fetch_intraday, to_secid

ROOT = Path(__file__).resolve().parents[1]
HOLDINGS_PATH = ROOT / "data" / "持仓明细.csv"


def to_decimal(value: str) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def format_decimal(value: Decimal, places: str = "0.00") -> str:
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def get_latest_price(code: str) -> Decimal | None:
    secid, _ = to_secid(code)

    intraday_rows = fetch_intraday(secid, 1)
    if intraday_rows:
        latest = to_decimal(intraday_rows[-1]["最新价"])
        if latest is not None:
            return latest

    daily_rows = fetch_daily_k(secid, 1)
    if daily_rows:
        return to_decimal(daily_rows[-1]["收盘"])

    return None


def update_row(row: dict[str, str]) -> dict[str, str]:
    code = row["证券代码"].strip()
    quantity = to_decimal(row["持仓数量"])
    cost = to_decimal(row["持仓成本"])

    latest_price = get_latest_price(code)
    if latest_price is None:
        return row

    row["最新价"] = format_decimal(latest_price)

    if quantity is not None:
        market_value = quantity * latest_price
        row["持仓市值"] = format_decimal(market_value)

        if cost is not None:
            pnl = (latest_price - cost) * quantity
            pnl_rate = Decimal("0")
            if cost != 0:
                pnl_rate = ((latest_price - cost) / cost) * Decimal("100")
            row["浮动盈亏"] = format_decimal(pnl)
            row["浮动盈亏率"] = f"{format_decimal(pnl_rate)}%"

    return row


def main() -> None:
    with HOLDINGS_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise RuntimeError("持仓明细.csv 缺少表头")
        rows = [update_row(dict(row)) for row in reader]

    with HOLDINGS_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"updated holdings: {HOLDINGS_PATH}")


if __name__ == "__main__":
    main()
