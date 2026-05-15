#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "a股快照_20260512.csv"
DEFAULT_OUTPUT = ROOT / "data" / "a_share_price_range_stats.csv"

DEFAULT_MAX_PRICE_BIN = 60

OUTPUT_FIELDS = [
    "价位区间",
    "总数",
    "上涨数",
    "上涨占比",
    "上涨平均涨幅",
    "下跌数",
    "下跌占比",
    "下跌平均跌幅",
    "平盘数",
    "平盘占比",
    "区间平均涨跌幅",
    "区间平均价格",
    "每元平均涨跌金额",
    "区间总成交额(亿)",
    "区间平均成交额(亿)",
    "上涨票平均成交额(亿)",
    "下跌票平均成交额(亿)",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按价位区间统计A股快照的上涨/下跌结构")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="输入A股快照CSV路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出统计CSV路径")
    parser.add_argument(
        "--include-growth-boards",
        action="store_true",
        help="包含创业板和科创板；默认剔除 300/301/302/688/689",
    )
    parser.add_argument(
        "--exclude-star-board-only",
        action="store_true",
        help="只剔除科创板 688/689，保留创业板；优先级高于默认剔除创业板和科创板",
    )
    parser.add_argument("--bin-size", type=int, default=10, help="价位区间宽度，默认10元")
    parser.add_argument(
        "--max-price-bin",
        type=int,
        default=DEFAULT_MAX_PRICE_BIN,
        help="超过该价格后合并为一个区间，默认60元",
    )
    parser.add_argument(
        "--price-field",
        default="最新价",
        choices=["最新价", "昨收", "今开", "最高", "最低"],
        help="用于价位分档的价格字段，默认最新价；复盘建议用昨收",
    )
    return parser.parse_args()


def to_float(raw: str) -> float | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def is_growth_or_star_board(code: str) -> bool:
    normalized = code.strip().zfill(6)
    return normalized.startswith(("300", "301", "302", "688", "689"))


def is_star_board(code: str) -> bool:
    normalized = code.strip().zfill(6)
    return normalized.startswith(("688", "689"))


def build_price_bins(bin_size: int, max_price_bin: int) -> list[tuple[str, float, float]]:
    if bin_size <= 0:
        raise ValueError("--bin-size 必须大于0")
    if max_price_bin <= 0:
        raise ValueError("--max-price-bin 必须大于0")
    bins: list[tuple[str, float, float]] = []
    low = 0
    while low < max_price_bin:
        high = low + bin_size
        bins.append((f"{low}-{high}元", low, high))
        low = high
    bins.append((f"{max_price_bin}元以上", max_price_bin, math.inf))
    return bins


def pct(value: int, total: int) -> str:
    if total == 0:
        return "0.00%"
    return f"{value / total * 100:.2f}%"


def avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def money_yi(row: dict[str, str]) -> float | None:
    amount = to_float(row.get("成交额", ""))
    if amount is None:
        return None
    return amount / 100000000


def read_snapshot(
    path: Path,
    include_growth_boards: bool,
    exclude_star_board_only: bool,
    price_field: str,
) -> tuple[list[dict[str, float]], int, int]:
    rows: list[dict[str, float]] = []
    excluded_boards = 0
    skipped = 0

    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = row.get("代码", "")
            if exclude_star_board_only and is_star_board(code):
                excluded_boards += 1
                continue
            if not exclude_star_board_only and not include_growth_boards and is_growth_or_star_board(code):
                excluded_boards += 1
                continue

            price = to_float(row.get(price_field, ""))
            pct_chg = to_float(row.get("涨跌幅", ""))
            amount = money_yi(row)
            if price is None or pct_chg is None or amount is None:
                skipped += 1
                continue

            rows.append({"price": price, "pct_chg": pct_chg, "amount_yi": amount})

    return rows, excluded_boards, skipped


def in_price_bin(row: dict[str, float], low: float, high: float) -> bool:
    return low <= row["price"] < high


def build_stats(rows: list[dict[str, float]], price_bins: list[tuple[str, float, float]]) -> list[dict[str, str]]:
    output_rows: list[dict[str, str]] = []

    for label, low, high in price_bins:
        bucket = [row for row in rows if in_price_bin(row, low, high)]
        up = [row for row in bucket if row["pct_chg"] > 0]
        down = [row for row in bucket if row["pct_chg"] < 0]
        flat = [row for row in bucket if row["pct_chg"] == 0]
        total = len(bucket)

        output_rows.append(
            {
                "价位区间": label,
                "总数": str(total),
                "上涨数": str(len(up)),
                "上涨占比": pct(len(up), total),
                "上涨平均涨幅": f"{avg([row['pct_chg'] for row in up]):.2f}%",
                "下跌数": str(len(down)),
                "下跌占比": pct(len(down), total),
                "下跌平均跌幅": f"{avg([row['pct_chg'] for row in down]):.2f}%",
                "平盘数": str(len(flat)),
                "平盘占比": pct(len(flat), total),
                "区间平均涨跌幅": f"{avg([row['pct_chg'] for row in bucket]):.2f}%",
                "区间平均价格": f"{avg([row['price'] for row in bucket]):.2f}",
                "每元平均涨跌金额": f"{avg([row['price'] for row in bucket]) * avg([row['pct_chg'] for row in bucket]) / 100:.4f}",
                "区间总成交额(亿)": f"{sum(row['amount_yi'] for row in bucket):.2f}",
                "区间平均成交额(亿)": f"{avg([row['amount_yi'] for row in bucket]):.2f}",
                "上涨票平均成交额(亿)": f"{avg([row['amount_yi'] for row in up]):.2f}",
                "下跌票平均成交额(亿)": f"{avg([row['amount_yi'] for row in down]):.2f}",
            }
        )

    return output_rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    rows, excluded_boards, skipped = read_snapshot(
        input_path,
        include_growth_boards=args.include_growth_boards,
        exclude_star_board_only=args.exclude_star_board_only,
        price_field=args.price_field,
    )
    price_bins = build_price_bins(args.bin_size, args.max_price_bin)
    stats = build_stats(rows, price_bins)
    write_csv(output_path, stats)

    print(
        f"input={input_path} output={output_path} valid={len(rows)} "
        f"excluded_growth_or_star={excluded_boards} skipped={skipped}"
    )
    for row in stats:
        print(",".join(row[field] for field in OUTPUT_FIELDS))


if __name__ == "__main__":
    main()
