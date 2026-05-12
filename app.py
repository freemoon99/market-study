#!/usr/bin/env python3
import csv
import datetime as dt
import email.utils
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


USE_POSTGRES = bool(os.environ.get("DATABASE_URL"))


def app_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_root():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


ROOT = app_root()
RESOURCES = resource_root()
PUBLIC = RESOURCES / "public"
DATA = ROOT / "data"
DB_PATH = DATA / "market_study.db"


HELP = {
    "market_cap": "시가총액: 현재 주가에 상장주식 수를 곱한 기업 규모입니다.",
    "per": "PER: 주가를 주당순이익(EPS)으로 나눈 값입니다. 낮을수록 이익 대비 가격 부담이 낮다고 해석하기도 합니다.",
    "pbr": "PBR: 주가를 주당순자산으로 나눈 값입니다. 1배 미만은 장부가치보다 낮게 거래된다는 의미입니다.",
    "roe": "ROE: 자기자본이익률입니다. 자본을 얼마나 효율적으로 이익으로 바꾸는지 봅니다.",
    "eps": "EPS: 주당순이익입니다. 기업 이익을 주식 수로 나눈 값입니다.",
}


THEME_RULES = [
    ("AI", ("ai", "인공지능", "챗gpt", "데이터센터", "gpu", "반도체 장비")),
    ("로봇", ("로봇", "자동화", "휴머노이드")),
    ("전력설비", ("전력", "변압기", "전선", "송전", "배전", "인프라", "전력기기")),
    ("원전", ("원전", "원자력", "smr", "체코 원전")),
    ("반도체", ("반도체", "hbm", "메모리", "파운드리", "디램", "dram")),
    ("2차전지", ("2차전지", "배터리", "리튬", "양극재", "음극재", "전고체")),
    ("바이오", ("바이오", "제약", "신약", "임상", "의료기기", "헬스케어")),
    ("방산", ("방산", "방위", "무기", "수출", "항공우주", "드론")),
    ("조선", ("조선", "선박", "lng", "해양플랜트")),
    ("자동차", ("자동차", "전장", "자율주행", "현대차", "기아")),
    ("게임", ("게임", "신작", "퍼블리싱")),
    ("엔터", ("엔터", "음원", "콘텐츠", "드라마", "웹툰")),
    ("정치/정책", ("정책", "대선", "총선", "공약", "정부", "규제완화")),
    ("우크라이나 재건", ("우크라이나", "재건", "건설기계")),
    ("화장품", ("화장품", "k뷰티", "뷰티")),
    ("식품", ("식품", "음식료", "라면", "k푸드")),
    ("철강/금속", ("철강", "금속", "구리", "알루미늄", "희토류", "니켈")),
]


class PostgresConnection:
    def __init__(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Postgres 사용을 위해 psycopg 패키지가 필요합니다. `pip install -r requirements.txt`를 실행하세요.") from exc
        self.conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)

    def __enter__(self):
        self.conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.conn.__exit__(exc_type, exc, tb)

    def execute(self, query, params=None):
        return self.conn.execute(query.replace("?", "%s"), params or ())

    def executescript(self, script):
        for statement in [s.strip() for s in script.split(";") if s.strip()]:
            self.execute(statement)


def db():
    if USE_POSTGRES:
        return PostgresConnection()
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    return conn


def init_db():
    with db() as conn:
        int_type = "bigint" if USE_POSTGRES else "integer"
        real_type = "double precision" if USE_POSTGRES else "real"
        conn.executescript(
            f"""
            create table if not exists days (
                date text primary key,
                refreshed_at text not null,
                source_note text
            );

            create table if not exists stocks (
                date text not null,
                code text not null,
                name text not null,
                market text,
                tags_json text not null,
                price {int_type},
                change_amount {int_type},
                change_rate {real_type},
                volume {int_type},
                volume_prev {int_type},
                volume_vs_prev_pct {real_type},
                volume_avg20 {real_type},
                volume_vs_avg20_pct {real_type},
                market_cap {int_type},
                per {real_type},
                pbr {real_type},
                eps {real_type},
                roe {real_type},
                sector text,
                sector_per {real_type},
                sector_pbr {real_type},
                reasons_json text not null,
                note text not null,
                updated_at text not null,
                primary key(date, code)
            );

            create table if not exists ohlcv (
                code text not null,
                trade_date text not null,
                open {int_type},
                high {int_type},
                low {int_type},
                close {int_type},
                volume {int_type},
                primary key(code, trade_date)
            );
            """
        )


def today_kr():
    now = dt.datetime.utcnow() + dt.timedelta(hours=9)
    return now.strftime("%Y-%m-%d")


def compact_date(value):
    return value.replace("-", "")


def human_date(value):
    if "-" in value:
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def parse_int(value):
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9\-]", "", str(value))
    return int(cleaned) if cleaned not in ("", "-") else None


