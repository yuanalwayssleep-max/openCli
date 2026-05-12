#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import requests
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "outputs" / "eastmoney_hs_bj_a_shares.csv"
DEFAULT_OUTPUT = ROOT / "data" / "a_share_candidate_pool.csv"
DEFAULT_ALL_SCORES_OUTPUT = ROOT / "data" / "a_share_full_score_detail.csv"
REFRESH_SCRIPT = ROOT / "scripts" / "fetch_eastmoney_a_shares.py"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
UT = "fa5fd1943c7b386f172d6893dbfba10b"


@dataclass
class Candidate:
    exchange: str
    board: str
    code: str
    name: str
    industry: str
    region: str
    concepts: str
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
    score_detail: str
    reason: str
    priority: str
    build_zone: str
    risk_tip: str
    first_entry_ok: str
    action_tip: str
    rank_tag: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按练手量化规则筛选A股候选池")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="输入A股快照CSV路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出全部入选股票评分CSV路径")
    parser.add_argument("--top3-output", default="", help="兼容旧参数；已停用，不再单独输出Top3文件")
    parser.add_argument("--all-scores-output", default=str(DEFAULT_ALL_SCORES_OUTPUT), help="输出全市场评分与剔除明细CSV路径")
    parser.add_argument("--top-n", type=int, default=10, help="兼容旧参数；候选池始终输出全部入选股票，最终推荐只取前2只")
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
    return value


def scaled_price(row: dict[str, str], field: str) -> float | None:
    value = to_float(row[field])
    if value is None:
        return None
    return value


def scaled_ratio(row: dict[str, str], field: str) -> float | None:
    value = to_float(row[field])
    if value is None:
        return None
    return value


def refresh_market_snapshot() -> None:
    subprocess.run(["python3", str(REFRESH_SCRIPT)], check=True)


def dynamic_amount_floor(total_market_amount: float) -> float:
    return 1_000_000_000


def amount_percentile(amount: float, sorted_amounts_desc: list[float]) -> float:
    if not sorted_amounts_desc:
        return 100
    better_or_equal = 0
    for item in sorted_amounts_desc:
        if item >= amount:
            better_or_equal += 1
        else:
            break
    return better_or_equal / len(sorted_amounts_desc) * 100


def secid_for(exchange: str, code: str) -> str:
    market_id = "1" if exchange == "上交所" else "0"
    return f"{market_id}.{code}"


