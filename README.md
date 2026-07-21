# 나라장터 교통용역 입찰공고 자동 알림 — 개발 인수인계 문서

매일 나라장터(조달청)의 신규 교통 관련 용역 입찰공고를 자동으로 걸러
카카오톡 '나에게 보내기'로 알림 받는 시스템입니다. 이 문서는 다음 담당자가
남은 자동화를 이어서 완성할 수 있도록 현재까지의 작업을 정리한 것입니다.

---

## 1. 진행 현황

| 단계 | 내용 | 상태 |
|------|------|------|
| 1 | 공공데이터포털 API 키 발급 | ✅ 완료 |
| 2~3 | 조회 + 필터 스크립트 (`narajangteo_check.py`) | ✅ 완료·검증 |
| 4 | 카카오 '나에게 보내기' 토큰 발급 도구 (`kakao_token.py`) | 🔶 도구 준비됨, 실제 발급/전송 확인 필요 |
| 5 | 필터 결과 → 카톡 전송 + 마감일까지 반복 알림 + PDF 리포트 (`daily_notify.py`) | ✅ 로직 완성(단위 테스트 통과) · 실제 카카오 전송은 미검증 |
| 6 | GitHub Actions 매일 자동 실행 (`daily.yml`) | ✅ 초안 완성(상태파일 자동 커밋 포함) · 실제 Actions 실행 미검증 |

---

## 2. 파일 구성

```
narajangteo_check.py            핵심: 조회 + 필터 (검증 완료). 단독 실행/테스트 가능
kakao_token.py                  카카오 토큰 1회 발급 + 테스트 전송
daily_notify.py                 필터 결과를 카톡으로 전송 (refresh_token 사용) + 마감일 전까지 반복 알림
                                 + 조회된 공고 전체를 정리한 PDF 리포트 생성 후 저장소에 커밋
                                 + PDF 링크를 카카오톡으로도 전송
reports/latest_report.pdf       매일 갱신되는 PDF 리포트 (daily_notify.py 가 자동 커밋)
.github/workflows/daily.yml     매일 자동 실행 워크플로 (실행 후 PDF 를 Artifact 로도 업로드)
README.md                       이 문서
```

`daily_notify.py` 는 `narajangteo_check.py` 의 `collect()` 를 그대로 import 해서
필터 로직을 재사용합니다. **필터 규칙을 바꿀 때는 `narajangteo_check.py` 한 곳만
수정하면 자동화에도 그대로 반영됩니다.**

---

## 3. 실행 방법 (검증된 부분)

### 3.1 파이썬 설치
python.org 에서 3.x 설치. 설치 첫 화면에서 **"Add python.exe to PATH" 체크 필수.**

### 3.2 의존성
```
pip install requests
```

### 3.3 API 키 (환경변수)
공공데이터포털 마이페이지의 **일반 인증키(Decoding)** 를 사용합니다.
```
Windows(cmd)      : set G2B_API_KEY=발급받은_디코딩_키
Windows(PowerShell): $env:G2B_API_KEY="발급받은_디코딩_키"
macOS/Linux       : export G2B_API_KEY='발급받은_디코딩_키'
```
> ⚠️ 키/토큰은 코드에 하드코딩하지 말 것. 자동화에서는 GitHub Secrets 로 주입.

### 3.4 실행
```
python narajangteo_check.py            # 최근 14일치 필터 결과 출력
python narajangteo_check.py --days 30  # 기간 조정
python narajangteo_check.py --selftest # API 없이 필터 로직만 점검
```
출력 요약줄: `수집 N → 지역(최우선) N → 업종/용역명 N → 마감유효 N`

---

## 4. 필터 명세 (현재 확정본)

처리 우선순위는 **1 → 4 순서**이며, `narajangteo_check.py` 상단 상수만 고치면 됩니다.

**1) 참가지역제한 — 절대·최우선 게이트**
서울 · 경기 · 전국(제한없음)만 통과. 그 외 지역제한 건은 업종·용역명·업무구분과
무관하게 **먼저** 제외. → 상수 `KEEP_REGIONS`

**2) 업무구분**
기술용역 + 일반용역(용역 전체) 허용. 별도 제한 없음.

**3) 업종코드 + 용역명 조건** → 상수 `INDSTRYTY_CDS`, `NAME_COND`
| 업종코드 | 업종 | 용역명 조건 |
|---------|------|-----------|
| 1132 | 교통영향평가대행자 | 없음 (업종 자체로 포함) |
| 3581 | 엔지니어링사업(교통) | 없음 (업종 자체로 포함) |
| 1169 | 학술연구용역 | 용역명에 '교통' 포함 시에만 |

**4) 마감유효**
입찰마감일이 오늘(검색일) 이후인 건만. 어제 이하 마감 건 제외.

조건 변경 예시:
- 지역 추가 → `KEEP_REGIONS = ["서울", "경기", "인천"]`
- 업종 추가 → `INDSTRYTY_CDS` 에 코드 추가 + `NAME_COND` 에 규칙 추가
- 특정 단어 제외 → `EXCLUDE = ["철거", "청소"]`

