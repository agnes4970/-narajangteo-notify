#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
나라장터 필터 결과 → 카카오톡 '나에게 보내기' 자동 전송 + PDF 리포트 생성/공유  (v6)
GitHub Actions(daily.yml)에서 매일 실행되는 것을 전제로 함.

동작:
  1) narajangteo_check.collect() 로 오늘 기준 최종 공고 리스트 확보
     (deadline_ok() 가 이미 마감 지난 공고를 걸러내므로 항상 "마감 전" 공고만 남음)
  2) 각 공고의 "마감일까지 남은 일수(D-day)"를 계산
  3) 등록된 각 refresh_token 별로 access_token 재발급
  4) 조회된 공고 전체를 등록된 모든 사람에게 각각 카카오톡 '나와의 채팅'으로 전송
     → 같은 공고라도 마감일이 지나기 전까지는 매일 반복해서 알림이 갑니다.
  5) 조회된 공고 전체를 정리한 PDF 리포트를 reports/latest_report.pdf 로 저장하고,
     (GitHub Actions 환경이면) 저장소에 자동 커밋 + 푸시합니다.
  6) 푸시가 성공하면, 그 커밋 시점의 GitHub 파일 보기(HTML) 페이지 링크를 담은
     카카오톡 메시지를
     ("PDF 리포트 보기" 버튼) 각 수신자에게 1건 추가로 전송합니다.
     ※ 이 링크가 열리려면 저장소가 Public(공개) 이어야 합니다 — Private 이면 로그인 없이는
       링크가 안 열려서, 이 경우 PDF 링크 메시지는 건너뛰고 로그만 남깁니다.

  ※ "이미 보낸 공고 재전송 안 함(dedup)" 기능은 사용하지 않습니다.
    대신 마감일 경과 여부로만 알림 종료를 제어합니다.

필요 환경변수 (GitHub Secrets 로 주입):
  G2B_API_KEY           나라장터 인증키(Decoding)
  KAKAO_REST_API_KEY    카카오 앱 REST API 키 (모든 수신자 공통)
  KAKAO_REFRESH_TOKEN   1번째 수신자의 refresh_token
  KAKAO_REFRESH_TOKEN_2 2번째 수신자의 refresh_token (선택, 이런 식으로 _3, _4 ... 계속 추가 가능)

PDF 생성/공유 요구사항:
  - reportlab 라이브러리 + 한글 폰트(나눔고딕) 필요 (daily.yml 에 설치 단계 포함됨)
  - PDF를 저장소에 커밋하려면 GITHUB_TOKEN 에 쓰기 권한 필요 (daily.yml 의
    permissions: contents: write 로 이미 설정됨)
  - 로컬(내 컴 터)에서 실행할 때는 커밋/푸시 단계를 건너뛰고 PDF 파일만 생성합니다
    (GITHUB_ACTIONS 환경변수로 CI 환경 여부를 판별)
