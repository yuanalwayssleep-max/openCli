#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "outputs" / "eastmoney_hs_bj_a_shares.csv"
DEFAULT_OUTPUT = ROOT / "data" / "a_share_candidate_pool.csv"
DEFAULT_TOP3_OUTPUT = ROOT / "data" / "top3推荐.csv"
REFRESH_SCRIPT = ROOT / "scripts" / "fetch_eastmoney_a_shares.py"


@dataclass
class Candidate:
    exchange: str
    board: str
    code: str
    name: str
    price: float
    pct_chg: float
    amount: float
    amplitude: float
    volume_ratio: float
    turnover: float
    pe: float | None
    pb: float | None
    day_high: float
    day_low: float
    prev_close: float
    score: float
    reason: str
    priority: str
    build_zone: str
    risk_tip: str
    first_entry_ok: str
    action_tip: str
    top3_tag: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按练手量化规则筛选A股候选池")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="输入A股快照CSV路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出候选池CSV路径")
    parser.add_argument("--top3-output", default=str(DEFAULT_TOP3_OUTPUT), help="输出Top3推荐CSV路径")
    parser.add_argument("--top-n", type=int, default=20, help="输出前N只股票，默认20")
    parser.add_argument("--refresh", action="store_true", help="筛选前先刷新东方财富A股全市场快照")
    return parser.parse_args()


def to_float(raw: str) -> float | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def scaled_percent(row: dict[str, str], field: str) -> float | None:
    value = to_float(row[field])
    if value is None:
        return None
    return value / 100


def scaled_price(row: dict[str, str], field: str) -> float | None:
    value = to_float(row[field])
    if value is None:
        return None
    return value / 100


def scaled_ratio(row: dict[str, str], field: str) -> float | None:
    value = to_float(row[field])
    if value is None:
        return None
    return value / 100


def refresh_market_snapshot() -> None:
    subprocess.run(["python3", str(REFRESH_SCRIPT)], check=True)


def build_reason(price: float, amount: float, amplitude: float, turnover: float, pct_chg: float, volume_ratio: float) -> str:
    reasons: list[str] = []
    if amount >= 5_000_000_000:
        reasons.append("成交额高")
    elif amount >= 2_500_000_000:
        reasons.append("流动性达标")
    if 2 <= amplitude <= 6:
        reasons.append("振幅适中")
    if 3 <= turnover <= 10:
        reasons.append("换手率适中")
    if -1.5 <= pct_chg <= 4:
        reasons.append("涨幅未过热")
    if volume_ratio >= 1:
        reasons.append("量比健康")
    if 8 <= price <= 60:
        reasons.append("价格区间适合练手")
    return "、".join(reasons)


def priority_label(rank: int) -> str:
    if rank == 1:
        return "核心关注"
    if rank <= 3:
        return "优先观察"
    if rank <= 10:
        return "候选观察"
    return "备选"


def build_entry_zone(price: float, day_low: float, day_high: float, pct_chg: float) -> str:
    intraday_range = max(day_high - day_low, 0.01)
    if pct_chg >= 3:
        lower = max(day_low, price - intraday_range * 0.35)
        upper = max(lower, price - intraday_range * 0.15)
        return f"{lower:.2f}-{upper:.2f}回踩稳住再看，不追高"
    if pct_chg >= 0:
        lower = max(day_low, price - intraday_range * 0.25)
        upper = min(day_high, price - intraday_range * 0.05)
        return f"{lower:.2f}-{upper:.2f}企稳可分批看第一笔"
    lower = max(day_low, price - intraday_range * 0.15)
    upper = min(day_high, price + intraday_range * 0.10)
    return f"{lower:.2f}-{upper:.2f}止跌回收后再看"