def parse_float(value):
    if value is None:
        return None
    cleaned = str(value).replace(",", "").replace("%", "").strip()
    if cleaned in ("", "-", "N/A"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def http_get(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def http_post(url, data, headers=None, timeout=15):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def krx_json(bld, payload):
    data = {"bld": bld, "locale": "ko_KR", "csvxls_isNo": "false"}
    data.update(payload)
    raw = http_post(
        "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        },
    )
    return json.loads(raw.decode("utf-8"))


def fetch_krx_daily(date_yyyymmdd):
    payload = {
        "mktId": "ALL",
        "trdDd": date_yyyymmdd,
        "share": "1",
        "money": "1",
    }
    result = krx_json("dbms/MDC/STAT/standard/MDCSTAT01501", payload)
    rows = result.get("OutBlock_1") or result.get("output") or []
    if not rows:
        raise RuntimeError("KRX 일별 시세 데이터를 찾지 못했습니다. 휴장일이거나 KRX 응답 형식이 바뀌었을 수 있습니다.")
    return rows


def strip_tags(value):
    value = re.sub(r"<script.*?</script>", "", value, flags=re.S)
    value = re.sub(r"<style.*?</style>", "", value, flags=re.S)
    value = re.sub(r"<.*?>", "", value, flags=re.S)
    return html.unescape(value).replace("\xa0", " ").strip()


def fetch_naver_market_snapshot():
    rows = []
    seen = set()
    for market_id, market_name in (("0", "KOSPI"), ("1", "KOSDAQ")):
        empty_pages = 0
        for page in range(1, 46):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={market_id}&page={page}"
            raw = http_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12).decode("euc-kr", errors="ignore")
            found = 0
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, flags=re.S):
                link = re.search(r"/item/main\.naver\?code=(\d{6})[^>]*>(.*?)</a>", tr, flags=re.S)
                if not link:
                    continue
                code = link.group(1)
                if code in seen:
                    continue
                seen.add(code)
                found += 1
                name = strip_tags(link.group(2))
                cells = [strip_tags(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
                nums = [c for c in cells if c and c != name]
                if len(nums) < 10:
                    continue
                price = parse_int(nums[1])
                change = parse_int(nums[2])
                rate = parse_float(nums[3])
                market_cap_uk = parse_int(nums[5])
                volume = parse_int(nums[8])
                per = parse_float(nums[9]) if len(nums) > 9 else None
                roe = parse_float(nums[10]) if len(nums) > 10 else None
                rows.append(
                    {
                        "code": code,
                        "name": name,
                        "market": market_name,
                        "price": price,
                        "change_amount": change,
                        "change_rate": rate,
                        "volume": volume,
                        "market_cap": market_cap_uk * 100_000_000 if market_cap_uk is not None else None,
                        "per": per,
                        "pbr": None,
                        "eps": round(price / per, 2) if price and per and per > 0 else None,
                        "roe": roe,
                    }
                )
            if found == 0:
                empty_pages += 1
            else:
                empty_pages = 0
            if empty_pages >= 2:
                break
            time.sleep(0.05)
    if not rows:
        raise RuntimeError("네이버 금융 시세 데이터를 찾지 못했습니다.")
    return rows


def parse_naver_rank_rows(raw, market_name, tag):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, flags=re.S):
        link = re.search(r'/item/main\.naver\?code=(\d{6})[^>]*>(.*?)</a>', tr, flags=re.S)
        if not link:
            continue
        cells = [strip_tags(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
        if len(cells) < 8:
            continue
        code = link.group(1)
        name = strip_tags(link.group(2))
        if tag == "상한가":
            price_idx, change_idx, rate_idx, volume_idx = 4, 5, 6, 7
        else:
            price_idx, change_idx, rate_idx, volume_idx = 2, 3, 4, 5
        rows.append(
            {
                "code": code,
                "name": name,
                "market": market_name,
                "price": parse_int(cells[price_idx]) if len(cells) > price_idx else None,
                "change_amount": parse_int(cells[change_idx]) if len(cells) > change_idx else None,
                "change_rate": parse_float(cells[rate_idx]) if len(cells) > rate_idx else None,
                "volume": parse_int(cells[volume_idx]) if len(cells) > volume_idx else None,
                "market_cap": None,
                "per": None,
                "pbr": None,
                "eps": None,
                "roe": None,
                "source_tags": [tag],
            }
        )
    return rows


def fetch_naver_ranked_candidates():
    by_code = {}

    upper_raw = http_get(
        "https://finance.naver.com/sise/sise_upper.naver",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=12,
    ).decode("euc-kr", errors="ignore")
    for item in parse_naver_rank_rows(upper_raw, None, "상한가"):
        by_code[item["code"]] = item

    for market_id, market_name in (("0", "KOSPI"), ("1", "KOSDAQ")):
        raw = http_get(
            f"https://finance.naver.com/sise/sise_quant.naver?sosok={market_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        ).decode("euc-kr", errors="ignore")
        for item in parse_naver_rank_rows(raw, market_name, "거래량 1000만주"):
            if item.get("volume") is None or item["volume"] < 10_000_000:
                continue
            existing = by_code.get(item["code"])
            if existing:
                existing["source_tags"] = sorted(set(existing.get("source_tags", []) + item["source_tags"]))
                for key, value in item.items():
                    if key != "source_tags" and existing.get(key) is None and value is not None:
                        existing[key] = value
                if not existing.get("market"):
                    existing["market"] = market_name
            else:
                by_code[item["code"]] = item

    if not by_code:
        raise RuntimeError("네이버 상한가/거래상위 데이터를 찾지 못했습니다.")
    return list(by_code.values())


def fetch_krx_fundamentals(date_yyyymmdd):
    try:
        payload = {"mktId": "ALL", "trdDd": date_yyyymmdd}
        result = krx_json("dbms/MDC/STAT/standard/MDCSTAT03501", payload)
        rows = result.get("OutBlock_1") or result.get("output") or []
        return {r.get("ISU_SRT_CD") or r.get("isuCd"): r for r in rows}
    except Exception:
        return {}


def fetch_naver_chart(code, count=70):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
    raw = http_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12).decode("euc-kr", errors="ignore")
    rows = []
    for item in re.findall(r"<item data=\"([^\"]+)\"", raw):
        parts = item.split("|")
        if len(parts) >= 6:
            rows.append(
                {
                    "trade_date": human_date(parts[0]),
                    "open": parse_int(parts[1]),
                    "high": parse_int(parts[2]),
                    "low": parse_int(parts[3]),
                    "close": parse_int(parts[4]),
                    "volume": parse_int(parts[5]),
                }
            )
    return rows


def rss_item_date(item):
    m = re.search(r"<pubDate>(.*?)</pubDate>", item, flags=re.S)
    if not m:
        return None
    try:
        published = email.utils.parsedate_to_datetime(html.unescape(m.group(1).strip()))
        if published.tzinfo is None:
            published = published.replace(tzinfo=dt.timezone.utc)
        kst = published.astimezone(dt.timezone(dt.timedelta(hours=9)))
        return kst.strftime("%Y-%m-%d")
    except Exception:
        return None


def fetch_naver_news(name, code, date_iso):
    query = urllib.parse.quote(f"{name} {code} 주가")
    url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        raw = http_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).decode("utf-8", errors="ignore")
        items = re.findall(r"<item>(.*?)</item>", raw, flags=re.S)
        reasons = []
        for item in items:
            if rss_item_date(item) != date_iso:
                continue
            title = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", item, flags=re.S)
            link = re.search(r"<link>(.*?)</link>", item, flags=re.S)
            text = html.unescape((title.group(1) or title.group(2)).strip()) if title else ""
            text = re.sub(r"\s+-\s+[^-]+$", "", text)
            if text:
                reasons.append({"text": text, "url": html.unescape(link.group(1).strip()) if link else "", "auto": True})
            if len(reasons) >= 3:
                break
        return reasons
    except Exception:
        return []


def fetch_research_items(name):
    queries = [f"{name} 회사 사업 실적 매출 수주 테마"]
    found = []
    seen = set()
    for q in queries:
        query = urllib.parse.quote(q)
        url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        try:
            raw = http_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8).decode("utf-8", errors="ignore")
        except Exception:
            continue
        for item in re.findall(r"<item>(.*?)</item>", raw, flags=re.S)[:5]:
            title = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", item, flags=re.S)
            link = re.search(r"<link>(.*?)</link>", item, flags=re.S)
            text = html.unescape((title.group(1) or title.group(2)).strip()) if title else ""
            text = re.sub(r"\s+-\s+[^-]+$", "", text)
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                found.append({"text": text, "url": html.unescape(link.group(1).strip()) if link else ""})
    return found[:5]


def fetch_naver_basic(code):
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        raw = http_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).decode("utf-8", errors="ignore")
    except Exception:
        return {}
    sector = None
    m = re.search(r"업종명\s*:\s*<a[^>]*>(.*?)</a>", raw, flags=re.S)
    if m:
        sector = strip_tags(m.group(1))
    roe = None
    m = re.search(r"ROE.*?</th>\s*<td[^>]*>(.*?)</td>", raw, flags=re.S)
    if m:
        roe = parse_float(re.sub(r"<.*?>", "", m.group(1)))
    company_text = None
    company_paragraphs = []
    summary_match = re.search(r'<div id="summary_info" class="summary_info">(.*?)<div class="txt_notice">', raw, flags=re.S)
    if summary_match:
        company_paragraphs = [
            re.sub(r"\s+", " ", strip_tags(p)).strip()
            for p in re.findall(r"<p>(.*?)</p>", summary_match.group(1), flags=re.S)
        ]
        company_paragraphs = [p for p in company_paragraphs if p]
        company_text = " ".join(company_paragraphs)[:520]
    financials = extract_financial_rows(raw)
    return {"sector": sector, "roe": roe, "company_text": company_text, "company_paragraphs": company_paragraphs, "financials": financials}


