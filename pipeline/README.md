<!--
[홍석환] Spark 처리 모듈과 실행 안내
기존 구조를 유지하면서 한 시간 지표 처리와 재현 가능한 검사 위치를 안내한다.
-->
# Spark 파이프라인

환경 설정, 처리 기능, DB 설정, 점검 도구와 문서를 역할별로 분리한다.

```text
pipeline/
├─ main.py                  실행 진입점: ingest / check / flow
├─ Dockerfile               컨테이너 빌드 및 실행
├─ configuration/           환경 설정
│  ├─ ingest.py             기존 적재 설정
│  ├─ user_flow.py          사용자 흐름 설정
│  ├─ flow.env.example      사용자 흐름 환경변수 예시
│  ├─ requirements.txt      Python 의존성
│  └─ log4j2.properties     Spark 로깅 설정
├─ ingestion/               기존 이벤트 적재 기능
│  ├─ records.py            Kafka 레코드 변환
│  ├─ normalization.py      이벤트 정규화
│  └─ mongo_writer.py       MongoDB 적재
├─ user_flow/               사용자 흐름 지표 기능
│  ├─ events.py             이벤트 해석·관측값 추출
│  ├─ metrics.py            지표 계산
│  ├─ state.py              복구 상태·청크 관리
│  ├─ verification.py       원본 DB 대조 검증
│  ├─ store.py              결과 저장·공개
│  └─ runtime.py            처리 연결·주기적 갱신
├─ database/                DB 권한 설정
│  └─ flow_permissions.js
├─ tools/                   빌드·실행 점검 도구
│  ├─ resolve_dependencies.py
│  ├─ check.py
│  └─ check_imports.py        외부 연결 없는 모듈 경로 확인
└─ docs/                    설계·운영·검증 문서
   ├─ user_flow.md
   ├─ contract.md
   └─ validation.md
```

실행 진입점과 Docker 빌드 위치는 유지한다. 저장소 루트의 `compose.yml`은 기존 적재, `compose.flow.yml`은 사용자 흐름 처리에 사용한다. 체크포인트와 DB의 데이터 경로는 이번 정리로 변경하지 않는다.

- [사용자 흐름 실행·구현 안내](docs/user_flow.md)
- [DB 저장·대시보드 조회 형식](docs/contract.md)
- [실행 준비와 관리자 브랜치 후속 작업](docs/connection_work.md)
- [이전 구현 검증 기록과 제한](docs/validation.md)

`tests/`에는 현재 코드의 계산·실패 복구 검사와 운영에서 분리된 Kafka·Spark·MongoDB 통합 검사가 있다. 운영 이미지에는 포함하지 않는다. 과거 검증 기록과 이번 검사 결과를 구분한다.
