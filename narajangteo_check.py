#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
나라장터 용역 입찰공고 - 교통영향평가 알림  (v8)
조달청 공식 OpenAPI(나라장터 입찰공고정보서비스) 사용.

필터 우선순위:
  1) 참가지역제한 (절대·최우선): 서울특별시 / 경기도 / 전국(제한없음) → 그 외 즉시 제외
  2) 업무구분: 기술용역 + 일반용역 (용역 전체)
  3) 업종코드 + 용역명 조건:
      · 1132 교통영향평가대행자   → 용역명 조건 없음
      · 3581 엔지니어링사업(교통) → 용역명 조건 없음
      · 1169 학술연구용역         → 용역명에 '교통' 포함 시에만
  4) 마감유효: 입찰마감일이 오늘(검색일) 이후인 건만
  - 기간(기본): 최근 14일

  * collect(api_key, days) 가 최종 공고 리스트를 반환 → 자동화(daily_notify.py)에서 재사용

사용법:
  set G2B_API_KEY=발급받은_디코딩_키
  python narajangteo_check.py
"""

import os
import sys
import re
import argparse
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("requests 모듈이 필요합니다:  pip install requests")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────
# 검색 조건  ← 여기만 손보시면 됩니다
# ─────────────────────────────────────────────────────────────
INDSTRYTY_CDS = ["1132", "3581", "1169"]        # 업종코드 (OR)
NAME_COND = {
    "1132": [],            # 교통영향평가대행자
    "3581": [],            # 엔지니어링사업(교통)
    "1169": ["교통"],      # 학술연구용역 → 용역명에 '교통'
}
DEFAULT_NAME_COND = ["교통"]
EXCLUDE       = []
KEEP_REGIONS  = ["서울", "경기"]                 # + 전국(제한없음) 유지
DEFAULT_DAYS  = 14
# ─────────────────────────────────────────────────────────────

OTHER_REGIONS = ["부산", "대구", "인천", "광주", "대전", "울산", "세종",
                 "강원", "충북", "충남", "전북", "전남", "경북", "경남",
                 "제주", "충청", "전라", "경상"]
RGN_KEY_RE = re.compile(r'(rgn.*lmt|lmt.*rgn|prtcpt.*rgn|rgn.*prtcpt|지역제한|참가.*지역)', re.I)
BSNS_KEYS = ("bsnsDivNm", "bidNtceBsnsDivNm", "bsnsDiv", "workDivNm", "업무구분")
CLOSE_KEYS = ("bidClseDt", "bidClseDate", "opengDt")

BASE_CANDIDATES = [
    "http://apis.data.go.kr/1230000/ad/BidPublicInfoService",
    "http://apis.data.go.kr/1230000/BidPublicInfoService",
]
OP_SRCH = "getBidPblancListInfoServcPPSSrch"
OP_LIST = "getBidPblancListInfoServc"


def _extract_items(body):
    items = body.get("items")
    if not items:
        return []
    item = items.get("item", []) if isinstance(items, dict) else items
    if isinstance(item, dict):
        return [item]
    return item or []


def _call(base, op, api_key, bdt, edt, extra, debug):
    items, page = [], 1
    while True:
        params = {"serviceKey": api_key, "inqryDiv": "1",
                  "inqryBgnDt": bdt, "inqryEndDt": edt,
                  "type": "json", "numOfRows": "100", "pageNo": str(page)}
        params.update(extra)
        r = requests.get(f"{base}/{op}", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        header = data.get("response", {}).get("header", {})
        code = header.get("resultCode")
        if code not in ("00", "0", None):
            raise RuntimeError(f"API 오류 [{code}] {header.get('resultMsg')}")
        body = data.get("response", {}).get("body", {})
        got = _extract_items(body)
        items.extend(got)
        total = int(body.get("totalCount", 0) or 0)
        if debug:
            print(f"      p{page}: {len(got)}건 (누적 {len(items)}/{total})")
        if len(items) >= total or not got:
            break
        page += 1
    return items


def _dedup(rows):
    seen, uniq = set(), []
    for b in rows:
        key = (b.get("bidNtceNo", ""), b.get("bidNtceOrd", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return uniq


def fetch(api_key, bdt, edt, debug=False):
    last_err = None
    for base in BASE_CANDIDATES:
        try:
            rows = []
            for cd in INDSTRYTY_CDS:
                if debug:
                    print(f"  [\uc5c5\uc885 {cd}]")
                got = _call(base, OP_SRCH, api_key, bdt, edt, {"indstrytyCd": cd}, debug)
                for x in got:
                    x.setdefault("_srchIndstrytyCd", cd)
                rows += got
            rows = _dedup(rows)
            if rows:
                if debug:
                    print(f"  \u2192 \uc5c5\uc885\ucf54\ub4dc \uc870\ud68c \uc131\uacf5: {len(rows)}\uac74")
                return rows
            if debug:
                print("  \u2192 \uc5c5\uc885\ucf54\ub4dc \uc870\ud68c 0\uac74, \uc804\uccb4\ubaa9\ub85d \ud3f4\ubc31")
            return _dedup(_call(base, OP_LIST, api_key, bdt, edt, {}, debug))
        except Exception as e:
            last_err = e
            if debug:
                print(f"  [{base}] \uc2e4\ud328: {e}")
            continue
    raise RuntimeError(f"\ubaa8\ub4e0 \uc5d4\ub4dc\ud3ec\uc778\ud2b8 \uc2e4\ud328: {last_err}")


def g(row, *keys):
    for k in keys:
        v = row.get(k)
        if v:
            return v
    return ""


def region_status(row):
    hits = [(k, str(v)) for k, v in row.items() if RGN_KEY_RE.search(k) and str(v).strip()]
    blob = " ".join(v for _, v in hits)
    if not blob.strip():
        return "keep", "\uc81c\ud55c\uc5c6\uc74c(\uc804\uad6d)"
    if any(r in blob for r in KEEP_REGIONS):
        return "keep", blob
    if any(r in blob for r in OTHER_REGIONS):
        return "drop", blob
    return "keep", blob


def name_ok(row):
    name = g(row, "bidNtceNm")
    if not name:
        return False
    if any(x in name for x in EXCLUDE):
        return False
    cond = NAME_COND.get(row.get("_srchIndstrytyCd"), DEFAULT_NAME_COND)
    return True if not cond else any(k in name for k in cond)


def close_date(row):
    s = g(row, *CLOSE_KEYS)
    d = re.sub(r"\D", "", str(s))[:8]
    if len(d) < 8:
        return None
    try:
        return datetime.strptime(d, "%Y%m%d").date()
    except ValueError:
        return None


def deadline_ok(row, today):
    d = close_date(row)
    return True if d is None else d >= today


def bsns_label(row):
    lbl = g(row, *BSNS_KEYS)
    if lbl:
        return lbl
    for v in row.values():
        if "\uc6a9\uc5ed" in str(v):
            return str(v)
    return "-"


def collect(api_key, days=DEFAULT_DAYS, debug=False):
    """필터를 모두 통과한 최종 공고 리스트와 단계별 카운트를 반환."""
    now = datetime.now()
    today = now.date()
    begin = (now - timedelta(days=days)).replace(hour=0, minute=0)
    bdt, edt = begin.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d%H%M")
    rows = fetch(api_key, bdt, edt, debug=debug)
    region_kept = [b for b in rows if region_status(b)[0] == "keep"]   # 1) 지역 최우선
    cond_kept = [b for b in region_kept if name_ok(b)]                 # 3) 업종/용역명
    final = [b for b in cond_kept if deadline_ok(b, today)]            # 4) 마감유효
    stats = {"rows": len(rows), "region": len(region_kept),
             "cond": len(cond_kept), "final": len(final),
             "expired": len(cond_kept) - len(final)}
    return final, stats


def format_line(b):
    """카톡/로그용 1건 요약 문자열."""
    name = g(b, "bidNtceNm")
    inst = g(b, "ntceInsttNm", "dminsttNm")
    close = g(b, *CLOSE_KEYS)
    _, rgn = region_status(b)
    url = g(b, "bidNtceDtlUrl", "bidNtceUrl")
    return f"{name}\n기관: {inst}\n마감: {close} | 지역: {rgn}\n{url}"


def print_hit(b):
    no, ordn = g(b, "bidNtceNo"), g(b, "bidNtceOrd")
    cd = b.get("_srchIndstrytyCd", "")
    _, rgn = region_status(b)
    print(f"\u25a0 {g(b,'bidNtceNm')}")
    print(f"   \uae30\uad00: {g(b,'ntceInsttNm','dminsttNm')}")
    print(f"   \uc9c0\uc5ed: {rgn}   |  \uc5c5\uc885\ucf54\ub4dc: {cd}   |  \uc5c5\ubb34\uad6c\ubd84: {bsns_label(b)}")
    print(f"   \ub9c8\uac10: {g(b,*CLOSE_KEYS)}   |  \ubc88\ud638: {no}-{ordn}")
    u = g(b, "bidNtceDtlUrl", "bidNtceUrl")
    if u:
        print(f"   \ub9c1\ud06c: {u}")
    print("-" * 74)


def run(api_key, days):
    print(f"\uc870\ud68c\uae30\uac04: \ucd5c\uadfc {days}\uc77c\n")
    final, s = collect(api_key, days, debug=True)
    print(f"\n\uc218\uc9d1 {s['rows']} \u2192 \uc9c0\uc5ed(\ucd5c\uc6b0\uc120) {s['region']} \u2192 \uc5c5\uc885/\uc6a9\uc5ed\uba85 {s['cond']} \u2192 \ub9c8\uac10\uc720\ud6a8 {s['final']}")
    print("=" * 74)
    for b in final:
        print_hit(b)
    if s["expired"]:
        print(f"\n(\ub9c8\uac10 \uc9c0\ub0a8\uc73c\ub85c \uc81c\uc678 {s['expired']}\uac74)")
    if not final:
        print("\ud574\ub2f9 \uae30\uac04 \uc870\uac74\uc5d0 \ub9de\ub294 \uacf5\uace0 \uc5c6\uc74c.")


def selftest():
    print("=== \ud544\ud130 \uc790\uccb4\uc810\uac80 ===\n")
    today = datetime.now().date()
    fut = (today + timedelta(days=7)).strftime("%Y-%m-%d 10:00")
    pst = (today - timedelta(days=3)).strftime("%Y-%m-%d 10:00")
    S = [
        {"bidNtceNm": "A \uad50\ud1b5\uc601\ud5a5\ud3c9\uac00 \uc6a9\uc5ed", "_srchIndstrytyCd": "1132", "rgnLmtBidLocplcJdgmBassNm": "", "bidClseDt": fut},
        {"bidNtceNm": "B \uad50\ud1b5\uc18c\ud1b5\ub300\ucc45", "_srchIndstrytyCd": "1169", "prtcptPsblRgnNm": "\uacbd\uae30\ub3c4", "bidClseDt": fut},
        {"bidNtceNm": "C \uad50\ud1b5\ub7c9 \uc870\uc0ac", "_srchIndstrytyCd": "1169", "rgnLmtBidLocplcJdgmBassNm": "\ubd80\uc0b0\uad11\uc5ed\uc2dc", "bidClseDt": fut},
        {"bidNtceNm": "D \ud559\uc220\uc5f0\uad6c", "_srchIndstrytyCd": "1169", "rgnLmtBidLocplcJdgmBassNm": "", "bidClseDt": fut},
        {"bidNtceNm": "E \uad50\ud1b5\uc601\ud5a5\ud3c9\uac00", "_srchIndstrytyCd": "1132", "rgnLmtBidLocplcJdgmBassNm": "", "bidClseDt": pst},
    ]
    for b in S:
        rg = region_status(b)[0] == "keep"
        nm = name_ok(b)
        dl = deadline_ok(b, today)
        keep = rg and nm and dl
        why = "" if keep else (" (\uc9c0\uc5ed)" if not rg else (" (\uc6a9\uc5ed\uba85)" if not nm else " (\ub9c8\uac10\uc9c0\ub0a8)"))
        print(f"  {'\u2713 \uc720\uc9c0' if keep else '\u2717 \uc81c\uc678'}{why}  {b['bidNtceNm']}")
    final = [b for b in S if region_status(b)[0] == "keep" and name_ok(b) and deadline_ok(b, today)]
    print(f"\n\ucd5c\uc885 {len(final)}\uac74  (\uae30\ub300: A\u00b7B \uc720\uc9c0 / C\uc9c0\uc5ed\u00b7D\uc6a9\uc5ed\uba85\u00b7E\ub9c8\uac10 \uc81c\uc678)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        sys.exit(0)
    key = os.environ.get("G2B_API_KEY")
    if not key:
        print("\ud658\uacbd\ubcc0\uc218 G2B_API_KEY \uac00 \uc5c6\uc2b5\ub2c8\ub2e4.")
        sys.exit(1)
    run(key, args.days)
