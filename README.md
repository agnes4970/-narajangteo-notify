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
| 5 | 필터 결과 → 카톡 전송 + 중복 알림 방지 (`daily_notify.py`) | ✅ 로직 완성(단위 테스트 통과) · 실제 카카오 전송은 미검증 |
| 6 | GitHub Actions 매일 자동 실행 (`daily.yml`) | ✅ 초안 완성(상태파일 자동 커밋 포함) · 실제 Actions 실행 미검증 |

---

## 2. 파일 구성

```
narajangteo_check.py            핵심: 조회 + 필터 (검증 완료). 단독 실행/테스트 가능
kakao_token.py                  카카오 토큰 1회 발급 + 테스트 전송
daily_notify.py                 필터 결과를 카톡으로 전송 (refresh_token 사용) + 중복 알림 방지
data/sent.json                  이미 보낸 공고번호 기록 (최초엔 빈 객체 {} 로 커밋)
.github/workflows/daily.yml     매일 자동 실행 워크플로 (실행 후 data/sent.json 자동 커밋)
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

1. 리포지토리에 `narajangteo_check.py`, `daily_notify.py`, `data/sent.json`(빈 `{}` 로 최초 커밋),
   `.github/workflows/daily.yml` 커밋.
2. Settings > Secrets and variables > Actions 에 Secret 3개 등록:
   `G2B_API_KEY`, `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN`
3. `daily.yml` 의 cron 은 `0 0 * * *`(UTC) = **매일 09:00 KST**. 필요 시 조정.
4. Actions 탭에서 수동 실행(workflow_dispatch)으로 먼저 테스트.
   (워크플로가 `data/sent.json` 을 자동 커밋하므로 `permissions: contents: write` 가
   설정돼 있는지 확인 — 리포 Settings > Actions > General > Workflow permissions 에서
   "Read and write permissions" 이 켜져 있어야 push 가 성공합니다.)

### 중복 알림 방지 (완료)
- `daily_notify.py` 가 `data/sent.json` 에 이미 보낸 공고번호(`bidNtceNo-bidNtceOrd`)를
  기록하고, 다음 실행부터는 그 목록에 없는 것만 전송합니다.
- 전송 성공한 건만 기록하므로, 카카오 API 에러 등으로 실패한 건은 다음 실행에 자동 재시도됩니다.
- 45일 지난 기록은 자동 정리되어 파일이 무한정 커지지 않습니다(마감 지난 공고가 다시 뜰 일은 없음).
- 워크플로 마지막 단계에서 `data/sent.json` 변경분을 리포에 커밋/푸시합니다.

### 남은 구현 포인트
- **refresh_token 자동 갱신**: 카카오 응답에 새 refresh_token 이 오면(만료 임박 시)
  현재는 로그 경고만 출력합니다. Secret 자체를 자동 갱신하려면 별도 PAT +
  GitHub REST API(`PUT /repos/{owner}/{repo}/actions/secrets/{name}`, libsodium 암호화 필요)
  연동이 필요 — 필요하면 다음 단계로 추가 가능합니다.
- 공고가 여러 건일 때 메시지 분할/묶음 전송 정책 결정(현재 1건당 1메시지).
- **실제 카카오톡 전송 검증**: `kakao_token.py` 로 최초 토큰 발급 + 테스트 메시지 수신 확인,
  이어서 `daily_notify.py` 를 로컬에서 한 번 실행해 실제 전송/`sent.json` 갱신을 확인 권장.

---

## 9. 참고

- 공공데이터포털: https://www.data.go.kr (서비스 15129394)
- 카카오 메시지 API(나에게 보내기): https://developers.kakao.com/docs/latest/ko/message/rest-api