def fetch_recent_daily(exchange: str, code: str, limit: int = 30) -> list[dict[str, float | str]]:
    response = requests.get(
        KLINE_URL,
        params={
            "secid": secid_for(exchange, code),
            "klt": "101",
            "fqt": "1",
            "lmt": str(limit),
            "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": UT,
        },
        headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    rows = []
    for line in data.get("klines", []):
        date, open_, close, high, low, volume, amount, amplitude, pct_chg, chg, turnover = line.split(",")
        rows.append(
            {
                "date": date,
                "open": float(open_),
                "close": float(close),
                "high": float(high),
                "low": float(low),
                "amount": float(amount),
                "pct_chg": float(pct_chg),
            }
        )
    return rows


def recent_position_metrics(exchange: str, code: str, price: float) -> dict[str, float | bool]:
    try:
        rows = fetch_recent_daily(exchange, code)
    except Exception:
        # 行情快照仍可用时，不因历史接口偶发失败完全中断筛选。
        return {"history_available": False}
    if len(rows) < 20:
        return {"history_available": False}

    highs20 = [float(row["high"]) for row in rows[-20:]]
    lows20 = [float(row["low"]) for row in rows[-20:]]
    closes20 = [float(row["close"]) for row in rows[-20:]]
    amounts20 = [float(row["amount"]) for row in rows[-20:]]
    hi20 = max(highs20)
    lo20 = min(lows20)
    if hi20 <= lo20:
        return {"history_available": False}

    pos20 = (price - lo20) / (hi20 - lo20) * 100
    ma20 = sum(closes20) / len(closes20)
    dist_ma20 = (price / ma20 - 1) * 100 if ma20 else 0

    if len(rows) >= 6:
        close_5_days_ago = float(rows[-6]["close"])
        cum5 = (price / close_5_days_ago - 1) * 100 if close_5_days_ago else 0
    else:
        cum5 = 0

    amount5 = sum(float(row["amount"]) for row in rows[-5:]) / 5
    amount20 = sum(amounts20) / len(amounts20)
    amount_ratio = amount5 / amount20 if amount20 else 1
    latest_pct = float(rows[-1]["pct_chg"])
    cum3 = 0
    if len(rows) >= 4:
        close_3_days_ago = float(rows[-4]["close"])
        cum3 = (price / close_3_days_ago - 1) * 100 if close_3_days_ago else 0

    recent_high_position_days = 0
    for row in rows[-3:]:
        row_close = float(row["close"])
        row_pos20 = (row_close - lo20) / (hi20 - lo20) * 100
        if row_pos20 > 90:
            recent_high_position_days += 1

    return {
        "history_available": True,
        "pos20": pos20,
        "dist_ma20": dist_ma20,
        "cum5": cum5,
        "cum3": cum3,
        "amount_ratio": amount_ratio,
        "latest_pct": latest_pct,
        "recent_high_position_days": recent_high_position_days,
    }


def passes_position_filters(metrics: dict[str, float | bool], amplitude: float, high_pullback_pct: float) -> bool:
    if not metrics.get("history_available"):
        return True
    pos20 = float(metrics["pos20"])
    dist_ma20 = float(metrics["dist_ma20"])
    cum5 = float(metrics["cum5"])
    cum3 = float(metrics["cum3"])
    amount_ratio = float(metrics["amount_ratio"])
    latest_pct = float(metrics["latest_pct"])
    recent_high_position_days = int(metrics["recent_high_position_days"])

    if pos20 > 90 and dist_ma20 > 8:
        return False
    if cum5 > 8:
        return False
    if pos20 > 90 and cum5 > 5:
        return False
    if amount_ratio > 1.2 and latest_pct < 1 and pos20 > 85:
        return False
    if recent_high_position_days >= 2 and cum3 < 3:
        return False
    if pos20 > 90 and amplitude < 2.6 and high_pullback_pct > -1:
        return False
    return True


def build_reason(price: float, amount: float, amplitude: float, turnover: float, pct_chg: float, volume_ratio: float) -> str:
    reasons: list[str] = []
    if amount >= 3_000_000_000:
        reasons.append("成交额高")
    elif amount >= 2_000_000_000:
        reasons.append("流动性达标")
    elif amount >= 1_000_000_000:
        reasons.append("成交额观察")
    if 1.8 <= amplitude <= 4.5:
        reasons.append("振幅适中")
    if 2 <= turnover <= 7.5:
        reasons.append("换手率适中")
    if 0.3 <= pct_chg <= 3.2:
        reasons.append("涨幅未过热")
    if 1 <= volume_ratio <= 1.8:
        reasons.append("量比健康")
    if 10 <= price <= 60:
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
    if pct_chg > 3.2:
        return "否"
    if turnover > 7.5 or amplitude > 4.5:
        return "否"
    if 0.3 <= pct_chg <= 3.2 and 1.8 <= amplitude <= 4.5 and 2 <= turnover <= 7.5:
        return "是"
    return "观察后决定"


def build_action_tip(pct_chg: float, build_zone: str, first_entry_ok: str) -> str:
    if first_entry_ok == "否":
        return f"今天不追高，只有回踩关键区后重新企稳才看；参考区间：{build_zone}"
    if first_entry_ok == "是":
        return f"可按区间观察第一笔10%，只做试仓；参考区间：{build_zone}"
    return f"先观察承接与回收，再决定是否试10%；参考区间：{build_zone}"


GENERIC_CONCEPTS = {
    "融资融券",
    "深股通",
    "沪股通",
    "预盈预增",
    "机构重仓",
    "转债标的",
    "标准普尔",
    "富时罗素",
    "MSCI中国",
    "央国企改革",
}


def concept_set(raw: str) -> set[str]:
    return {item.strip() for item in (raw or "").split(",") if item.strip() and item.strip() not in GENERIC_CONCEPTS}


def relation_reason(left: Candidate, right: Candidate) -> str:
    if left.industry and right.industry and left.industry == right.industry:
        return f"同行业:{left.industry}"
    overlap = concept_set(left.concepts) & concept_set(right.concepts)
    if len(overlap) >= 2:
        return "概念重叠:" + "/".join(sorted(overlap)[:4])
    return ""


def select_diversified(candidates: list[Candidate], limit: int = 2) -> list[Candidate]:
    selected: list[Candidate] = []
    skipped: list[Candidate] = []
    for item in candidates:
        if len(selected) >= limit:
            break
        related = [relation_reason(item, chosen) for chosen in selected]
        related = [reason for reason in related if reason]
        if related:
            item.reason = f"{item.reason}；组合相关性降级({';'.join(related)})"
            skipped.append(item)
            continue
        selected.append(item)

    if len(selected) < limit:
        for item in skipped:
            if len(selected) >= limit:
                break
            selected.append(item)
    return selected


def score_candidate(
    *,
    pct_chg: float,
    amount: float,
    amplitude: float,
    volume_ratio: float,
    turnover: float,
    close_position_pct: float,
    high_pullback_pct: float,
    day_high_space_pct: float,
    amount_rank_pct: float,
    day_low: float,
    price: float,
    metrics: dict[str, float | bool],
) -> tuple[float, str]:
    details: list[str] = []

    amount_yi = amount / 100000000
    if amount_yi >= 30:
        liquidity_amount = 12
    elif amount_yi >= 20:
        liquidity_amount = 9
    elif amount_yi >= 10:
        liquidity_amount = 5
    else:
        liquidity_amount = 0

    if 3 <= turnover <= 6:
        turnover_score = 5
    else:
        turnover_score = 3

    if 1.1 <= volume_ratio <= 1.6:
        volume_score = 4
    elif 1.0 <= volume_ratio <= 1.8:
        volume_score = 2
    else:
        volume_score = 1

    if 0.8 <= pct_chg <= 2.4:
        pct_score = 8
    else:
        pct_score = 5

    if 2.6 <= amplitude <= 4.0:
        amplitude_score = 5
    elif 1.2 <= amplitude < 2.6 or 4.0 < amplitude <= 5.0:
        amplitude_score = 3
    else:
        amplitude_score = 1

    if close_position_pct >= 75:
        close_position_score = 8
    elif close_position_pct >= 65:
        close_position_score = 6
    else:
        close_position_score = 3

    # 快照无法识别14:30后的5分钟主动抢筹，先给基础尾盘近似分；
    # Top候选再补抓5分钟K自动确认尾盘量价。
    tail_proxy_score = min(20, round(close_position_score * 1.2 + max(0, 4 + high_pullback_pct), 2))

    history_score = 22
    if metrics.get("history_available"):
        pos20 = float(metrics["pos20"])
        dist_ma20 = float(metrics["dist_ma20"])
        cum5 = float(metrics["cum5"])
        amount_ratio = float(metrics["amount_ratio"])
        latest_pct = float(metrics["latest_pct"])

        if pos20 > 85:
            history_score -= 6
        elif pos20 > 75:
            history_score -= 3
        if cum5 > 5:
            history_score -= 6
        if dist_ma20 > 6:
            history_score -= 5
        if amount_ratio > 1.2 and latest_pct < 1 and pos20 > 80:
            history_score -= 5
    history_score = max(0, history_score)

    defense_space_pct = (price / day_low - 1) * 100 if day_low else 0
    if day_high_space_pct >= 1.5 and defense_space_pct <= day_high_space_pct * 2:
        risk_reward_score = 13
    elif day_high_space_pct >= 1.0:
        risk_reward_score = 8
    else:
        risk_reward_score = 3

    total = (
        liquidity_amount
        + turnover_score
        + volume_score
        + pct_score
        + amplitude_score
        + close_position_score
        + tail_proxy_score
        + history_score
        + risk_reward_score
    )
    total = min(100, round(total, 2))

    details.extend(
        [
            f"成交额分层{liquidity_amount}/12",
            f"换手{turnover_score}/5",
            f"量比{volume_score}/4",
            f"涨跌幅{pct_score}/8",
            f"振幅质量近似{amplitude_score}/5",
            f"日内位置{close_position_score}/8",
            f"尾盘近似{tail_proxy_score}/20",
            f"历史风险{history_score}/22",
            f"空间盈亏比{risk_reward_score}/13",
        ]
    )
    return total, "；".join(details)


def append_score_record(
    records: list[dict[str, str]] | None,
    row: dict[str, str],
    *,
    status: str,
    reject_reason: str = "",
    score: float | None = None,
    score_detail: str = "",
    close_position_pct: float | None = None,
    high_pullback_pct: float | None = None,
    day_high_space_pct: float | None = None,
    open_to_price_pct: float | None = None,
    amount_rank_pct: float | None = None,
    metrics: dict[str, float | bool] | None = None,
) -> None:
    if records is None:
        return
    price = to_float(row.get("最新价", ""))
    pct_chg = to_float(row.get("涨跌幅", ""))
    amount = to_float(row.get("成交额", ""))
    amplitude = to_float(row.get("振幅", ""))
    turnover = to_float(row.get("换手率", ""))
    volume_ratio = to_float(row.get("量比", ""))
    pe = to_float(row.get("市盈率", ""))
    pb = to_float(row.get("市净率", ""))
    metrics = metrics or {}
    records.append(
        {
            "交易所": row.get("交易所", ""),
            "板块": row.get("板块", ""),
            "代码": row.get("代码", ""),
            "名称": row.get("名称", ""),
            "行业": row.get("行业", ""),
            "地域板块": row.get("地域板块", ""),
            "概念题材": row.get("概念题材", ""),
            "最新价": "" if price is None else f"{price:.2f}",
            "涨跌幅(%)": "" if pct_chg is None else f"{pct_chg:.2f}",
            "成交额(亿元)": "" if amount is None else f"{amount / 100000000:.2f}",
            "振幅(%)": "" if amplitude is None else f"{amplitude:.2f}",
            "换手率(%)": "" if turnover is None else f"{turnover:.2f}",
            "量比": "" if volume_ratio is None else f"{volume_ratio:.2f}",
            "市盈率": "" if pe is None else f"{pe:.2f}",
            "市净率": "" if pb is None else f"{pb:.2f}",
            "筛选状态": status,
            "剔除原因": reject_reason,
            "评分": "" if score is None else f"{score:.2f}",
            "评分明细": score_detail,
            "日内位置(%)": "" if close_position_pct is None else f"{close_position_pct:.2f}",
            "距日内高点(%)": "" if high_pullback_pct is None else f"{high_pullback_pct:.2f}",
            "到日内高点空间(%)": "" if day_high_space_pct is None else f"{day_high_space_pct:.2f}",
            "开盘至当前(%)": "" if open_to_price_pct is None else f"{open_to_price_pct:.2f}",
            "成交额分位(%)": "" if amount_rank_pct is None else f"{amount_rank_pct:.2f}",
            "近20日位置(%)": "" if not metrics.get("history_available") else f"{float(metrics['pos20']):.2f}",
            "近5日涨幅(%)": "" if not metrics.get("history_available") else f"{float(metrics['cum5']):.2f}",
            "偏离MA20(%)": "" if not metrics.get("history_available") else f"{float(metrics['dist_ma20']):.2f}",
            "近5日/20日成交额": "" if not metrics.get("history_available") else f"{float(metrics['amount_ratio']):.2f}",
        }
    )


def write_all_scores(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "交易所",
        "板块",
        "代码",
        "名称",
        "行业",
        "地域板块",
        "概念题材",
        "最新价",
        "涨跌幅(%)",
        "成交额(亿元)",
        "振幅(%)",
        "换手率(%)",
        "量比",
        "市盈率",
        "市净率",
        "筛选状态",
        "剔除原因",
        "评分",
        "评分明细",
        "日内位置(%)",
        "距日内高点(%)",
        "到日内高点空间(%)",
        "开盘至当前(%)",
        "成交额分位(%)",
        "近20日位置(%)",
        "近5日涨幅(%)",
        "偏离MA20(%)",
        "近5日/20日成交额",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def load_candidates(path: Path, score_records: list[dict[str, str]] | None = None) -> list[Candidate]:
    candidates: list[Candidate] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        amounts = [to_float(row.get("成交额", "")) or 0 for row in rows]
        total_market_amount = sum(amounts)
        amount_floor = dynamic_amount_floor(total_market_amount)
        sorted_amounts_desc = sorted(amounts, reverse=True)
        for row in rows:
            name = row["名称"]
            board = row["板块"]
            if name.startswith(("ST", "*ST", "SST", "N", "C")) or board == "北交所":
                append_score_record(score_records, row, status="硬性剔除", reject_reason="ST/新股/北交所不参与尾盘重仓隔夜")
                continue
            industry = row.get("行业", "")
            region = row.get("地域板块", "")
            concepts = row.get("概念题材", "")

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
            day_open = scaled_price(row, "今开")
            prev_close = scaled_price(row, "昨收")

            if None in (price, pct_chg, amount, amplitude, volume_ratio, turnover, day_high, day_low, day_open, prev_close):
                append_score_record(score_records, row, status="硬性剔除", reject_reason="关键行情字段缺失")
                continue

            if not (10 <= price <= 60):
                append_score_record(score_records, row, status="硬性剔除", reject_reason="价格不在10-60元")
                continue
            amount_rank_pct = amount_percentile(amount, sorted_amounts_desc)
            if amount < amount_floor:
                append_score_record(
                    score_records,
                    row,
                    status="硬性剔除",
                    reject_reason=f"成交额低于硬下限{amount_floor / 100000000:.0f}亿元",
                    amount_rank_pct=amount_rank_pct,
                )
                continue
            if not (1.2 <= amplitude <= 5.0):
                append_score_record(score_records, row, status="硬性剔除", reject_reason="振幅不在1.2%-5.0%")
                continue
            if not (2 <= turnover <= 7.5):
                append_score_record(score_records, row, status="硬性剔除", reject_reason="换手率不在2%-7.5%")
                continue
            if not (1.0 <= volume_ratio <= 2.5):
                append_score_record(score_records, row, status="硬性剔除", reject_reason="日总量比不在1.0-2.5")
                continue
            if not (0.3 <= pct_chg <= 3.2):
                append_score_record(score_records, row, status="硬性剔除", reject_reason="涨跌幅不在+0.3%到+3.2%")
                continue
            intraday_range = day_high - day_low
            if intraday_range <= 0:
                append_score_record(score_records, row, status="硬性剔除", reject_reason="日内高低价异常")
                continue
            close_position_pct = (price - day_low) / intraday_range * 100
            high_pullback_pct = (price / day_high - 1) * 100 if day_high else 0
            day_high_space_pct = (day_high / price - 1) * 100 if price else 0
            open_to_price_pct = (price / day_open - 1) * 100 if day_open else 0

            # 复盘紫光股份、金风科技后新增：高开低走且收在日内低位的票，
            # 即使成交额/换手达标，也不适合做次日冲高卖的尾盘优先票。
            if close_position_pct < 55:
                append_score_record(
                    score_records,
                    row,
                    status="硬性剔除",
                    reject_reason="收盘/当前价处于日内振幅55%以下",
                    close_position_pct=close_position_pct,
                    high_pullback_pct=high_pullback_pct,
                    day_high_space_pct=day_high_space_pct,
                    open_to_price_pct=open_to_price_pct,
                    amount_rank_pct=amount_rank_pct,
                )
                continue
            if high_pullback_pct <= -1.5:
                append_score_record(
                    score_records,
                    row,
                    status="硬性剔除",
                    reject_reason="距离日内高点回落超过1.5%",
                    close_position_pct=close_position_pct,
                    high_pullback_pct=high_pullback_pct,
                    day_high_space_pct=day_high_space_pct,
                    open_to_price_pct=open_to_price_pct,
                    amount_rank_pct=amount_rank_pct,
                )
                continue
            if day_high_space_pct < 1.0:
                append_score_record(
                    score_records,
                    row,
                    status="硬性剔除",
                    reject_reason="到日内高点空间低于1.0%",
                    close_position_pct=close_position_pct,
                    high_pullback_pct=high_pullback_pct,
                    day_high_space_pct=day_high_space_pct,
                    open_to_price_pct=open_to_price_pct,
                    amount_rank_pct=amount_rank_pct,
                )
                continue
            if open_to_price_pct <= -1.2:
                append_score_record(
                    score_records,
                    row,
                    status="硬性剔除",
                    reject_reason="高开低走/开盘至当前跌幅超过1.2%",
                    close_position_pct=close_position_pct,
                    high_pullback_pct=high_pullback_pct,
                    day_high_space_pct=day_high_space_pct,
                    open_to_price_pct=open_to_price_pct,
                    amount_rank_pct=amount_rank_pct,
                )
                continue
            metrics = recent_position_metrics(row["交易所"], row["代码"], price)
            score, score_detail = score_candidate(
                pct_chg=pct_chg,
                amount=amount,
                amplitude=amplitude,
                volume_ratio=volume_ratio,
                turnover=turnover,
                close_position_pct=close_position_pct,
                high_pullback_pct=high_pullback_pct,
                day_high_space_pct=day_high_space_pct,
                amount_rank_pct=amount_rank_pct,
                day_low=day_low,
                price=price,
                metrics=metrics,
            )
            if not passes_position_filters(metrics, amplitude, high_pullback_pct):
                append_score_record(
                    score_records,
                    row,
                    status="硬性剔除",
                    reject_reason="历史位置风险剔除",
                    score=score,
                    score_detail=score_detail,
                    close_position_pct=close_position_pct,
                    high_pullback_pct=high_pullback_pct,
                    day_high_space_pct=day_high_space_pct,
                    open_to_price_pct=open_to_price_pct,
                    amount_rank_pct=amount_rank_pct,
                    metrics=metrics,
                )
                continue
            append_score_record(
                score_records,
                row,
                status="进入候选评分",
                score=score,
                score_detail=score_detail,
                close_position_pct=close_position_pct,
                high_pullback_pct=high_pullback_pct,
                day_high_space_pct=day_high_space_pct,
                open_to_price_pct=open_to_price_pct,
                amount_rank_pct=amount_rank_pct,
                metrics=metrics,
            )
            reason = build_reason(price, amount, amplitude, turnover, pct_chg, volume_ratio)
            candidates.append(
                Candidate(
                    exchange=row["交易所"],
                    board=board,
                    code=row["代码"],
                    name=name,
                    industry=industry,
                    region=region,
                    concepts=concepts,
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
                    score_detail=score_detail,
                    reason=reason,
                    priority="",
                    build_zone="",
                    risk_tip="",
                    first_entry_ok="",
                    action_tip="",
                    rank_tag="",
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
        "行业",
        "地域板块",
        "概念题材",
        "最新价",
        "涨跌幅(%)",
        "成交额(亿元)",
        "振幅(%)",
        "换手率(%)",
        "量比",
        "市盈率",
        "市净率",
        "评分",
        "评分明细",
        "优先级",
        "入选理由",
        "建议建仓位",
        "是否适合今天建第一笔",
        "建议动作",
        "风险提示",
        "排名",
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
                    "行业": item.industry,
                    "地域板块": item.region,
                    "概念题材": item.concepts,
                    "最新价": f"{item.price:.2f}",
                    "涨跌幅(%)": f"{item.pct_chg:.2f}",
                    "成交额(亿元)": f"{item.amount / 100000000:.2f}",
                    "振幅(%)": f"{item.amplitude:.2f}",
                    "换手率(%)": f"{item.turnover:.2f}",
                    "量比": f"{item.volume_ratio:.2f}",
                    "市盈率": "" if item.pe is None else f"{item.pe:.2f}",
                    "市净率": "" if item.pb is None else f"{item.pb:.2f}",
                    "评分": f"{item.score:.2f}",
                    "评分明细": item.score_detail,
                    "优先级": item.priority,
                    "入选理由": item.reason,
                    "建议建仓位": item.build_zone,
                    "是否适合今天建第一笔": item.first_entry_ok,
                    "建议动作": item.action_tip,
                    "风险提示": item.risk_tip,
                    "排名": item.rank_tag,
                }
            )


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    all_scores_output_path = Path(args.all_scores_output).resolve()

    if args.refresh:
        refresh_market_snapshot()

    score_records: list[dict[str, str]] = []
    candidates = load_candidates(input_path, score_records)
    candidates.sort(key=lambda item: item.score, reverse=True)
    diversified = select_diversified(candidates, limit=2)
    remaining = [item for item in candidates if item not in diversified]
    ordered_candidates = diversified + remaining
    for idx, item in enumerate(ordered_candidates, start=1):
        item.priority = priority_label(idx)
        item.build_zone = build_entry_zone(item.price, item.day_low, item.day_high, item.pct_chg)
        item.risk_tip = build_risk_tip(item.pct_chg, item.turnover, item.day_low, item.price, item.prev_close)
        item.first_entry_ok = build_entry_ok(item.pct_chg, item.turnover, item.amplitude)
        item.action_tip = build_action_tip(item.pct_chg, item.build_zone, item.first_entry_ok)
        item.rank_tag = f"Top{idx}"
    write_candidates(output_path, ordered_candidates)
    write_all_scores(all_scores_output_path, score_records)

    print(
        f"loaded={len(candidates)} saved_candidates={len(ordered_candidates)} "
        f"output={output_path} all_scores_output={all_scores_output_path}"
    )


if __name__ == "__main__":
    main()