def extract_financial_rows(raw):
    rows = {}
    for label in ("매출액", "영업이익", "당기순이익", "부채비율", "유보율", "ROE", "PER", "PBR"):
        m = re.search(rf"<th[^>]*>\s*(?:<strong>)?{label}(?:</strong>)?\s*</th>(.*?)</tr>", raw, flags=re.S)
        if not m:
            continue
        values = []
        for td in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), flags=re.S):
            text = strip_tags(td)
            text = re.sub(r"\s+", " ", text).strip()
            if text and text != "&nbsp;":
                values.append(text)
        rows[label] = values
    return rows


def clean_theme_text(text):
    text = str(text or "")
    noise_words = (
        "조선비즈",
        "머니투데이",
        "매일경제",
        "한국경제",
        "이데일리",
        "서울경제",
        "파이낸셜뉴스",
        "연합뉴스",
        "뉴스핌",
        "아시아경제",
        "헤럴드경제",
    )
    for word in noise_words:
        text = text.replace(word, " ")
    return text


def detect_themes(*parts):
    text = clean_theme_text(" ".join([str(p or "") for p in parts])).lower()
    themes = []
    for label, keywords in THEME_RULES:
        if any(keyword.lower() in text for keyword in keywords):
            themes.append(label)
    return themes


def infer_stock_themes(stock):
    reason_text = " ".join([r.get("text", "") for r in stock.get("reasons", [])])
    themes = detect_themes(stock.get("name"), stock.get("sector"), reason_text, stock.get("note"))
    if not themes and stock.get("sector"):
        themes = [stock["sector"]]
    return themes[:4]


