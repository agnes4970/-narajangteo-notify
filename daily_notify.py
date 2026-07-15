#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
나라장터 필터 결과 → 카카오톡 '나에게 보내기' 자동 전송  (v2 · 중복방지 포함)
GitHub Actions(daily.yml)에서 매일 실행되는 것을 전제로 함.

동작:
  1) narajangteo_check.collect() 로 오늘 기준 최종 공고 리스트 확보
  2) data/sent.json 에 저장된 "이미 보낸 공고번호" 목록과 대조해 신규만 추림
  3) refresh_token 으로 access_token 재발급
  4) 신규 공고만 카카오톡 '나와의 채팅'으로 전송 (0건이면 아무 것도 안 보냄)
  5) 전송 성공한 공고번호를 data/sent.json 에 추가 저장
     (오래된 항목은 자동 정리 → 파일이 무한정 커지지 않음)

필요 환경변수 (GitHub Secrets 로 주입):
  G2B_API_KEY           나라장터 인증키(Decoding)
  KAKAO_REST_API_KEY    카카오 앱 REST API 키
  KAKAO_REFRESH_TOKEN   kakao_token.py 로 발급받은 refresh_token

상태 파일:
  data/sent.json  { "공고번호-차수": "YYYY-MM-DD(최초 확인일)", ... }
  daily.yml 워크플로가 실행 후 이 파일이 바뀌면 자동으로 커밋/푸시합니다.
  (workflow 에 permissions: contents: write 필요 — daily.yml 에 반영됨)

남은 확인 필요 사항:
  - refresh_token 은 약 2개월마다 만료 → 만료 시 Secret 수동 재발급 필요.
    (응답에 새 refresh_token 이 오면 로그에 경고 출력 — 자동 Secret 갱신은
     별도 PAT + GitHub API 연동이 필요해 이번 단계에서는 보류)
"""

import os
import sys
import json
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("requests 필요: pip install requests")
    sys.exit(1)

import narajangteo_check as njt   # 검증된 필터 로직 재사용

DAYS = 14
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sent.json")
# 마감일이 지나고도 한참 지난 항목은 다시 뜰 일이 없으므로 정리 기준으로 사용.
# (조회기간 DEFAULT_DAYS=14 + 여유를 둬서 넉넉하게 45일 보관)
PRUNE_AFTER_DAYS = 45


def bid_key(b):
    """공고 고유키: 공고번호-차수"""
    return f"{njt.g(b, 'bidNtceNo')}-{njt.g(b, 'bidNtceOrd')}"


def load_sent():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: {STATE_PATH} 읽기 실패({e}) → 빈 상태로 시작")
        return {}


def save_sent(sent):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    # 오래된 항목 정리
    cutoff = (datetime.now() - timedelta(days=PRUNE_AFTER_DAYS)).strftime("%Y-%m-%d")
    pruned = {k: v for k, v in sent.items() if v >= cutoff}
    removed = len(sent) - len(pruned)
    if removed:
        print(f"오래된 전송기록 {removed}건 정리")
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2, sort_keys=True)


def refresh_access_token(rest_key, refresh_token):
    r = requests.post(KAKAO_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    }, timeout=20)
    r.raise_for_status()
    data = r.json()
    # 새 refresh_token 이 함께 올 수 있음(만료 임박 시). 있으면 로그로 남김.
    if data.get("refresh_token"):
        print("NOTE: 새 refresh_token 발급됨 → Secret(KAKAO_REFRESH_TOKEN) 갱신 필요")
    return data["access_token"]


def send_to_me(access_token, text, link_url):
    tmpl = {
        "object_type": "text",
        "text": text[:200],   # 기본 텍스트 템플릿 최대 200자
        "link": {"web_url": link_url or "https://www.g2b.go.kr",
                 "mobile_web_url": link_url or "https://www.g2b.go.kr"},
        "button_title": "공고 보기",
    }
    r = requests.post(
        KAKAO_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(tmpl, ensure_ascii=False)},
        timeout=20,
    )
    return r.status_code, r.text


def main():
    g2b = os.environ.get("G2B_API_KEY")
    rest = os.environ.get("KAKAO_REST_API_KEY")
    rtok = os.environ.get("KAKAO_REFRESH_TOKEN")
    missing = [k for k, v in {"G2B_API_KEY": g2b, "KAKAO_REST_API_KEY": rest,
                              "KAKAO_REFRESH_TOKEN": rtok}.items() if not v]
    if missing:
        print("환경변수 누락:", ", ".join(missing))
        sys.exit(1)

    final, stats = njt.collect(g2b, DAYS, debug=True)
    print(f"\n최종 대상 {stats['final']}건")

    sent = load_sent()
    today_str = datetime.now().strftime("%Y-%m-%d")

    new_items = [b for b in final if bid_key(b) not in sent]
    already = len(final) - len(new_items)
    print(f"기존 전송기록 {len(sent)}건 보유 → 이번 대상 중 신규 {len(new_items)}건 / 중복제외 {already}건")

    if not new_items:
        print("신규 대상 없음 → 전송 생략")
        # 상태 파일은 정리(prune)만 하고 저장 (전송 이력 없이도 오래된 건 청소)
        save_sent(sent)
        return

    access = refresh_access_token(rest, rtok)

    ok = 0
    for b in new_items:
        key = bid_key(b)
        name = njt.g(b, "bidNtceNm")
        inst = njt.g(b, "ntceInsttNm", "dminsttNm")
        close = njt.g(b, *njt.CLOSE_KEYS)
        _, rgn = njt.region_status(b)
        link = njt.g(b, "bidNtceDtlUrl", "bidNtceUrl")
        text = f"[나라장터 교통용역]\n{name}\n· 기관: {inst}\n· 마감: {close}\n· 지역: {rgn}"
        sc, body = send_to_me(access, text, link)
        print("전송", sc, name[:20])
        if sc == 200:
            ok += 1
            sent[key] = today_str   # 성공한 것만 기록 → 실패분은 다음 실행에 재시도됨
        else:
            print(f"  실패 응답: {body[:200]}")
    print(f"\n전송 완료 {ok}/{len(new_items)}건")

    save_sent(sent)


if __name__ == "__main__":
    main()
