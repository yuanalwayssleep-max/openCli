#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from pathlib import Path

import requests
import urllib3

try:
    import akshare as ak
except Exception:  # noqa: BLE001
    ak = None


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_URL = "https://push2.eastmoney.com/api/qt/clist/get"
PAGE_SIZE = 100
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "outputs" / "eastmoney_hs_bj_a_shares.csv"
SINA_BATCH_SIZE = 800
EASTMONEY_RESOLVE_IPS = ("47.112.165.11",)

REQUEST_PARAMS = {
    "np": "1",
    "fltt": "2",
    "invt": "2",
    "fs": "m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2",
    "fields": "f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23,f100,f102,f103",
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
    "f100": "行业",
    "f102": "地域板块",
    "f103": "概念题材",
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


def fetch_akshare_fallback_rows() -> list[dict]:
    if ak is None:
        raise RuntimeError("akshare is not installed; cannot use fallback snapshot source")

    # akshare uses the same public quote data but has its own pagination wrapper.
    # Clear proxy variables for this fallback because local HTTP proxies often break
    # Eastmoney push endpoints with RemoteDisconnected/empty replies.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    df = ak.stock_zh_a_spot_em()
    rows: list[dict] = []
    for _, item in df.iterrows():
        code = str(item.get("代码", "")).zfill(6)
        row = {
            "交易所": infer_exchange(code),
            "板块": infer_board(code),
            "代码": code,
            "市场代码": normalize_number(item.get("市场代码", "")),
            "名称": normalize_number(item.get("名称", "")),
            "空字段f1": "",
            "最新价": normalize_number(item.get("最新价", "")),
            "涨跌额": normalize_number(item.get("涨跌额", "")),
            "涨跌幅": normalize_number(item.get("涨跌幅", "")),
            "流通市场代码": "",
            "成交量": normalize_number(item.get("成交量", "")),
            "成交额": normalize_number(item.get("成交额", "")),
            "振幅": normalize_number(item.get("振幅", "")),
            "最高": normalize_number(item.get("最高", "")),
            "昨收": normalize_number(item.get("昨收", "")),
            "最低": normalize_number(item.get("最低", "")),
            "今开": normalize_number(item.get("今开", "")),
            "量比": normalize_number(item.get("量比", "")),
            "换手率": normalize_number(item.get("换手率", "")),
            "市盈率": normalize_number(item.get("市盈率-动态", "")),
            "市净率": normalize_number(item.get("市净率", "")),
            "行业": "",
            "地域板块": "",
            "概念题材": "",
        }
        rows.append(row)
    return rows


def fetch_page_with_curl_resolve(page_no: int, resolve_ip: str) -> dict:
    from urllib.parse import urlencode

    params = {
        **REQUEST_PARAMS,
        "cb": f"jQuery37107122279616065396_1777519325764",
        "pn": str(page_no),
        "pz": str(PAGE_SIZE),
        "_": str(1777519325769 + page_no),
    }
    url = f"{API_URL}?{urlencode(params)}"
    cmd = [
        "curl",
        "--silent",
        "--show-error",
        "--fail",
        "--location",
        "--max-time",
        "30",
        "--resolve",
        f"push2.eastmoney.com:443:{resolve_ip}",
        "-A",
        "Mozilla/5.0",
        "-e",
        "https://quote.eastmoney.com/center/gridlist.html#hs_a_board",
        url,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    text = result.stdout.strip()
    left = text.find("(")
    right = text.rfind(")")
    if left != -1 and right > left:
        text = text[left + 1 : right]
    return json.loads(text)


def fetch_all_rows_with_curl_resolve(resolve_ip: str) -> list[dict]:
    first_page = fetch_page_with_curl_resolve(1, resolve_ip)
    total = int(first_page["data"]["total"])
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    rows: list[dict] = []
    seen_codes: set[str] = set()
    for page_no in range(1, pages + 1):
        payload = first_page if page_no == 1 else fetch_page_with_curl_resolve(page_no, resolve_ip)
        for item in payload["data"].get("diff", []):
            code = str(item.get("f12", "")).zfill(6)
            if code in seen_codes:
                continue
            seen_codes.add(code)
            row = {"交易所": infer_exchange(code), "板块": infer_board(code)}
            for source_field, output_field in FIELD_MAP.items():
                row[output_field] = normalize_number(item.get(source_field))
            rows.append(row)
    return rows


def latest_metadata_snapshot() -> Path:
    candidates = sorted((ROOT / "data").glob("a股快照_*.csv"), reverse=True)
    for path in candidates:
        try:
            with path.open(encoding="utf-8-sig", newline="") as f:
                if sum(1 for _ in f) > 1000:
                    return path
        except OSError:
            continue
    raise RuntimeError("no usable metadata snapshot found under data/a股快照_*.csv")


def sina_code_for(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return f"sh{code}"
    if code.startswith(("000", "001", "002", "003", "200", "300", "301", "302")):
        return f"sz{code}"
    if code.startswith(("4", "8", "9")):
        return f"bj{code}"
    return ""


def fetch_sina_fallback_rows() -> list[dict]:
    metadata_path = latest_metadata_snapshot()
    with metadata_path.open(encoding="utf-8-sig", newline="") as f:
        metadata_rows = list(csv.DictReader(f))

    codes: list[str] = []
    metadata_by_raw: dict[str, dict[str, str]] = {}
    for row in metadata_rows:
        code = str(row.get("代码", "")).zfill(6)
        raw_code = sina_code_for(code)
        if not raw_code:
            continue
        codes.append(raw_code)
        metadata_by_raw[raw_code] = row

    if not codes:
        raise RuntimeError(f"no usable stock codes found in {metadata_path}")

    rows: list[dict] = []
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    for start in range(0, len(codes), SINA_BATCH_SIZE):
        batch = codes[start : start + SINA_BATCH_SIZE]
        response = requests.get(
            "https://hq.sinajs.cn/list=" + ",".join(batch),
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        text = response.content.decode("gbk", "ignore")
        for part in text.split(";"):
            part = part.strip()
            if not part or "=\"" not in part:
                continue
            left, value = part.split("=\"", 1)
            raw_code = left.replace("var hq_str_", "")
            values = value.rstrip("\"").split(",")
            if len(values) < 32 or not values[0]:
                continue
            meta = metadata_by_raw.get(raw_code, {})
            code = raw_code[2:]
            try:
                open_price = float(values[1])
                prev_close = float(values[2])
                price = float(values[3])
                high = float(values[4])
                low = float(values[5])
                volume = float(values[8])
                amount = float(values[9])
            except ValueError:
                continue

            change = price - prev_close
            pct_change = change / prev_close * 100 if prev_close else 0.0
            amplitude = (high - low) / prev_close * 100 if prev_close else 0.0
            rows.append(
                {
                    "交易所": meta.get("交易所") or infer_exchange(code),
                    "板块": meta.get("板块") or infer_board(code),
                    "代码": code,
                    "市场代码": meta.get("市场代码", ""),
                    "名称": values[0],
                    "空字段f1": "",
                    "最新价": price,
                    "涨跌额": change,
                    "涨跌幅": pct_change,
                    "流通市场代码": meta.get("流通市场代码", ""),
                    "成交量": volume,
                    "成交额": amount,
                    "振幅": amplitude,
                    "最高": high,
                    "昨收": prev_close,
                    "最低": low,
                    "今开": open_price,
                    "量比": meta.get("量比", ""),
                    "换手率": meta.get("换手率", ""),
                    "市盈率": meta.get("市盈率", ""),
                    "市净率": meta.get("市净率", ""),
                    "行业": meta.get("行业", ""),
                    "地域板块": meta.get("地域板块", ""),
                    "概念题材": meta.get("概念题材", ""),
                }
            )
        time.sleep(0.2)
    return rows


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
    source = "eastmoney"
    try:
        rows = fetch_all_rows()
    except Exception as exc:  # noqa: BLE001
        print(f"eastmoney fetch failed: {exc}")
        rows = []
        for resolve_ip in EASTMONEY_RESOLVE_IPS:
            try:
                print(f"trying eastmoney curl --resolve fallback via {resolve_ip}...")
                source = f"eastmoney_curl_resolve_{resolve_ip}"
                rows = fetch_all_rows_with_curl_resolve(resolve_ip)
                break
            except Exception as curl_exc:  # noqa: BLE001
                print(f"eastmoney curl --resolve fallback failed via {resolve_ip}: {curl_exc}")
        if not rows:
            try:
                print("trying akshare fallback...")
                source = "akshare_fallback"
                rows = fetch_akshare_fallback_rows()
            except Exception as akshare_exc:  # noqa: BLE001
                print(f"akshare fallback failed: {akshare_exc}")
                print("trying sina fallback...")
                source = "sina_fallback"
                rows = fetch_sina_fallback_rows()

    if len(rows) < 1000:
        raise RuntimeError(f"snapshot row count is suspiciously low: {len(rows)}")

    rows.sort(key=lambda x: (x["交易所"], x["代码"]))
    write_csv(rows)
    print(f"saved {len(rows)} rows to {OUTPUT_PATH} via {source}")


if __name__ == "__main__":
    main()
