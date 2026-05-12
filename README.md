# 당일 시장 정리

유목민님식 당일 시장 복기를 빠르게 하기 위한 로컬 웹앱입니다. 한국 증시에서 상한가 종목과 거래량 1000만주 이상 종목을 자동으로 모으고, 뉴스 원인 후보와 학습 노트를 날짜별로 저장합니다.

## 빠른 실행

```bash
python3 app.py
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다.

## 실행 설명서

### 1. 준비물

- macOS, Windows, Linux 중 하나
- Python 3.9 이상
- 인터넷 연결

로컬 SQLite만 사용할 때는 별도 패키지 없이 실행됩니다. Render Postgres를 사용할 때는 `requirements.txt`의 `psycopg`가 설치되어야 합니다.

### 2. 실행하기

터미널에서 프로젝트 폴더로 이동합니다.

```bash
cd "/Users/pkh/Documents/New project"
```

앱을 실행합니다.

```bash
python3 app.py
```

터미널에 아래와 비슷한 문구가 나오면 정상입니다.

```text
Market Study app: http://127.0.0.1:8765
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8765
```

### 3. 사용 흐름

1. 날짜를 선택합니다.
2. `갱신`을 눌러 당일 데이터를 수집합니다.
3. 상단의 상한가/거래량/총 종목 수와 당일 테마를 확인합니다.
4. `종목 상세` 탭에서 종목별 차트, 원인 후보, 자동 리서치 노트를 봅니다.
5. `주식 4분면` 탭에서 가격 모멘텀과 거래량 에너지를 한눈에 봅니다.
6. `RRG` 탭에서 상대강도와 모멘텀 기준 위치를 확인합니다.
7. 필요한 원인 후보와 `내 의견`을 수정한 뒤 `저장`을 누릅니다.
8. `MD↓` 버튼으로 Markdown 파일을 내보냅니다.

### 4. 저장 위치

- 로컬 DB: `data/market_study.db`
- Markdown 내보내기: `exports/market-summary-YYYY-MM-DD.md`

`data/market_study.db`가 날짜별 기록, 수정한 뉴스 원인, 노트를 보관합니다. 이 파일을 백업하면 공부 기록도 같이 보존됩니다.

### 5. 종료하기

앱을 실행한 터미널에서 `Ctrl + C`를 누르면 서버가 종료됩니다.

### 6. 포트 변경하기

기본 주소는 `127.0.0.1:8765`입니다. 다른 포트를 쓰려면 아래처럼 실행합니다.

```bash
PORT=9000 python3 app.py
```

그 다음 브라우저에서 `http://127.0.0.1:9000`을 엽니다.

## 주요 기능

- 네이버 증권 상한가/거래상위 페이지 기준 상한가와 거래량 1000만주 이상 종목 추출
- 상단 요약: 상한가 수, 거래량 1000만주 이상 수, 총 종목 수
- 종목별 가격, 등락률, 거래량 변화, 캔들/거래량 차트
- PER, PBR, ROE, EPS, 시가총액 도움말
- 뉴스 기반 원인 후보 자동 등록 및 사용자의 수정/삭제/추가
- 회사 소개, 사업군, 테마, 의견을 정리하는 노트 템플릿
- SQLite 로컬 저장: `data/market_study.db`
- 날짜별 기록 조회
- Markdown 내보내기: `exports/market-summary-YYYY-MM-DD.md`
- 당일 테마 자동 추출 및 상단 태그 요약
- Markdown 상단 시장 요약, 우선 복기 후보, 연속 출현 정보
- 저장된 이전 날짜와 비교한 `n일째 상한가`, `n일째 거래량 1000만주` 태그
- 가격 모멘텀과 거래량 에너지 기준 주식 4분면
- 실제 좌표형 4분면 그래프와 종목명 노드 표시
- RRG 그래프: 상대강도와 모멘텀 기준 배치
- 당일 테마 클릭 필터와 종목 유형 필터
- 기본 다크모드, 토글형 다크모드/라이트모드
- 네이버 금융 기업개요/업종/실적 테이블과 뉴스 기반 자동 리서치 메모 초안

## 데이터 메모

실데이터 수집은 네이버 증권 상한가 페이지, 네이버 증권 거래상위 페이지, 네이버 금융 차트, Google News RSS를 사용합니다. 네이버 화면과 최대한 맞추기 위해 상한가는 `sise_upper.naver`, 거래량 후보는 `sise_quant.naver`를 기준으로 가져온 뒤 거래량 1000만주 이상만 남깁니다. ETF/ETN/스팩류는 공부 후보에서 제외합니다. 네트워크가 막혀 있거나 데이터 제공 페이지가 바뀌면 앱은 샘플 데이터를 표시해 화면 흐름을 유지합니다. 실제 공부 기록은 로컬 DB에 저장되므로 수정한 원인과 노트는 다음 갱신 때도 보존됩니다.