def build_risk_tip(pct_chg: float, turnover: float, day_low: float, price: float, prev_close: float) -> str:
    if pct_chg >= 4:
        return f"当日涨幅偏高，若跌破{day_low:.2f}附近承接且收不回，不宜追高接力"
    if turnover >= 8:
        return f"换手已偏高，若重新跌破昨收{prev_close:.2f}附近，短线波动可能加剧"
    if pct_chg < 0:
        return f"仍属弱修复结构，若价格跌破{day_low:.2f}且无快速收回，当日建仓应放弃"
    return f"若跌破日内低点{day_low:.2f}或回踩后持续弱于昨收{prev_close:.2f}，应降低仓位预期"


def build_entry_ok(pct_chg: float, turnover: float, amplitude: float) -> str:
    if pct_chg >= 4:
        return "否"
    if turnover > 9.5 and amplitude > 5.5:
        return "否"
    if -1.0 <= pct_chg <= 3.5 and 2 <= amplitude <= 6 and turnover <= 9.5:
        return "是"
    return "观察后决定"


def build_action_tip(pct_chg: float, build_zone: str, first_entry_ok: str) -> str:
    if first_entry_ok == "否":
        return f"今天不追高，只有回踩关键区后重新企稳才看；参考区间：{build_zone}"
    if first_entry_ok == "是":
        return f"可按区间观察第一笔10%，只做试仓；参考区间：{build_zone}"
    return f"先观察承接与回收，再决定是否试10%；参考区间：{build_zone}"


def score_candidate(price: float, pct_chg: float, amount: float, amplitude: float, volume_ratio: float, turnover: float) -> float:
    base = amount / 1e9 * 2.0
    volatility = amplitude * 1.4
    activity = turnover * 0.9
    volume = volume_ratio * 1.0
    heat_penalty = abs(pct_chg - 1.0) * 1.1 + max(0, turnover - 8) * 0.4 + max(0, amplitude - 5) * 0.4
    price_penalty = 0.0 if 8 <= price <= 60 else 99.0
    return round(base + volatility + activity + volume - heat_penalty - price_penalty, 2)


