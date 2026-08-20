# 통합 자산 대시보드 (구글시트 실시간 연동)

주식 포트폴리오 / 자산현황 / 가계부, 3개 구글시트를 실시간으로 읽어서
하나의 웹 페이지(고정 링크)로 보여주는 Streamlit 대시보드입니다.
링크를 열 때마다 시트의 최신 값을 다시 읽어옵니다 (10분 캐시).

---

## 0. 폴더 구성

```
wealth_dashboard/
├── app.py                 # 대시보드 본체 (streamlit run app.py)
├── fetch_data.py           # 구글시트에서 데이터 추출
├── sheet_utils.py           # 라벨로 셀 값 찾는 헬퍼
├── requirements.txt
├── .gitignore
└── .streamlit/
    └── secrets_example.toml   # 이걸 복사해서 secrets.toml 로 채우세요
```

---

## 1. 구글 서비스 계정 만들기 (1회만 하면 됨)

1. https://console.cloud.google.com 접속 → 새 프로젝트 생성 (또는 기존 프로젝트 사용)
2. 좌측 메뉴 **API 및 서비스 → 라이브러리** 에서 다음 2개 API를 각각 검색해서 **사용 설정**
   - Google Sheets API
   - Google Drive API
3. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → 서비스 계정**
   - 이름 아무거나 (예: `wealth-dashboard`)
   - 역할은 지정 안 해도 됩니다 (본인 시트만 읽을 거라서)
4. 생성된 서비스 계정 클릭 → **키 → 키 추가 → JSON** → `service_account.json` 다운로드
5. JSON 파일 안의 `client_email` 값 (예: `wealth-dashboard@xxx.iam.gserviceaccount.com`) 을 복사해두세요.

## 2. 3개 구글시트를 서비스 계정과 공유

각 시트에서 **공유** 버튼 → 방금 복사한 `client_email` 주소를 붙여넣고 **뷰어(읽기 전용)** 권한으로 초대.
(3개 시트 모두 반복)

## 3. secrets.toml 채우기

```bash
cp .streamlit/secrets_example.toml .streamlit/secrets.toml
```

다운로드한 `service_account.json`을 열어서 각 값을 `secrets.toml`에 그대로 옮겨 적습니다.
`private_key`는 줄바꿈(`\n`)이 포함된 긴 문자열이니 통째로 복사하세요.

**이 파일은 절대 GitHub에 올리면 안 됩니다** (`.gitignore`에 이미 걸려 있음).

## 4. 로컬에서 실행해보기

```bash
pip install -r requirements.txt
streamlit run app.py
```

브라우저가 자동으로 열리고 `http://localhost:8501` 에서 대시보드가 보입니다.
숫자가 이상하면 사이드바의 **디버그 모드**를 켜고 터미널에 찍히는 원본 값들을 확인하세요.
(시트 구조상 라벨이 여러 번 나오는 경우 엉뚱한 값을 집을 수 있어서, `fetch_data.py` 안의
`occurrence` 값을 조정해야 할 수도 있습니다.)

## 5. 웹에 배포해서 고정 링크 만들기 (Streamlit Community Cloud, 무료)

1. 이 폴더를 GitHub 저장소로 올립니다 (`secrets.toml`, `service_account.json`은 제외한 채로).
2. https://share.streamlit.io 접속 → GitHub 계정 연결 → **New app**
3. 방금 올린 저장소 / 브랜치 / `app.py` 선택 → **Deploy**
4. 배포된 앱 화면에서 **Settings → Secrets** 에 들어가서
   `.streamlit/secrets.toml`에 적었던 내용을 그대로 붙여넣고 저장.
5. 몇 분 뒤 `https://<앱이름>.streamlit.app` 같은 고정 링크가 발급됩니다.
   이 링크가 바로 "특정 웹 링크에서 활성화되는" 대시보드입니다.
   접속할 때마다 최신 시트 값을 다시 불러옵니다.

## 6. 참고 사항 / 한계

- 라벨 검색 방식이라 시트에 **행을 추가/삭제**하는 정도는 잘 버팁니다. 다만 **열 구조(컬럼 순서)를
  통째로 바꾸면** 다시 확인이 필요할 수 있어요.
- 같은 라벨(`자산`, `순자산` 등)이 시트 안에 여러 번 나오는 경우 첫 번째 매칭을 사용합니다.
  다른 곳을 가리키면 `fetch_data.py`에서 `occurrence=1` 등으로 바꿔주세요.
- 가계부 수입(`총 수입`) 항목이 비어있는 달이 많으면 저축여력 계산이 부정확합니다 —
  매달 수입을 채워 넣는 게 이 대시보드를 정확하게 만드는 가장 쉬운 방법입니다.
- 서비스 계정 키는 비밀번호와 같습니다. 절대 공개 저장소에 커밋하지 마세요.