def extract_opinion(note):
    if not note:
        return "- 왜 움직였다고 보는가:\n- 다음에 확인할 것:\n"
    marker = "### 내 의견"
    if marker not in note:
        return "- 왜 움직였다고 보는가:\n- 다음에 확인할 것:\n"
    return note.split(marker, 1)[1].strip() or "- 왜 움직였다고 보는가:\n- 다음에 확인할 것:"


def should_refresh_auto_note(note):
    if not note:
        return True
    placeholders = (
        "무엇을 하는 회사인가:",
        "주요 제품/서비스:",
        "연결된 테마/재료:",
        "관련 종목으로 분류됩니다.",
        "뉴스/차트 확인 필요",
        "핵심 확인 포인트: 사업보고서",
        "핵심 확인 포인트:",
    )
    return any(p in note for p in placeholders)


def merge_reasons(existing_json, fresh_reasons):
    if not existing_json:
        return fresh_reasons
    try:
        existing = json.loads(existing_json)
    except Exception:
        return fresh_reasons
    manual = [r for r in existing if not r.get("auto")]
    if manual:
        return fresh_reasons + manual
    return fresh_reasons


def summarize_research_points(reasons, research_items):
    titles = [r.get("text", "") for r in (reasons or []) + (research_items or []) if r.get("text")]
    joined = " ".join(titles)
    points = []
    if any(k in joined for k in ("수주", "계약", "공급", "납품")):
        points.append("수주/계약성 뉴스가 있는지 확인됩니다.")
    if any(k in joined for k in ("실적", "매출", "영업이익", "흑자", "적자")):
        points.append("실적 또는 이익 변화 관련 뉴스가 포착됩니다.")
    if any(k in joined for k in ("정책", "정부", "규제", "지원", "대선", "공약")):
        points.append("정책/정부 이슈와 연결될 가능성이 있습니다.")
    if any(k in joined.lower() for k in ("ai", "반도체", "로봇", "전력", "원전", "배터리", "바이오")):
        points.append("시장 주도 테마 키워드와 연결된 뉴스가 확인됩니다.")
    if not points:
        points.append("뉴스 제목만으로는 재료가 뚜렷하지 않습니다. 공시와 사업보고서 확인이 필요합니다.")
    return points[:3]


def financial_brief(financials):
    if not financials:
        return ["네이버 금융 실적 테이블을 확인하지 못했습니다. 분기/연간 실적은 별도 확인이 필요합니다."]
    lines = []
    sales = financials.get("매출액", [])
    op = financials.get("영업이익", [])
    net = financials.get("당기순이익", [])
    if sales:
        lines.append(f"매출액 최근값: {sales[-1]}억원 수준으로 표시됩니다. 최근 연속값은 {' → '.join(sales[-4:])}입니다.")
    if op:
        lines.append(f"영업이익 최근값: {op[-1]}억원, 흐름은 {' → '.join(op[-4:])}입니다.")
    if net:
        lines.append(f"당기순이익 최근값: {net[-1]}억원, 흐름은 {' → '.join(net[-4:])}입니다.")
    debt = financials.get("부채비율", [])
    if debt:
        lines.append(f"부채비율 최근값: {debt[-1]}%로 재무 부담 변화를 같이 봅니다.")
    return lines[:4] or ["실적 수치가 충분하지 않습니다. 최근 분기보고서와 공시 확인이 필요합니다."]


def business_points(company_paragraphs, sector):
    text = " ".join(company_paragraphs or [])
    points = []
    if company_paragraphs:
        points.extend(company_paragraphs[:3])
    elif sector:
        points.append(f"{sector} 업종에 속한 기업으로, 업종 내 주요 제품/서비스와 매출 비중 확인이 필요합니다.")
    else:
        points.append("기업개요를 자동으로 확인하지 못했습니다. 네이버 금융/사업보고서에서 주요 제품과 매출 구조를 확인하세요.")
    if any(k in text for k in ("제조", "생산", "부품", "모듈", "장비")):
        points.append("제조 기반 사업은 수주, 가동률, 원가율, 고객사 변화가 실적 포인트입니다.")
    if any(k in text for k in ("판매", "유통", "서비스", "플랫폼")):
        points.append("판매/서비스 사업은 매출 성장률, 반복 매출, 판관비 효율을 함께 봅니다.")
    if any(k in text for k in ("해외", "수출", "법인")):
        points.append("해외 매출과 환율, 현지 법인 실적이 변동 요인이 될 수 있습니다.")
    return points[:5]


