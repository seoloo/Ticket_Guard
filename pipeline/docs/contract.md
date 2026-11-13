<!--
[홍석환] 사용자 흐름 저장·조회 설명
현재 한 시간 기준과 실행·검증 경계를 정리한다.
-->
# DB 저장·대시보드 조회 형식: 사용자 흐름 첫 번째 버전

## 읽기 경계

관리자는 지표 전용 DB의 `flow_read_current`, `flow_read_series`, `flow_health`만 읽는다. 원본 DB 자격 증명이나 쓰기 권한은 필요 없다. `database/flow_permissions.js`를 지표 DB 관리자가 명시적으로 실행하면 공개 포인터를 기준으로 결합하는 읽기 전용 뷰와 최소 권한 역할을 만든다. 기존 계정은 덮어쓰지 않는다.

`flow_public`은 범위별 최신 검증 버전을 가리킨다. `flow_versions`와 `flow_series`에 저장 중인 미공개 문서가 있어도 공개 뷰에는 나타나지 않는다. 두 뷰를 별도로 읽을 때는 반드시 같은 `version`인지 확인한다. 그 사이 갱신되었다면 다시 조회한다. 이전 버전 조회 유예는 30초다.

통합된 버전 읽기는 파이프라인 측 `user_flow.store.read_public`의 동작을 참고한다. 이 함수는 쓰기 계정용 내부 헬퍼이며 관리자 앱으로 파이프라인 코드를 가져오라는 의미는 아니다.

## 범위와 필터

범위 식별자는 전체 `all` 또는 `[시뮬레이션 여부, 공연 식별자, 회차 식별자]`의 공백 없는 JSON 문자열이다. 시뮬레이션 여부는 `true/false/null`이며 `null`은 미확인이다. 실제 관측된 완전 일치 조합과 전체만 생성한다. 최대 100개 범위이며 상한 초과 시 공개를 차단한다.

공연만 선택하는 등의 임의 조합은 현재 지원하지 않는다. 지원하지 않는 필터를 전체로 조용히 대체하거나 사전 계산 비율을 평균 내서 제공하지 않는다. 여러 조합을 합치는 조회가 필요하면 DB 담당자에게 별도의 계산 계약을 요청한다.

## 최신 결과 예시

다음은 구조 설명용 예시이며 실제 화면의 대체 데이터가 아니다. 시각은 UTC이며 화면에서 한국 시각으로 변환할 수 있다.

```json
{
  "_id": "all",
  "version": "검증된_버전_지문",
  "status": "verified",
  "asOf": "2026-11-12T00:00:00Z",
  "result": {
    "scope": "all",
    "status": "verified",
    "metrics": {
      "contractVersion": 1,
      "calculationVersion": 1,
      "countingUnit": "browser_session",
      "asOf": "2026-11-12T00:00:00Z",
      "windowStart": "2026-11-11T23:00:00Z",
      "presenceTimeoutSeconds": 30,
      "current": 10,
      "booking": {"numerator": 3, "denominator": 10, "ratio": 0.3},
      "nodes": [
        {
          "id": "queue", "label": "대기열", "order": 2,
          "current": 4, "entered": 10, "ongoing": 4,
          "dwell": {"meanSeconds": 8.5, "medianSeconds": 8, "samples": 6}
        }
      ],
      "edges": [
        {
          "source": "queue", "target": "captcha", "kind": "forward",
          "moves": 6, "numerator": 6, "denominator": 10, "ratio": 0.6, "ongoing": 4
        }
      ]
    }
  }
}
```

전체 단계와 정의된 기본 연결은 항상 제공한다. `null` 비율은 분모 없음이다. 노드의 현재 인원은 기준 시각의 값이며 체류와 전환율은 최근 1시간 표본의 통계다. 현재 인원은 활동 신호 기반의 추정값이다.

노드·연결선의 색, 크기, 좌표, 선 굵기는 관리자 앱 책임이다. 비율은 0~1이며 백분율 표시 시 100을 곱한다. 체류 시간은 초 단위다. `forward/backward/retry/cancel`은 정상 방향·역방향·동일 단계 재방문·취소 연결을 뜻한다.

## 시계열 예시

`flow_read_series.result`에 같은 공개 버전의 두 배열을 제공한다.

```json
{
  "version": "검증된_버전_지문",
  "presence": [
    {"at": "2026-11-11T23:59:55Z", "asOf": "2026-11-11T23:59:59Z", "current": 9, "observed": true},
    {"at": "2026-11-12T00:00:00Z", "asOf": "2026-11-12T00:00:00Z", "current": 10, "observed": true}
  ],
  "booking": [
    {"at": "2026-11-11T23:59:55Z", "numerator": 3, "denominator": 10, "ratio": 0.3, "ongoing": 7, "observed": true},
    {"at": "2026-11-12T00:00:00Z", "numerator": 0, "denominator": 0, "ratio": null, "ongoing": 0, "observed": true}
  ]
}
```

각 배열은 최근 1시간의 5초 격자다. 미관측 구간은 `observed=false`와 `null` 값으로 제공한다. 빈 구간을 0으로 그리지 않는다. 예매율은 예매 시작 구간 기준이므로 지연된 성공으로 과거 구간의 값이 바뀔 수 있다. 최신 예매율 카드는 `metrics.booking`, 최신 접속 수 카드는 `metrics.current`를 사용한다.

최신 예매율은 분자 합계÷분모 합계다. 그래프 비율들의 평균이 아니다. 최신 접속 수는 마지막 기준 시각의 상태이며 그래프 값의 합계·평균이 아니다.

읽기 시 현재 시각 기준 1시간 필터를 다시 적용한다. 프로세스가 멈추면 마지막 공개 문서는 남으므로 `asOf`, `publishedAt`, `flow_health`를 확인해 오래된 자료임을 표시한다.

## 검증·갱신 상태

- `flow_health.status=verified`: 마지막 갱신 성공.
- `waiting_chunks`: 완성되지 않은 청크가 있어 공개 보류.
- `blocked`: 검증 또는 처리 실패. 이전 공개값 유지.
- 조회 실패·미공개·오래된 자료를 정상값 0으로 바꾸지 않는다.
- 기준 시각, 계산 시각, 검증 시각, 공개 시각은 구분된다.
- 공개 버전은 범위별로 원자적이다. 다른 필터 범위까지 동시에 같은 버전이라는 뜻은 아니다.
- 원본 대조는 소비한 Kafka 레코드와 원본 저장물의 일치를 확인한다. 수집 전에 유실된 행동까지 보장하지 않는다.

## 저장량

최신 요약과 시계열은 분리 저장한다. 시계열당 720개 시점, 접속과 예매 두 배열을 제공한다. 매번 전체 시계열 불변 문서를 기록하므로 공개 유예 기간의 이전 버전 저장 비용이 발생한다. 현재는 단순한 버전 일관성을 우선한 구현이며 장시간·다차원 시험에서 쓰기량을 측정해야 한다. 문서당 8MiB 제한을 넘으면 공개를 차단한다.
