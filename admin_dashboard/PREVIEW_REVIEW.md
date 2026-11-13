<!--
[홍석환] DB 대시보드 세 관점 시안 검토 기록
접속 경로·구현 파일·검증 결과와 실제 데이터 연결 시 교체할 경계를 정리한다.
-->
# DB 대시보드 시안

기존 관리자 로그인 후 다음 주소에서 확인한다.

- 사용자 흐름: `http://localhost:8000/admin/preview#flow`
- 네트워크 상태: `http://localhost:8000/admin/preview#network`
- 이상탐지: `http://localhost:8000/admin/preview#anomaly`

세 관점은 상단 헤더 아래의 버튼으로 전환한다. 직접 주소 접근과 브라우저 뒤로 가기를 지원하며, 자동 갱신은 수행하지 않는다. 기존 `/admin/` 실제 데이터 화면은 유지한다.

## 화면과 데이터

사용자 흐름은 확정한 다섯 지표를 표시한다. 단계별 현재 인원과 완료 체류 평균·중앙값·표본 수, 단계 간 전환율은 네트워크 그래프로 구성한다. 예매율과 현재 동시 접속 인원은 수치 카드와 최근 12시간 시계열로 표현한다. 현재 인원은 최근 활동에 따른 추정값이다.

네트워크와 이상탐지는 검토용 제안이다. HTTP 오류와 응답 미수신, 브라우저 관측과 서버 처리 시간을 구분한다. 이상 신호는 확정 봇 판정이 아니며 위험 점수나 실제 차단 기능은 제공하지 않는다.

모든 자료는 시안용 고정 샘플이다. 시계열과 집계 카드의 계산 근거를 맞추고, 미관측 구간은 0으로 표시하지 않는다. 원본 DB와 QA 자료는 조회하지 않는다.

## 파일별 책임

| 파일 | 역할 |
|---|---|
| `src/ticket_guard_admin/pages.py` | 시안 전용 데이터와 새 템플릿 연결. 실제 화면 함수 유지 |
| `src/ticket_guard_admin/monitoring_preview_data.py` | 세 관점의 고정 샘플과 합계 구성 |
| `templates/monitor_preview.html` | 공통 헤더·관점 탐색·샘플 안내 |
| `templates/monitor_user_flow.html` | 사용자 흐름 확정 지표 |
| `templates/preview_network.html` | 네트워크 제안 지표 |
| `templates/preview_anomaly.html` | 신호 요약·대상 목록·상세 영역 |
| `static/monitor_common.css`, `static/monitor_flow.css` | 공통·관점별 반응형 배치 |
| `static/monitor_charts.js` | 시간축·단위·결측을 처리하는 SVG 시계열 |
| `static/monitor_flow.js` | 단계·연결선과 선택 근거 |
| `static/monitor_anomaly.js` | 대상 검색·필터·상세 타임라인 |
| `static/monitor_navigation.js` | 해시 전환과 화면 크기 변경 처리 |
| `tests/test_monitoring_preview.py` | 데이터 정합성·시안 분리·정적 자원 검사 |
| `tests/check_preview_browser.cjs` | 기존 인증 경로의 브라우저 검사와 캡처 |

템플릿과 정적 파일 경로의 기준은 `src/ticket_guard_admin/`이다. 기존 시안 템플릿과 데이터 모듈은 보존했으며 새 시안의 렌더링 경로에서는 사용하지 않는다.

## 검증 결과

- 관리자 전용 검사와 지정 MongoDB 회귀 검사: 15개 통과.
- QA 전체 검사: 177개 통과.
- 최초 일반 권한 실행은 임시 폴더 접근 제한으로 실패했으며, 동일 검사를 권한 제한 없이 재실행해 통과했다. QA 테스트나 기대값을 수정하지 않았다.
- 실제 기존 게이트웨이의 관리자 인증으로 세 관점·단계 선택·대상 상세·검색·필터·뒤로 가기·직접 접근을 확인했다.
- 데스크톱 1600px, 좁은 화면 390px에서 확인했다. 페이지 전체 가로 넘침과 브라우저 실행 오류는 없었다.
- 작은 화면의 단계 그래프와 긴 표는 각 영역 안에서 가로로 이동한다.
- 관리자 이미지 빌드와 관리자 컨테이너 갱신을 수행했다. 다른 서비스 재시작과 새 공개 포트 추가는 없었다.

캡처는 저장소의 `output/admin-preview/`에 있다. 브라우저 검사에는 설치된 Playwright와 Edge를 사용했다. 재현 시 `PLAYWRIGHT_MODULE`로 모듈 경로를 지정하거나 일반 모듈 탐색 경로에 Playwright를 준비한다. 자격 증명은 로컬 환경 파일에서 읽되 출력하지 않는다.

## 이후 연결

실제 공개 지표 연결은 별도 작업이다. `monitoring_preview_data.py`가 제공하는 화면 전달 경계를 실제 조회 결과로 교체하고, 기존 공개 계약의 버전·단위·필터·결측 의미를 유지해야 한다. 네트워크·이상탐지는 지표와 판정 기준 확정이 먼저 필요하다.

기존 사용자 주석 변경은 보존했다. QA 공용 코드·Spark·DB 구조는 수정하지 않았고 커밋·푸시도 하지 않았다.