def build_note(name, item=None, basic=None, reasons=None, research_items=None, previous_note=None):
    item = item or {}
    basic = basic or {}
    reasons = reasons or []
    research_items = research_items or []
    themes = detect_themes(
        name,
        basic.get("sector"),
        basic.get("company_text"),
        " ".join([r.get("text", "") for r in reasons]),
        " ".join([r.get("text", "") for r in research_items]),
    )
    theme_text = ", ".join(themes) if themes else (basic.get("sector") or "뉴스/차트 확인 필요")
    company_intro = basic.get("company_text") or f"{name}은(는) {basic.get('sector') or item.get('market') or '해당 시장'} 관련 종목입니다."
    sector = basic.get("sector") or item.get("sector") or "-"
    business_lines = business_points(basic.get("company_paragraphs"), sector)
    performance_lines = financial_brief(basic.get("financials"))
    reason_lines = [r.get("text", "") for r in reasons if r.get("text")][:3]
    research_lines = [r.get("text", "") for r in research_items if r.get("text")][:4]
    research_points = summarize_research_points(reasons, research_items)
    if not reason_lines:
        reason_lines = ["뉴스 원인 후보가 부족합니다. 공시, 뉴스, 거래원, 섹터 동향을 직접 확인하세요."]
    opinion = extract_opinion(previous_note)
    return (
        f"## {name} 학습 노트\n\n"
        "### 회사 소개\n"
        f"- {company_intro}\n"
        f"- 시장/업종: {item.get('market') or '-'} / {sector}\n\n"
        "### 사업군과 실적 포인트\n"
        + "".join([f"- 사업 포인트: {line}\n" for line in business_lines])
        + "".join([f"- 실적 포인트: {line}\n" for line in performance_lines])
        + f"- 밸류에이션: PER {format_num(item.get('per'))}, PBR {format_num(item.get('pbr'))}, ROE {format_num(item.get('roe'))}, EPS {format_num(item.get('eps'))}\n\n"
        + "### 자동 리서치 메모\n"
        + "".join([f"- {line}\n" for line in research_points])
        + "".join([f"- 참고 뉴스: {line}\n" for line in research_lines])
        + "\n"
        + "### 오늘의 테마\n"
        + f"- 연결 테마: {theme_text}\n"
        + f"- 수급 힌트: 거래량 {format_num(item.get('volume'))}주, 20일 평균 대비 {format_num(item.get('volume_vs_avg20_pct'))}%\n"
        + "".join([f"- 원인 후보: {line}\n" for line in reason_lines])
        + "\n"
        "### 내 의견\n"
        f"{opinion}\n"
    )


def default_note(name):
    return build_note(name)


def is_market_noise(name):
    prefixes = (
        "KODEX",
        "TIGER",
        "ACE",
        "SOL",
        "KBSTAR",
        "RISE",
        "PLUS",
        "HANARO",
        "KOSEF",
        "ARIRANG",
        "TIMEFOLIO",
        "TREX",
        "WON",
        "BNK",
        "FOCUS",
    )
    upper_name = name.upper()
    return upper_name.startswith(prefixes) or " ETN" in upper_name or "스팩" in name or "기업인수목적" in name


def normalize_row(row, fundamentals):
    code = row.get("ISU_SRT_CD") or row.get("isuSrtCd") or row.get("isuCd")
    name = row.get("ISU_ABBRV") or row.get("isuAbbrv") or row.get("ISU_NM") or ""
    price = parse_int(row.get("TDD_CLSPRC") or row.get("tddClsprc"))
    change = parse_int(row.get("CMPPREVDD_PRC") or row.get("cmpPrevddPrc"))
    rate = parse_float(row.get("FLUC_RT") or row.get("flucRt"))
    volume = parse_int(row.get("ACC_TRDVOL") or row.get("accTrdvol"))
    market = row.get("MKT_NM") or row.get("mktNm")
    market_cap = parse_int(row.get("MKTCAP") or row.get("mktcap"))
    f = fundamentals.get(code, {})
    return {
        "code": code,
        "name": name,
        "market": market,
        "price": price,
        "change_amount": change,
        "change_rate": rate,
        "volume": volume,
        "market_cap": market_cap,
        "per": parse_float(f.get("PER") or f.get("per")),
        "pbr": parse_float(f.get("PBR") or f.get("pbr")),
        "eps": parse_float(f.get("EPS") or f.get("eps")),
    }