def load_candidates(path: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["名称"]
            board = row["板块"]
            if name.startswith(("ST", "*ST", "SST", "N", "C")) or board == "北交所":
                continue

            price = scaled_price(row, "最新价")
            pct_chg = scaled_percent(row, "涨跌幅")
            amount = to_float(row["成交额"])
            amplitude = scaled_percent(row, "振幅")
            volume_ratio = scaled_ratio(row, "量比")
            turnover = scaled_percent(row, "换手率")
            pe = scaled_ratio(row, "市盈率")
            pb = scaled_ratio(row, "市净率")
            day_high = scaled_price(row, "最高")
            day_low = scaled_price(row, "最低")
            prev_close = scaled_price(row, "昨收")

            if None in (price, pct_chg, amount, amplitude, volume_ratio, turnover, day_high, day_low, prev_close):
                continue

            if not (8 <= price <= 60):
                continue
            if amount < 2_500_000_000:
                continue
            if not (2 <= amplitude <= 6):
                continue
            if not (3 <= turnover <= 10):
                continue
            if volume_ratio < 0.9:
                continue
            if not (-1.5 <= pct_chg <= 4):
                continue

            score = score_candidate(price, pct_chg, amount, amplitude, volume_ratio, turnover)
            reason = build_reason(price, amount, amplitude, turnover, pct_chg, volume_ratio)
            candidates.append(
                Candidate(
                    exchange=row["交易所"],
                    board=board,
                    code=row["代码"],
                    name=name,
                    price=price,
                    pct_chg=pct_chg,
                    amount=amount,
                    amplitude=amplitude,
                    volume_ratio=volume_ratio,
                    turnover=turnover,
                    pe=pe,
                    pb=pb,
                    day_high=day_high,
                    day_low=day_low,
                    prev_close=prev_close,
                    score=score,
                    reason=reason,
                    priority="",
                    build_zone="",
                    risk_tip="",
                    first_entry_ok="",
                    action_tip="",
                    top3_tag="",
                )
            )
    return candidates


def write_candidates(path: Path, candidates: list[Candidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "交易所",
        "板块",
        "代码",
        "名称",
        "最新价",
        "涨跌幅(%)",
        "成交额(亿元)",
        "振幅(%)",
        "换手率(%)",
        "量比",
        "市盈率",
        "市净率",
        "评分",
        "优先级",
        "入选理由",
        "建议建仓位",
        "是否适合今天建第一笔",
        "建议动作",
        "风险提示",
        "Top3推荐",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in candidates:
            writer.writerow(
                {
                    "交易所": item.exchange,
                    "板块": item.board,
                    "代码": item.code,
                    "名称": item.name,
                    "最新价": f"{item.price:.2f}",
                    "涨跌幅(%)": f"{item.pct_chg:.2f}",
                    "成交额(亿元)": f"{item.amount / 100000000:.2f}",
                    "振幅(%)": f"{item.amplitude:.2f}",
                    "换手率(%)": f"{item.turnover:.2f}",
                    "量比": f"{item.volume_ratio:.2f}",
                    "市盈率": "" if item.pe is None else f"{item.pe:.2f}",
                    "市净率": "" if item.pb is None else f"{item.pb:.2f}",
                    "评分": f"{item.score:.2f}",
                    "优先级": item.priority,
                    "入选理由": item.reason,
                    "建议建仓位": item.build_zone,
                    "是否适合今天建第一笔": item.first_entry_ok,
                    "建议动作": item.action_tip,
                    "风险提示": item.risk_tip,
                    "Top3推荐": item.top3_tag,
                }
            )


def write_top3(path: Path, candidates: list[Candidate]) -> None:
    top3 = candidates[:3]
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "Top3推荐",
        "代码",
        "名称",
        "优先级",
        "最新价",
        "涨跌幅(%)",
        "成交额(亿元)",
        "振幅(%)",
        "换手率(%)",
        "量比",
        "建议建仓位",
        "是否适合今天建第一笔",
        "建议动作",
        "风险提示",
        "入选理由",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in top3:
            writer.writerow(
                {
                    "Top3推荐": item.top3_tag,
                    "代码": item.code,
                    "名称": item.name,
                    "优先级": item.priority,
                    "最新价": f"{item.price:.2f}",
                    "涨跌幅(%)": f"{item.pct_chg:.2f}",
                    "成交额(亿元)": f"{item.amount / 100000000:.2f}",
                    "振幅(%)": f"{item.amplitude:.2f}",
                    "换手率(%)": f"{item.turnover:.2f}",
                    "量比": f"{item.volume_ratio:.2f}",
                    "建议建仓位": item.build_zone,
                    "是否适合今天建第一笔": item.first_entry_ok,
                    "建议动作": item.action_tip,
                    "风险提示": item.risk_tip,
                    "入选理由": item.reason,
                }
            )


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    top3_output_path = Path(args.top3_output).resolve()

    if args.refresh:
        refresh_market_snapshot()

    candidates = load_candidates(input_path)
    candidates.sort(key=lambda item: item.score, reverse=True)
    top_candidates = candidates[: args.top_n]
    for idx, item in enumerate(top_candidates, start=1):
        item.priority = priority_label(idx)
        item.build_zone = build_entry_zone(item.price, item.day_low, item.day_high, item.pct_chg)
        item.risk_tip = build_risk_tip(item.pct_chg, item.turnover, item.day_low, item.price, item.prev_close)
        item.first_entry_ok = build_entry_ok(item.pct_chg, item.turnover, item.amplitude)
        item.action_tip = build_action_tip(item.pct_chg, item.build_zone, item.first_entry_ok)
        item.top3_tag = f"Top{idx}" if idx <= 3 else ""
    write_candidates(output_path, top_candidates)
    write_top3(top3_output_path, top_candidates)

    print(
        f"loaded={len(candidates)} saved_top_n={len(top_candidates)} "
        f"output={output_path} top3_output={top3_output_path}"
    )


if __name__ == "__main__":
    main()