## DB 선택 방식

앱은 환경변수 `DATABASE_URL`이 있으면 Postgres를 사용하고, 없으면 기존처럼 SQLite 파일 `data/market_study.db`를 사용합니다.

```bash
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME" python3 app.py
```

Render에서는 `render.yaml`이 Render Postgres의 내부 연결 문자열을 `DATABASE_URL`로 자동 연결합니다.

## 단일 실행 파일로 배포하기

이 프로젝트는 PyInstaller로 하나의 실행 파일로 묶을 수 있게 준비되어 있습니다.

### 1. PyInstaller 설치

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pyinstaller
```

### 2. 빌드

```bash
.venv/bin/python build_single.py
```

빌드가 끝나면 아래 파일이 생성됩니다.

```text
dist/market-study
```

### 3. 실행

```bash
./dist/market-study
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8765
```

### 4. 배포할 파일

기본 배포 파일은 아래 하나입니다.

```text
dist/market-study
```

단, 사용자의 날짜별 기록과 노트는 실행 파일 옆의 `data/market_study.db`에 저장됩니다. 기존 기록까지 같이 옮기려면 `data/` 폴더도 함께 전달하거나 백업해야 합니다.

Markdown 내보내기는 실행 파일 옆의 `exports/` 폴더에 생성됩니다.

### 5. 직접 PyInstaller 명령을 쓰는 경우

`market-study.spec` 파일이 `public/` 폴더를 실행 파일 내부에 포함하도록 설정합니다.

```bash
python3 -m PyInstaller market-study.spec
```

### 6. 참고

- 빌드 결과물은 현재 운영체제용입니다. macOS에서 빌드하면 macOS용 실행 파일이 만들어집니다.
- Windows용 `.exe`가 필요하면 Windows에서 같은 명령으로 빌드하는 것을 추천합니다.
- 실행 파일로 실행해도 인터넷 연결은 필요합니다. KRX, 네이버 금융, Google News RSS에서 데이터를 가져오기 때문입니다.

## Render에 배포하기

Render Web Service와 Render Postgres로 배포할 수 있습니다. 이 저장소에는 `render.yaml` 설정이 포함되어 있습니다.

### 중요한 점

- Render Web Service는 외부 요청을 받기 위해 `0.0.0.0`에 바인딩해야 합니다.
- 앱은 Render 환경에서는 자동으로 `HOST=0.0.0.0`, `PORT` 환경변수를 사용합니다.
- Render에서는 `DATABASE_URL`이 자동 설정되어 Postgres에 기록됩니다.
- Render Free Postgres는 1GB 제한이 있고, 생성 후 30일이 지나면 만료됩니다. 장기 기록용으로 쓰려면 유료 DB 또는 주기적 백업을 권장합니다.
- `DATABASE_URL`이 없는 로컬 실행에서는 SQLite 파일 `data/market_study.db`에 저장됩니다.

### 배포 순서

1. GitHub 저장소에 이 프로젝트를 올립니다.
2. Render에서 `New +` → `Blueprint`를 선택합니다.
3. 이 저장소를 연결합니다.
4. `render.yaml`을 인식하면 `market-study` Web Service와 `market-study-db` Postgres가 생성됩니다.
5. 배포가 끝나면 Render가 제공하는 `*.onrender.com` 주소로 접속합니다.

### 수동 설정으로 배포하는 경우

Render에서 `New +` → `Web Service`를 선택하고 아래처럼 설정합니다.

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: python app.py
Environment Variables:
  HOST=0.0.0.0
  PYTHON_VERSION=3.11.9
  DATABASE_URL=<Render Postgres Internal Database URL>
```

수동 설정에서는 Render에서 `New +` → `Postgres`로 DB를 만든 뒤, Web Service 환경변수 `DATABASE_URL`에 Postgres의 Internal Database URL을 넣습니다.

### Render 배포 시 주의

- 네이버/Google News RSS를 서버에서 호출하므로, 외부 사이트의 차단/응답 변경에 영향을 받을 수 있습니다.
- 무료 Web Service는 잠들거나 재시작될 수 있고, 무료 Postgres는 30일 만료/백업 없음 제약이 있습니다.
- 여러 사용자가 동시에 같은 앱을 쓰면 같은 Postgres DB를 공유하게 됩니다. 개인용 시장 정리 앱으로 쓰는 것이 가장 안전합니다.