def enrich_and_store(date_iso):
    source_note = "Naver upper/volume rank, Naver chart, Google News RSS"
    try:
        normalized = fetch_naver_ranked_candidates()
    except Exception:
        source_note = "Naver market snapshot fallback, Naver chart, Google News RSS"
        normalized = fetch_naver_market_snapshot()
    now = dt.datetime.now().isoformat(timespec="seconds")
    selected = []

    for item in normalized:
        if not item["code"] or item["price"] is None:
            continue
        if is_market_noise(item["name"]):
            continue
        tags = item.get("source_tags") or []
        if not tags:
            if item["change_rate"] is not None and 29.5 <= item["change_rate"] <= 30.5:
                tags.append("상한가")
            if item["volume"] is not None and item["volume"] >= 10_000_000:
                tags.append("거래량 1000만주")
        if tags:
            item["tags"] = sorted(set(tags), key=lambda tag: 0 if tag == "상한가" else 1)
            selected.append(item)

    selected.sort(key=lambda x: (0 if "상한가" in x["tags"] else 1, -(x.get("volume") or 0)))

    with db() as conn:
        existing_rows = conn.execute("select code, reasons_json, note from stocks where date=?", (date_iso,)).fetchall()
        existing_by_code = {r["code"]: r for r in existing_rows}
        conn.execute(
            """
            insert into days(date, refreshed_at, source_note) values(?,?,?)
            on conflict(date) do update set
                refreshed_at=excluded.refreshed_at,
                source_note=excluded.source_note
            """,
            (date_iso, now, source_note),
        )
        conn.execute("delete from stocks where date=?", (date_iso,))
        for item in selected:
            chart = fetch_naver_chart(item["code"])
            for c in chart:
                conn.execute(
                    """
                    insert into ohlcv(code, trade_date, open, high, low, close, volume)
                    values(?,?,?,?,?,?,?)
                    on conflict(code, trade_date) do update set
                        open=excluded.open,
                        high=excluded.high,
                        low=excluded.low,
                        close=excluded.close,
                        volume=excluded.volume
                    """,
                    (item["code"], c["trade_date"], c["open"], c["high"], c["low"], c["close"], c["volume"]),
                )
            volumes = [c["volume"] for c in chart if c["volume"] is not None]
            prev_volume = volumes[-2] if len(volumes) >= 2 else None
            avg20 = sum(volumes[-21:-1]) / min(20, len(volumes[-21:-1])) if len(volumes[-21:-1]) else None
            item["volume_prev"] = prev_volume
            item["volume_avg20"] = avg20
            item["volume_vs_prev_pct"] = pct_change(item["volume"], prev_volume)
            item["volume_vs_avg20_pct"] = pct_change(item["volume"], avg20)

            basic = fetch_naver_basic(item["code"])
            item["sector"] = basic.get("sector")
            item["roe"] = basic.get("roe")
            reasons = fetch_naver_news(item["name"], item["code"], date_iso)
            if not reasons:
                reasons = [{"text": "당일 뉴스 없음: 직접 원인을 입력하거나 공시/거래량/테마를 확인하세요.", "url": "", "auto": True}]
            research_items = fetch_research_items(item["name"])

            existing = existing_by_code.get(item["code"])
            merged_reasons = merge_reasons(existing["reasons_json"] if existing else None, reasons)
            reasons_json = json.dumps(merged_reasons, ensure_ascii=False)
            note = build_note(item["name"], item, basic, reasons, research_items, existing["note"] if existing else None) if (not existing or should_refresh_auto_note(existing["note"])) else existing["note"]
            conn.execute(
                """
                insert into stocks(
                    date, code, name, market, tags_json, price, change_amount, change_rate, volume,
                    volume_prev, volume_vs_prev_pct, volume_avg20, volume_vs_avg20_pct,
                    market_cap, per, pbr, eps, roe, sector, sector_per, sector_pbr,
                    reasons_json, note, updated_at
                ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                on conflict(date, code) do update set
                    name=excluded.name,
                    market=excluded.market,
                    tags_json=excluded.tags_json,
                    price=excluded.price,
                    change_amount=excluded.change_amount,
                    change_rate=excluded.change_rate,
                    volume=excluded.volume,
                    volume_prev=excluded.volume_prev,
                    volume_vs_prev_pct=excluded.volume_vs_prev_pct,
                    volume_avg20=excluded.volume_avg20,
                    volume_vs_avg20_pct=excluded.volume_vs_avg20_pct,
                    market_cap=excluded.market_cap,
                    per=excluded.per,
                    pbr=excluded.pbr,
                    eps=excluded.eps,
                    roe=excluded.roe,
                    sector=excluded.sector,
                    sector_per=excluded.sector_per,
                    sector_pbr=excluded.sector_pbr,
                    reasons_json=excluded.reasons_json,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (
                    date_iso,
                    item["code"],
                    item["name"],
                    item["market"],
                    json.dumps(item["tags"], ensure_ascii=False),
                    item["price"],
                    item["change_amount"],
                    item["change_rate"],
                    item["volume"],
                    item["volume_prev"],
                    item["volume_vs_prev_pct"],
                    item["volume_avg20"],
                    item["volume_vs_avg20_pct"],
                    item["market_cap"],
                    item.get("per"),
                    item.get("pbr"),
                    item.get("eps"),
                    item.get("roe"),
                    item.get("sector"),
                    None,
                    None,
                    reasons_json,
                    note,
                    now,
                ),
            )
            time.sleep(0.08)
    return get_day(date_iso)


def pct_change(now, base):
    if now is None or not base:
        return None
    return (float(now) - float(base)) / float(base) * 100


def get_streak_tags(conn, date_iso, code, tags):
    dates = [
        r["date"]
        for r in conn.execute(
            "select date from days where date<=? order by date desc",
            (date_iso,),
        ).fetchall()
    ]
    if not dates:
        return []
    streaks = []
    for tag in tags:
        count = 0
        for d in dates:
            row = conn.execute(
                "select tags_json from stocks where date=? and code=?",
                (d, code),
            ).fetchone()
            if not row:
                break
            day_tags = json.loads(row["tags_json"])
            if tag not in day_tags:
                break
            count += 1
        if count >= 2:
            streaks.append(f"{count}일째 {tag}")
    return streaks


def build_day_insights(stocks):
    theme_scores = {}
    for stock in stocks:
        score = 1
        if "상한가" in stock["tags"]:
            score += 2
        if "거래량 1000만주" in stock["tags"]:
            score += 1
        if stock.get("volume_vs_avg20_pct") and stock["volume_vs_avg20_pct"] > 100:
            score += 1
        for theme in stock.get("themes", []):
            theme_scores.setdefault(theme, {"name": theme, "count": 0, "score": 0, "stocks": []})
            theme_scores[theme]["count"] += 1
            theme_scores[theme]["score"] += score
            theme_scores[theme]["stocks"].append(stock["name"])
    themes = sorted(theme_scores.values(), key=lambda x: (x["score"], x["count"]), reverse=True)[:10]
    leader_names = [s["name"] for s in stocks if "상한가" in s["tags"]][:5]
    repeat_names = [f"{s['name']}({', '.join(s.get('streak_tags', []))})" for s in stocks if s.get("streak_tags")][:5]
    mood = "상한가와 거래량 후보를 중심으로 주도 테마를 확인하세요."
    if themes:
        mood = f"{themes[0]['name']} 테마가 가장 두드러집니다. 관련 종목 수와 거래량 증가를 함께 확인하세요."
    return {
        "themes": themes,
        "mood": mood,
        "leaders": leader_names,
        "repeats": repeat_names,
    }


def get_day(date_iso):
    with db() as conn:
        day = conn.execute("select * from days where date=?", (date_iso,)).fetchone()
        stocks = conn.execute(
            "select * from stocks where date=? order by case when tags_json like '%상한가%' then 1 else 0 end desc, volume desc",
            (date_iso,),
        ).fetchall()
        result = []
        for s in stocks:
            item = dict(s)
            item["tags"] = json.loads(item.pop("tags_json"))
            item["reasons"] = json.loads(item.pop("reasons_json"))
            item["themes"] = infer_stock_themes(item)
            item["streak_tags"] = get_streak_tags(conn, date_iso, item["code"], item["tags"])
            item["display_tags"] = item["tags"] + item["streak_tags"]
            chart = conn.execute(
                "select trade_date, open, high, low, close, volume from ohlcv where code=? order by trade_date",
                (item["code"],),
            ).fetchall()
            item["chart"] = [dict(c) for c in chart]
            result.append(item)
        limit_count = sum(1 for s in result if "상한가" in s["tags"])
        volume_count = sum(1 for s in result if "거래량 1000만주" in s["tags"])
        return {
            "date": date_iso,
            "refreshed_at": day["refreshed_at"] if day else None,
            "help": HELP,
            "counts": {"limit_up": limit_count, "high_volume": volume_count, "total": len(result)},
            "insights": build_day_insights(result),
            "stocks": result,
        }


def update_stock(date_iso, code, payload):
    with db() as conn:
        conn.execute(
            "update stocks set reasons_json=?, note=?, updated_at=? where date=? and code=?",
            (
                json.dumps(payload.get("reasons", []), ensure_ascii=False),
                payload.get("note", ""),
                dt.datetime.now().isoformat(timespec="seconds"),
                date_iso,
                code,
            ),
        )
    return {"ok": True}


def format_num(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}"


def markdown_link(text, url):
    label = (text or "").replace("[", "\\[").replace("]", "\\]")
    if not url:
        return label
    clean_url = str(url).replace(")", "%29").replace(" ", "%20")
    return f"[{label}]({clean_url})"


def stock_focus_score(stock):
    score = 0
    score += stock.get("change_rate") or 0
    score += min(60, max(0, stock.get("volume_vs_avg20_pct") or 0) / 5)
    if "상한가" in stock.get("tags", []):
        score += 20
    if stock.get("streak_tags"):
        score += 10
    return score


def export_markdown(date_iso):
    day = get_day(date_iso)
    filename = f"market-summary-{date_iso}.md"
    themes = day.get("insights", {}).get("themes", [])
    leaders = day.get("insights", {}).get("leaders", [])
    repeats = day.get("insights", {}).get("repeats", [])
    focus = sorted(day["stocks"], key=stock_focus_score, reverse=True)[:7]
    theme_line = ", ".join([f"#{t['name']}({t['count']})" for t in themes]) or "-"
    lines = [
        f"# {date_iso} 한국 증시 당일 정리",
        "",
        "## 시장 요약",
        "",
        f"- 상한가: {day['counts']['limit_up']}개",
        f"- 거래량 1000만주 이상: {day['counts']['high_volume']}개",
        f"- 총 종목: {day['counts']['total']}개",
        f"- 분위기: {day.get('insights', {}).get('mood', '-')}",
        f"- 당일 테마: {theme_line}",
        f"- 상한가 핵심: {', '.join(leaders) or '-'}",
        f"- 연속 출현: {', '.join(repeats) or '-'}",
        "",
        "## 우선 복기 후보",
        "",
        *[
            f"- {s['name']} ({s['code']}): {', '.join(s.get('display_tags', s['tags']))}, 등락률 {format_num(s['change_rate'])}%, 거래량 평균 대비 {format_num(s['volume_vs_avg20_pct'])}%"
            for s in focus
        ],
        "",
    ]
    for s in day["stocks"]:
        lines += [
            f"## {' / '.join(s.get('display_tags', s['tags']))} | {s['name']} ({s['code']})",
            "",
            f"- 테마: {', '.join(s.get('themes', [])) or '-'}",
            f"- 현재가: {format_num(s['price'])}원 ({format_num(s['change_rate'])}%)",
            f"- 거래량: {format_num(s['volume'])}주, 전일 대비 {format_num(s['volume_vs_prev_pct'])}%, 20일 평균 대비 {format_num(s['volume_vs_avg20_pct'])}%",
            f"- 시가총액: {format_num(s['market_cap'])}",
            f"- PER/PBR/ROE/EPS: {format_num(s['per'])} / {format_num(s['pbr'])} / {format_num(s['roe'])} / {format_num(s['eps'])}",
            "",
            "### 원인 후보",
        ]
        for r in s["reasons"]:
            lines.append(f"- {markdown_link(r.get('text', ''), r.get('url'))}")
        lines += ["", "### 노트", s.get("note") or "", ""]
    return {"ok": True, "filename": filename, "markdown": "\n".join(lines)}


def sample_day(date_iso):
    now = dt.datetime.now().isoformat(timespec="seconds")
    sample_chart = []
    base = 10000
    for i in range(40):
        d = (dt.date.fromisoformat(date_iso) - dt.timedelta(days=39 - i)).isoformat()
        close = base + i * 80 + (i % 5) * 90
        sample_chart.append({"trade_date": d, "open": close - 120, "high": close + 300, "low": close - 260, "close": close, "volume": 800000 + i * 180000})
    with db() as conn:
        conn.execute(
            """
            insert into days(date, refreshed_at, source_note) values(?,?,?)
            on conflict(date) do update set
                refreshed_at=excluded.refreshed_at,
                source_note=excluded.source_note
            """,
            (date_iso, now, "sample"),
        )
        code = "000000"
        for c in sample_chart:
            conn.execute(
                """
                insert into ohlcv(code, trade_date, open, high, low, close, volume) values(?,?,?,?,?,?,?)
                on conflict(code, trade_date) do update set
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume
                """,
                (code, c["trade_date"], c["open"], c["high"], c["low"], c["close"], c["volume"]),
            )
        conn.execute(
            """
            insert into stocks(date, code, name, market, tags_json, price, change_amount, change_rate, volume,
                volume_prev, volume_vs_prev_pct, volume_avg20, volume_vs_avg20_pct, market_cap, per, pbr, eps, roe,
                sector, sector_per, sector_pbr, reasons_json, note, updated_at)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(date, code) do update set
                name=excluded.name,
                market=excluded.market,
                tags_json=excluded.tags_json,
                price=excluded.price,
                change_amount=excluded.change_amount,
                change_rate=excluded.change_rate,
                volume=excluded.volume,
                volume_prev=excluded.volume_prev,
                volume_vs_prev_pct=excluded.volume_vs_prev_pct,
                volume_avg20=excluded.volume_avg20,
                volume_vs_avg20_pct=excluded.volume_vs_avg20_pct,
                market_cap=excluded.market_cap,
                per=excluded.per,
                pbr=excluded.pbr,
                eps=excluded.eps,
                roe=excluded.roe,
                sector=excluded.sector,
                sector_per=excluded.sector_per,
                sector_pbr=excluded.sector_pbr,
                reasons_json=excluded.reasons_json,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (
                date_iso,
                code,
                "샘플종목",
                "KOSDAQ",
                json.dumps(["상한가", "거래량 1000만주"], ensure_ascii=False),
                13200,
                3040,
                29.92,
                15000000,
                4300000,
                248.84,
                3500000,
                328.57,
                210000000000,
                18.4,
                2.1,
                720,
                11.2,
                "소프트웨어",
                None,
                None,
                json.dumps(
                    [
                        {"text": "샘플 뉴스: 신규 계약과 테마 기대감으로 매수세 유입", "url": "", "auto": True},
                        {"text": "샘플 뉴스: 거래량이 최근 평균 대비 크게 증가", "url": "", "auto": True},
                    ],
                    ensure_ascii=False,
                ),
                default_note("샘플종목"),
                now,
            ),
        )
    return get_day(date_iso)


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        parsed = urllib.parse.urlparse(path)
        clean = parsed.path
        if clean == "/":
            clean = "/index.html"
        if clean.startswith("/api/"):
            return str(PUBLIC / "index.html")
        return str(PUBLIC / clean.lstrip("/"))

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return super().do_GET()
        try:
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/api/dates":
                with db() as conn:
                    dates = [r["date"] for r in conn.execute("select date from days order by date desc").fetchall()]
                return self.send_json({"today": today_kr(), "dates": dates})
            if parsed.path == "/api/day":
                date_iso = query.get("date", [today_kr()])[0]
                return self.send_json(get_day(date_iso))
            if parsed.path == "/api/export":
                date_iso = query.get("date", [today_kr()])[0]
                return self.send_json(export_markdown(date_iso))
            self.send_json({"error": "not found"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/refresh":
                date_iso = payload.get("date") or today_kr()
                try:
                    return self.send_json(enrich_and_store(date_iso))
                except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
                    if payload.get("sampleOnFail", True):
                        data = sample_day(date_iso)
                        data["warning"] = f"실데이터 수집 실패로 샘플 데이터를 표시했습니다: {e}"
                        return self.send_json(data)
                    raise
            if parsed.path.startswith("/api/stocks/"):
                parts = parsed.path.split("/")
                if len(parts) >= 5:
                    return self.send_json(update_stock(parts[3], parts[4], payload))
            self.send_json({"error": "not found"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)


def main():
    init_db()
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    shown_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Market Study app: http://{shown_host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