---

## 5. 나라장터 API 정보

- **서비스명**: 조달청_나라장터 입찰공고정보서비스 (공공데이터포털 데이터 15129394)
- **Endpoint(base)**: `https://apis.data.go.kr/1230000/ad/BidPublicInfoService`
  (개편 전 경로 `.../1230000/BidPublicInfoService` 도 코드에서 자동 폴백)
- **오퍼레이션**
  - `getBidPblancListInfoServcPPSSrch` — 업종코드(indstrytyCd) 조건 조회 (기본 사용)
  - `getBidPblancListInfoServc` — 용역 전체 목록 (업종코드 0건일 때 폴백)
- **주요 파라미터**: `serviceKey`(디코딩키), `inqryDiv=1`(공고게시일 기준),
  `inqryBgnDt`/`inqryEndDt`(YYYYMMDDHHMM), `type=json`, `numOfRows`, `pageNo`, `indstrytyCd`
- **제약**: 1회 조회 기간 약 15일 → 코드가 자동 14일 단위 분할.
  개발계정 트래픽 약 1,000건/일(업종 3개 × 페이지 수 감안해도 하루 1회 실행은 여유).
- **인증키 주의**: 반드시 **Decoding** 키 사용. (현재 키는 순수 hex라 Encoding=Decoding 동일)

---

## 6. 다음 담당자 확인/검증 권장 사항

1. **지역제한·업무구분 실제 필드명 확정.**
   현재는 필드명을 모른 채로도 동작하도록 "지역 관련 키/값 스캔"(`RGN_KEY_RE`) 및
   "값에 '용역' 포함" 방식으로 처리 중. 실제 응답 원본을 한 번 떠서
   (`getBidPblancListInfoServc` 응답의 지역제한/업무구분 필드명 확인) `RGN_KEY_RE`,
   `BSNS_KEYS`, `CLOSE_KEYS` 를 정확한 필드명으로 고정하면 더 견고해짐.
2. **엔드포인트 `/ad/` 경로 최종 확인.** (콘솔 서비스정보 화면상 `/ad/` 로 표기됨)
3. **PPSSrch 업종코드 조회 정상 여부.** 0건이 뜨면 자동으로 전체목록 폴백됨(정상 동작이나
   업종 필터가 느슨해지므로 로그로 폴백 여부 확인 권장).

---

## 7. 다음 단계 A — 카카오 '나에게 보내기' 연동 (Step 4~5)

'나에게 보내기'는 본인에게만 보내므로 **사업자 등록·앱 검수 없이** 가능합니다.

### 7.1 카카오 개발자 콘솔 세팅 (1회)
1. developers.kakao.com → 내 애플리케이션 → 애플리케이션 추가
2. 앱 설정 > 앱 키 > **REST API 키** 복사
3. 제품 설정 > 카카오 로그인 > 활성화 ON, **Redirect URI** 에 `https://localhost:3000` 등록
4. 제품 설정 > 카카오 로그인 > 동의항목 > **카카오톡 메시지 전송(talk_message)** 사용 설정

### 7.2 토큰 발급 (kakao_token.py)
1. `kakao_token.py` 상단 `REST_API_KEY` 채우기
2. `python kakao_token.py` 실행 → 출력된 인가 주소를 브라우저 접속 → 로그인/동의
3. 주소창이 `https://localhost:3000/?code=XXXX` 로 바뀌면 그 `code` 를 프로그램에 붙여넣기
4. 출력되는 **REFRESH TOKEN** 보관 → 자동화 Secret 으로 사용.
   동시에 카톡 '나와의 채팅'에 테스트 메시지 도착 확인.

### 7.3 토큰 특성
- access_token 수명 약 6시간, refresh_token 약 2개월.
- 자동화(daily_notify.py)는 매 실행마다 refresh_token 으로 access_token 을 재발급.
- refresh_token 만료(~2개월) 또는 회전 시 재발급/Secret 갱신 필요.
- 나에게 보내기 API: `POST https://kapi.kakao.com/v2/api/talk/memo/default/send`,
  기본 텍스트 템플릿 `text` 최대 200자.

---

## 8. 다음 단계 B — 매일 자동 실행 (Step 6, GitHub Actions)

1. 리포지토리에 `narajangteo_check.py`, `daily_notify.py`, `.github/workflows/daily.yml` 커밋.
2. Settings > Secrets and variables > Actions 에 Secret 등록:
   `G2B_API_KEY`, `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN`
   (2번째 수신자를 추가하려면 `KAKAO_REFRESH_TOKEN_2` 도 등록 — 3번째부터는 `_3`, `_4` ... 계속 추가 가능)
3. `daily.yml` 의 cron 은 `7 0 * * *`(UTC) = **매일 09:07 KST**.
   (정각·5분 단위처럼 딱 떨어지는 시각은 GitHub Actions 스케줄 실행이 몰려서 지연되기 쉬워
   애매한 분(20분)으로 설정해 혼잡을 피함. 그래도 GitHub 특성상 몇 분 오차는 있을 수 있음)