"""

import os
import sys
import json
import subprocess
from datetime import datetime

try:
    import requests
except ImportError:
    print("requests 필요: pip install requests")
    sys.exit(1)

import narajangteo_check as njt   # 검증된 필터 로직 재사용

DAYS = 14
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PDF_REL_PATH = os.path.join("reports", "latest_report.pdf")
PDF_ABS_PATH = os.path.join(REPO_ROOT, PDF_REL_PATH)

NANUM_REGULAR_CANDIDATES = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]
NANUM_BOLD_CANDIDATES = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]


def collect_refresh_tokens():
    tokens = []
    first = os.environ.get("KAKAO_REFRESH_TOKEN")
    if first:
        tokens.append(("수신자1", first))
    i = 2
    while True:
        t = os.environ.get(f"KAKAO_REFRESH_TOKEN_{i}")
        if not t:
            break
        tokens.append((f"수신자{i}", t))
        i += 1
    return tokens


def days_remaining(b, today):
    d = njt.close_date(b)
    if d is None:
        return None
    return (d - today).days


def dday_label(n):
    if n is None:
        return "마감일 미상"
    if n <= 0:
        return "오늘 마감(D-DAY)"
    return f"D-{n}"


def refresh_access_token(rest_key, refresh_token, label):
    r = requests.post(KAKAO_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    }, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("refresh_token"):
        print(f"NOTE: [{label}] 새 refresh_token 발급됨 → 해당 Secret 갱신 필요")
    return data["access_token"]


def send_to_me(access_token, text, link_url=None, button_title="공고 보기"):
    tmpl = {
        "object_type": "text",
        "text": text[:200],
        "link": {"web_url": link_url or "https://www.g2b.go.kr",
                 "mobile_web_url": link_url or "https://www.g2b.go.kr"},
        "button_title": button_title,
    }
    r = requests.post(
        KAKAO_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(tmpl, ensure_ascii=False)},
        timeout=20,
    )
    return r.status_code, r.text


def generate_pdf(items, today):
    """조회된 공고 전체를 정리한 PDF 1개 파일 생성. 실패해도 전체 흐름은 계속 진행."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle)
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        print("reportlab 미설치 → PDF 생성 건너뜀 (pip install reportlab)")
        return False

    reg_path = next((p for p in NANUM_REGULAR_CANDIDATES if os.path.exists(p)), None)
    bold_path = next((p for p in NANUM_BOLD_CANDIDATES if os.path.exists(p)), None)
    if not reg_path:
        print("한글 폰트(나눔고딕) 없음 → PDF 생성 건너뜀")
        return False

    os.makedirs(os.path.dirname(PDF_ABS_PATH), exist_ok=True)

    pdfmetrics.registerFont(TTFont("Nanum", reg_path))
    pdfmetrics.registerFont(TTFont("NanumBold", bold_path or reg_path))

    title_style = ParagraphStyle("title", fontName="NanumBold", fontSize=16, leading=20)
    meta_style = ParagraphStyle("meta", fontName="Nanum", fontSize=9, textColor=colors.grey)
    cell_style = ParagraphStyle("cell", fontName="Nanum", fontSize=9.5, leading=13)
    cell_bold_style = ParagraphStyle("cell_bold", fontName="NanumBold", fontSize=9.5, leading=13)
    dday_style = ParagraphStyle("dday", fontName="NanumBold", fontSize=9.5, leading=13,
                                 textColor=colors.HexColor("#B00020"))

    doc = SimpleDocTemplate(PDF_ABS_PATH, pagesize=A4,
                             topMargin=18 * mm, bottomMargin=15 * mm,
                             leftMargin=15 * mm, rightMargin=15 * mm)
    story = [
        Paragraph("나라장터 교통용역 입찰공고 알림 리스트", title_style),
        Paragraph(f"생성일: {today.strftime('%Y-%m-%d')}  ·  마감 전인 공고 {len(items)}건 (마감일 임박 순 정렬)",
                   meta_style),
        Spacer(1, 10 * mm),
    ]

    def sort_key(b):
        n = days_remaining(b, today)
        return (n is None, n if n is not None else 9999)
    sorted_items = sorted(items, key=sort_key)

    table_data = [[
        Paragraph("<b>공고명 / 기관</b>", cell_bold_style),
        Paragraph("<b>지역</b>", cell_bold_style),
        Paragraph("<b>마감일</b>", cell_bold_style),
        Paragraph("<b>D-day</b>", cell_bold_style),
    ]]
    for b in sorted_items:
        name = njt.g(b, "bidNtceNm")
        inst = njt.g(b, "ntceInsttNm", "dminsttNm")
        close = njt.g(b, *njt.CLOSE_KEYS)
        _, rgn = njt.region_status(b)
        n = days_remaining(b, today)
        name_cell = Paragraph(f"{name}<br/><font size=8 color='#666666'>{inst}</font>", cell_style)
        table_data.append([
            name_cell,
            Paragraph(rgn, cell_style),
            Paragraph(close, cell_style),
            Paragraph(dday_label(n), dday_style),
        ])

    col_widths = [95 * mm, 22 * mm, 30 * mm, 23 * mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#032D90")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(table)

    doc.build(story)
    print(f"PDF 리포트 생성 완료: {PDF_ABS_PATH}")
    return True


def _run_git(args):
    return subprocess.run(["git"] + args, cwd=REPO_ROOT,
                           capture_output=True, text=True)


def commit_and_push_pdf():
    """GitHub Actions 환경에서만 PDF를 커밋/푸시. 성공 시 raw.githubusercontent.com 링크 반환."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("로컬 실행 환경 → PDF 커밋/푸시 및 카카오 링크 전송 생략")
        return None

    repo = os.environ.get("GITHUB_REPOSITORY")  # 예: agnes4970/-narajangteo-notify
    if not repo:
        print("WARNING: GITHUB_REPOSITORY 확인 불가 → PDF 링크 생략")
        return None

    try:
        _run_git(["config", "user.name", "github-actions[bot]"])
        _run_git(["config", "user.email", "github-actions[bot]@users.noreply.github.com"])
        _run_git(["add", PDF_REL_PATH])

        status = _run_git(["status", "--porcelain", PDF_REL_PATH])
        if not status.stdout.strip():
            print("PDF 변경 없음 → 커밋 생략, 기존 커밋 기준으로 링크 생성")
        else:
            commit = _run_git(["commit", "-m", "chore: update daily bid report"])
            if commit.returncode != 0:
                print(f"WARNING: git commit 실패 → {commit.stderr[:300]}")
                return None
            push = _run_git(["push"])
            if push.returncode != 0:
                print(f"WARNING: git push 실패 → {push.stderr[:300]}")
                return None

        sha = _run_git(["rev-parse", "HEAD"]).stdout.strip()
        if not sha:
            return None
        # raw.githubusercontent.com (파일 원본 그대로) 링크는 카카오톡 인앱 브라우저에서
        # 미리보기가 안 돼 탭해도 반응이 없는 경우가 있어, GitHub 파일 보기(HTML) 페이지로 연결.
        # 이 페이지 안에 PDF 뷰어가 내장되어 바로 보이고, 다운로드도 그 화면에서 가능함.
        url = f"https://github.com/{repo}/blob/{sha}/{PDF_REL_PATH}"
        print(f"PDF 링크 생성: {url}")
        return url
    except Exception as e:
        print(f"WARNING: PDF 커밋/푸시 중 오류 → {e}")
        return None


def main():
    g2b = os.environ.get("G2B_API_KEY")
    rest = os.environ.get("KAKAO_REST_API_KEY")
    missing = [k for k, v in {"G2B_API_KEY": g2b, "KAKAO_REST_API_KEY": rest}.items() if not v]
    if missing:
        print("환경변수 누락:", ", ".join(missing))
        sys.exit(1)

    recipients = collect_refresh_tokens()
    if not recipients:
        print("환경변수 누락: KAKAO_REFRESH_TOKEN (최소 1명은 등록돼야 합니다)")
        sys.exit(1)
    print(f"등록된 수신자 수: {len(recipients)}명")

    final, stats = njt.collect(g2b, DAYS, debug=True)
    print(f"\n최종 대상 {stats['final']}건 (마감 전인 공고만 · 매일 반복 알림)")

    today = datetime.now().date()

    if not final:
        print("대상 없음 → 전송/PDF 생략")
        return

    pdf_ok = generate_pdf(final, today)
    pdf_url = commit_and_push_pdf() if pdf_ok else None

    access_tokens = []
    for label, rtok in recipients:
        try:
            at = refresh_access_token(rest, rtok, label)
            access_tokens.append((label, at))
        except Exception as e:
            print(f"WARNING: [{label}] access_token 재발급 실패 → 이번 실행에서 제외: {e}")

    if not access_tokens:
        print("전송 가능한 수신자가 없습니다 (모든 refresh_token 재발급 실패). 종료.")
        sys.exit(1)

    total_msgs_ok = 0
    total_msgs_try = 0
    for b in final:
        name = njt.g(b, "bidNtceNm")
        inst = njt.g(b, "ntceInsttNm", "dminsttNm")
        close = njt.g(b, *njt.CLOSE_KEYS)
        _, rgn = njt.region_status(b)
        link = njt.g(b, "bidNtceDtlUrl", "bidNtceUrl")
        n = days_remaining(b, today)
        text = (f"[나라장터 교통용역]\n{name}\n"
                f"· 기관: {inst}\n"
                f"· 마감: {close} ({dday_label(n)})\n"
                f"· 지역: {rgn}")

        for label, at in access_tokens:
            total_msgs_try += 1
            sc, body = send_to_me(at, text, link, button_title="공고 보기")
            print(f"전송[{label}] {sc} {name[:20]}")
            if sc == 200:
                total_msgs_ok += 1
            else:
                print(f"  실패 응답: {body[:200]}")

    print(f"\n메시지 전송 완료 {total_msgs_ok}/{total_msgs_try}건 (공고 {len(final)}건 × 수신자 {len(access_tokens)}명 기준)")

    # 마지막으로 PDF 리포트 링크 1건 추가 전송 (커밋/푸시가 성공한 경우에만)
    if pdf_url:
        pdf_text = (f"📎 오늘의 나라장터 교통용역 리포트\n"
                    f"마감 전인 공고 {len(final)}건이 마감 임박 순으로 정리된 PDF입니다.")
        for label, at in access_tokens:
            sc, body = send_to_me(at, pdf_text, pdf_url, button_title="PDF 리포트 보기")
            print(f"PDF 링크 전송[{label}] {sc}")
            if sc != 200:
                print(f"  실패 응답: {body[:200]}")
    elif pdf_ok:
        print("PDF는 생성됐지만 링크 전송은 건너뜀 (로컬 실행이거나 저장소 푸시 실패)")


if __name__ == "__main__":
    main()
