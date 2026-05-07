#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import subprocess
from pathlib import Path

import pandas as pd
import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "outputs" / "cn_a_shares_official.csv"
TMP_DIR = ROOT / "outputs" / ".tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

SSE_URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_REFERER = "https://www.sse.com.cn/assortment/stock/list/share/"
SZSE_XLSX_URL = "https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1"
BSE_LIST_URL = "https://www.bse.cn/nq/listedcompany.html"


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def fetch_sse_rows(stock_type: str) -> list[dict]:
    params = {
        "STOCK_TYPE": stock_type,
        "REG_PROVINCE": "",
        "CSRC_CODE": "",
        "STOCK_CODE": "",
        "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
        "COMPANY_STATUS": "2,4,5,7,8",
        "type": "inParams",
        "isPagination": "true",
        "pageHelp.cacheSize": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.pageSize": "5000",
        "pageHelp.pageNo": "1",
        "jsonCallBack": "jsonpCallback",
    }
    response = requests.get(
        SSE_URL,
        params=params,
        headers={"Referer": SSE_REFERER, "User-Agent": "Mozilla/5.0"},
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    match = re.search(r"jsonpCallback\((.*)\)$", response.text)
    if not match:
        raise RuntimeError("unexpected SSE response")
    payload = json.loads(match.group(1))
    data = payload["pageHelp"]["data"]

    board_name = "上交所A股" if stock_type == "1" else "上交所科创板"
    rows = []
    for item in data:
        rows.append(
            {
                "市场分组": board_name,
                "交易所": "上交所",
                "板块": item.get("LIST_BOARD", ""),
                "代码": str(item.get("A_STOCK_CODE", "")).zfill(6),
                "名称": item.get("COMPANY_ABBR", ""),
                "公司全称": item.get("FULL_NAME", ""),
                "上市日期": item.get("LIST_DATE", ""),
                "所属行业": item.get("CSRC_DESC", ""),
                "地区": item.get("AREA_NAME", ""),
                "省份": item.get("REG_PROVINCE_DESC", ""),
                "总股本": item.get("TOTAL_SHARE_CAPITAL", ""),
                "流通股本": item.get("CIRCULATE_SHARE_CAPITAL", ""),
                "公司网址": item.get("WEBSITE", ""),
                "数据来源": "上海证券交易所",
            }
        )
    return rows


def fetch_szse_rows() -> list[dict]:
    xlsx_path = TMP_DIR / "szse_a_list.xlsx"
    response = requests.get(
        SZSE_XLSX_URL,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.szse.cn/market/product/stock/list/index.html"},
        timeout=60,
    )
    response.raise_for_status()
    xlsx_path.write_bytes(response.content)

    df = pd.read_excel(xlsx_path)
    rows = []
    for _, row in df.iterrows():
        code = row.get("A股代码")
        if pd.isna(code):
            continue
        rows.append(
            {
                "市场分组": "深交所A股",
                "交易所": "深交所",
                "板块": row.get("板块", ""),
                "代码": f"{int(code):06d}",
                "名称": row.get("A股简称", ""),
                "公司全称": row.get("公司全称", ""),
                "上市日期": str(row.get("A股上市日期", "")),
                "所属行业": row.get("所属行业", ""),
                "地区": row.get("地      区", ""),
                "省份": row.get("省    份", ""),
                "总股本": row.get("A股总股本", ""),
                "流通股本": row.get("A股流通股本", ""),
                "公司网址": row.get("公司网址", ""),
                "数据来源": "深圳证券交易所",
            }
        )
    return rows


def bse_eval_table_rows() -> list[list[str]]:
    script = (
        "(function(){"
        "const t=[...document.querySelectorAll('table')].find(x=>x.innerText.includes('证券代码')&&x.innerText.includes('流通股本'));"
        "if(!t) return JSON.stringify([]);"
        "const rows=t.innerText.split('\\n').slice(1).filter(Boolean).map(line=>line.split('\\t'));"
        "return JSON.stringify(rows);"
        "})()"
    )
    out = run(["opencli", "browser", "eval", script]).strip()
    return json.loads(out)


def bse_next_index_from_state() -> int | None:
    state = run(["opencli", "browser", "state"])
    match = re.search(r"\[(\d+)\]<a>></a>", state)
    if match:
        return int(match.group(1))
    return None


def fetch_bse_rows() -> list[dict]:
    run(["opencli", "browser", "open", BSE_LIST_URL])
    run(["opencli", "browser", "wait", "time", "3"])

    all_rows: list[dict] = []
    seen_codes: set[str] = set()

    while True:
        page_rows = bse_eval_table_rows()
        if not page_rows:
            raise RuntimeError("failed to read BSE table")

        for row in page_rows:
            if len(row) < 7:
                continue
            code = row[0].strip()
            if not code or code in seen_codes or not code.isdigit():
                continue
            seen_codes.add(code)
            all_rows.append(
                {
                    "市场分组": "北交所A股",
                    "交易所": "北交所",
                    "板块": "北交所",
                    "代码": code,
                    "名称": row[1].strip(),
                    "公司全称": "",
                    "上市日期": row[4].strip(),
                    "所属行业": row[5].strip(),
                    "地区": row[6].strip(),
                    "省份": row[6].strip(),
                    "总股本": row[2].strip(),
                    "流通股本": row[3].strip(),
                    "公司网址": "",
                    "数据来源": "北京证券交易所",
                }
            )

        next_index = bse_next_index_from_state()
        if next_index is None:
            break

        previous_count = len(seen_codes)
        run(["opencli", "browser", "click", str(next_index)])
        run(["opencli", "browser", "wait", "time", "2"])
        if len(seen_codes) == previous_count and next_index is None:
            break

        if len(seen_codes) >= 318:
            # 北交所当前页显示总页数为 16，股票数约 318；达到这个量级后可停止循环。
            maybe_last = bse_next_index_from_state()
            if maybe_last is None:
                break

    return all_rows


def normalize_date(value: str) -> str:
    value = str(value).strip()
    if not value or value.lower() == "nan":
        return ""
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def write_csv(rows: list[dict]) -> None:
    fieldnames = [
        "市场分组",
        "交易所",
        "板块",
        "代码",
        "名称",
        "公司全称",
        "上市日期",
        "所属行业",
        "地区",
        "省份",
        "总股本",
        "流通股本",
        "公司网址",
        "数据来源",
    ]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row = row.copy()
            row["上市日期"] = normalize_date(row["上市日期"])
            writer.writerow(row)


def main() -> None:
    rows = []
    rows.extend(fetch_sse_rows("1"))
    rows.extend(fetch_sse_rows("8"))
    rows.extend(fetch_szse_rows())
    rows.extend(fetch_bse_rows())

    deduped = {}
    for row in rows:
        deduped[row["代码"]] = row

    final_rows = sorted(deduped.values(), key=lambda x: (x["交易所"], x["代码"]))
    write_csv(final_rows)
    print(f"saved {len(final_rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