4. Actions 탭에서 수동 실행(workflow_dispatch)으로 먼저 테스트.

### 마감일까지 반복 알림 (완료)
- **더 이상 "이미 보낸 공고는 재전송 안 함(dedup)" 로직을 쓰지 않습니다.**
- 매 실행마다 `narajangteo_check.collect()` 가 반환하는 공고(= 아직 마감 전인 공고)를
  **전부** 전송합니다. 즉 같은 공고라도 마감일이 지나기 전까지는 매일 반복해서 알림이 갑니다.
- 마감일이 지나면 `narajangteo_check.py` 의 `deadline_ok()` 가 자동으로 걸러내므로,
  별도 상태 저장 파일(`data/sent.json`) 없이도 마감된 공고는 알림 대상에서 빠집니다.
- 공고 식별은 공고번호(`bidNtceNo-bidNtceOrd`) 기준입니다.
- **주의**: 나라장터 API 특성상 "최근 14일 이내 게시된 공고"만 조회됩니다. 따라서 마감일이
  게시일로부터 14일 이내인 공고는 마감일까지 매일 반복 알림이 가지만, 그보다 훨씬 뒤에
  마감되는(드문 경우) 공고는 게시 14일 후부터 조회 대상에서 빠지면서 알림이 멈출 수 있습니다.

### 마감까지 남은 일수(D-day) 표시
- 카카오톡 메시지에 `마감: 2026-07-24 10:00 (D-3)` 처럼 D-day 가 함께 표시됩니다.
- 당일 마감인 공고는 `(오늘 마감(D-DAY))` 로 표시됩니다.

### PDF 리포트 + 카카오톡 링크 전송 (신규)
- 매 실행마다 조회된 공고 전체(마감 전인 것만)를 정리한 PDF 1개 파일을 생성합니다.
  마감 임박 순으로 정렬되고, 공고명·기관·지역·마감일·D-day 가 표 형태로 정리됩니다.
- 이 PDF는 저장소의 `reports/latest_report.pdf` 로 **자동 커밋 + 푸시**됩니다
  (매일 같은 경로를 덮어씀 — 과거 버전은 git 커밋 히스토리로 남습니다).
- 커밋이 성공하면, 그 커밋 시점 그대로의 PDF를 가리키는 `raw.githubusercontent.com`
  링크를 만들어 **카카오톡 메시지로도 전송**합니다 ("PDF 리포트 보기" 버튼).
  → 이 링크가 로그인 없이 바로 열리려면 **저장소가 Public(공개)** 이어야 합니다.
    Private 상태면 링크 전송은 자동으로 건너뛰고 로그만 남습니다.
- GitHub Actions 실행 결과 화면(Actions 탭 > 해당 실행 > Artifacts)에서도 별도로
  다운로드 가능합니다 (30일 보관, 참고/백업용).
- PDF 생성에는 `reportlab` 패키지와 한글 폰트(나눔고딕)가 필요합니다.
  `daily.yml` 에 `pip install reportlab`, `apt-get install -y fonts-nanum` 단계가 이미 포함돼 있습니다.
  (로컬에서 실행할 때는 커밋/푸시 및 카카오 링크 전송 단계를 자동으로 건너뛰고
  PDF 파일만 생성합니다 — `GITHUB_ACTIONS` 환경변수로 CI 환경 여부를 판별)

### 여러 명에게 전송
- `KAKAO_REFRESH_TOKEN`, `KAKAO_REFRESH_TOKEN_2`, `KAKAO_REFRESH_TOKEN_3` ... 이름으로
  Secret 을 등록한 만큼, 등록된 모든 사람에게 각각 카카오톡이 전송됩니다.
- 각 수신자는 본인 카카오 계정으로 `kakao_token.py` 를 한 번 실행해서 본인 refresh_token 을
  발급받아야 합니다 (REST API 키는 공용 — 앱을 여러 개 만들 필요 없음).

### 남은 구현 포인트
- **refresh_token 자동 갱신**: 카카오 응답에 새 refresh_token 이 오면(만료 임박 시)
  현재는 로그 경고만 출력합니다. Secret 자체를 자동 갱신하려면 별도 PAT +
  GitHub REST API(`PUT /repos/{owner}/{repo}/actions/secrets/{name}`, libsodium 암호화 필요)
  연동이 필요 — 필요하면 다음 단계로 추가 가능합니다.
- **실제 카카오톡 전송 검증**: `kakao_token.py` 로 최초 토큰 발급 + 테스트 메시지 수신 확인,
  이어서 `daily_notify.py` 를 로컬에서 한 번 실행해 실제 전송/PDF 생성을 확인 권장.

---

## 9. 참고

- 공공데이터포털: https://www.data.go.kr (서비스 15129394)
- 카카오 메시지 API(나에게 보내기): https://developers.kakao.com/docs/latest/ko/message/rest-api
