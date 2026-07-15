#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카카오 '나에게 보내기' 토큰 발급 + 테스트 전송  (일회성)

순서:
  1) 아래 REST_API_KEY 를 본인 앱의 REST API 키로 채우기
     (REDIRECT_URI 는 카카오 개발자 콘솔에 등록한 값과 반드시 동일해야 함)
  2) 안내받은 주소로 브라우저 접속 → 카카오 로그인/동의
     → 주소창이 https://localhost:3000/?code=XXXXX 로 바뀌면 그 code 값 복사
       (페이지는 안 열려도 됩니다. 주소창의 code= 뒤 문자열만 필요)
  3)  python kakao_token.py   실행 → code 붙여넣고 엔터
     → ACCESS / REFRESH 토큰 출력 + 카톡으로 테스트 메시지 전송
     → 출력된 REFRESH TOKEN 을 보관 (다음 단계 자동화에 사용)
"""

import sys
import json

try:
    import requests
except ImportError:
    print("requests 모듈이 필요합니다:  pip install requests")
    sys.exit(1)

# ─────────────────────────────────────────────
REST_API_KEY = "ffa4aa77bb7a5b31edf1204fd272f69c"
REDIRECT_URI = "https://localhost:3000"
# ─────────────────────────────────────────────


def get_tokens(code):
    r = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "authorization_code",
        "client_id": REST_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }, timeout=20)
    if r.status_code != 200:
        print("토큰 발급 실패:", r.status_code, r.text)
        sys.exit(1)
    return r.json()


def send_to_me(access_token, text):
    tmpl = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": "https://www.g2b.go.kr",
                 "mobile_web_url": "https://www.g2b.go.kr"},
        "button_title": "나라장터",
    }
    r = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(tmpl, ensure_ascii=False)},
        timeout=20,
    )
    return r.status_code, r.text


def print_authorize_url():
    url = ("https://kauth.kakao.com/oauth/authorize"
           f"?client_id={REST_API_KEY}"
           f"&redirect_uri={REDIRECT_URI}"
           "&response_type=code&scope=talk_message")
    print("\n[인가 코드 받기] 아래 주소를 브라우저에 붙여넣어 접속하세요:\n")
    print(url + "\n")


if __name__ == "__main__":
    if "여기에" in REST_API_KEY:
        print("먼저 파일 상단 REST_API_KEY 를 본인 값으로 채우세요.")
        print_authorize_url()
        sys.exit(1)

    print_authorize_url()
    code = input("주소창의 code= 값을 붙여넣고 엔터: ").strip()

    tok = get_tokens(code)
    at, rt = tok.get("access_token"), tok.get("refresh_token")
    print("\n=== 토큰 발급 결과 ===")
    print("ACCESS TOKEN :", at)
    print("REFRESH TOKEN:", rt)
    print("↑ REFRESH TOKEN 을 꼭 보관하세요 (자동화에 사용).")

    if at:
        sc, body = send_to_me(at, "[테스트] 나라장터 알림 연결 성공")
        print("\n테스트 전송 결과:", sc, body)
        if sc == 200:
            print("카카오톡 '나와의 채팅'에 메시지가 왔는지 확인하세요.")
