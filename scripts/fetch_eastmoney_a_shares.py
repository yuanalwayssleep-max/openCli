#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_URL = "https://push2.eastmoney.com/api/qt/clist/get"
PAGE_SIZE = 100
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "outputs" / "eastmoney_hs_bj_a_shares.csv"

REQUEST_PARAMS = {
    "np": "1",
    "fltt": "1",
    "invt": "2",
    "fs": "m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2",
    "fields": "f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23",
    "fid": "f12",
    "po": "1",
    "dect": "1",
    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    "wbp2u": "|0|0|0|web",
}

FIELD_MAP = {
    "f12": "代码",
    "f13": "市场代码",
    "f14": "名称",
    "f1": "空字段f1",
    "f2": "最新价",
    "f4": "涨跌额",
    "f3": "涨跌幅",
    "f152": "流通市场代码",
    "f5": "成交量",
    "f6": "成交额",
    "f7": "振幅",
    "f15": "最高",
    "f18": "昨收",
    "f16": "最低",
    "f17": "今开",
    "f10": "量比",
    "f8": "换手率",
    "f9": "市盈率",
    "f23": "市净率",
}


def normalize_number(value):
    if value in (None, "-", ""):
        return ""
    return value


def infer_exchange(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return "上交所"
    if code.startswith(("000", "001", "002", "003", "200", "300", "301", "302")):
        return "深交所"
    if code.startswith(("4", "8", "9")):
        return "北交所"
    return ""


def infer_board(code: str) -> str:
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301", "302")):
        return "创业板"
    if code.startswith(("600", "601", "603", "605")):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    if code.startswith(("4", "8", "9")):
        return "北交所"
    return ""


def fetch_page(page_no: int) -> dict:
    params = {
        **REQUEST_PARAMS,
        "cb": f"jQuery37107122279616065396_1777519325764",
        "pn": str(page_no),
        "pz": str(PAGE_SIZE),
        "_": str(1777519325769 + page_no),
    }
    response = requests.get(
        API_URL,
        params=params,
        headers={
            "Referer": "https://quote.eastmoney.com/center/gridlist.html#hs_a_board",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    text = response.text.strip()
    left = text.find("(")
    right = text.rfind(")")
    if left == -1 or right == -1 or right <= left:
        raise RuntimeError(f"unexpected response on page {page_no}")
    return json.loads(text[left + 1 : right])


def fetch_all_rows() -> list[dict]:
    first_page = fetch_page(1)
    total = int(first_page["data"]["total"])
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    rows: list[dict] = []
    seen_codes: set[str] = set()

    for page_no in range(1, pages + 1):
        payload = first_page if page_no == 1 else fetch_page(page_no)
        for item in payload["data"].get("diff", []):
            code = str(item.get("f12", "")).zfill(6)
            if code in seen_codes:
                continue
            seen_codes.add(code)

            row = {
                "交易所": infer_exchange(code),
                "板块": infer_board(code),
            }
            for source_field, output_field in FIELD_MAP.items():
                row[output_field] = normalize_number(item.get(source_field))
            rows.append(row)

    return rows


def write_csv(rows: list[dict]) -> None:
    fieldnames = [
        "交易所",
        "板块",
        *FIELD_MAP.values(),
    ]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = fetch_all_rows()
    rows.sort(key=lambda x: (x["交易所"], x["代码"]))
    write_csv(rows)
    print(f"saved {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
