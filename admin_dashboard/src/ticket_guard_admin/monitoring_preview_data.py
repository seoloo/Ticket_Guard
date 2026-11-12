"""
[홍석환] 세 관점 관리자 시안의 고정 샘플 데이터
사용자 흐름의 확정 지표와 네트워크·이상탐지의 검토용 자료를 구성한다.
운영 DB와 QA 정답표를 사용하지 않는다.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone


def build_monitoring_preview() -> dict:
    end = datetime(2026, 11, 12, 15, tzinfo=timezone(timedelta(hours=9)))
    times = [(end - timedelta(minutes=30 * (24 - i))).isoformat() for i in range(25)]
    node_rows = [
        ("shows", "공연 목록", 80, 1500, 42, 35),
        ("detail", "상세·회차 선택", 100, 1300, 65, 54),
        ("queue", "대기열", 130, 1000, 84, 72),
        ("captcha", "보안문자", 60, 900, 18, 15),
        ("select", "좌석·수량 선택", 95, 810, 92, 78),
        ("complete", "예매 완료", 35, 620, 12, 10),
    ]
    nodes = [dict(id=id_, label=label, current=current, entered=entered,
                  mean=mean, median=median, samples=entered-current)
             for id_, label, current, entered, mean, median in node_rows]
    edges = [dict(source=left[0], target=right[0], numerator=right[3], denominator=left[3],
                  ratio=right[3]/left[3]) for left, right in zip(node_rows, node_rows[1:])]
    success = [20, 21, 22, 24, 25, 27, 26, 24, 22, 25, 28, 30, 29, 27, 25, 23, 21, 22, 24, 26, 28, 29, 27, 24, 23]
    success[12] += 620 - sum(success)
    presence = [260, 280, 310, 295, 330, 365, 350, 380, 410, 390, None, None,
                440, 420, 460, 490, 470, 510, 485, 465, 490, 520, 505, 480, 500]
    flow = {
        "current": sum(n["current"] for n in nodes), "starts": 1000, "completed": sum(success),
        "ratio": sum(success)/1000, "nodes": nodes, "edges": edges,
        "secondary": [dict(source="select", target="detail", kind="backward", label="뒤로 이동", count=24),
                      dict(source="captcha", target="captcha", kind="retry", label="재시도", count=36),
                      dict(source="queue", target="cancel", kind="cancel", label="취소", count=45)],
        "presence": [dict(at=t, value=v, observed=v is not None) for t, v in zip(times, presence)],
        "booking": [dict(at=t, value=n/40, numerator=n, denominator=40, observed=True) for t, n in zip(times, success)],
    }
    paths = [
        dict(path="/api/action/", requests=6200, errors=150, missing=50, browserMean=185, browserMedian=158, serverMean=110, serverMedian=94),
        dict(path="/captcha.png", requests=1800, errors=60, missing=20, browserMean=150, browserMedian=132, serverMean=90, serverMedian=78),
        dict(path="/detail/{공연}/", requests=1200, errors=20, missing=7, browserMean=132, browserMedian=118, serverMean=70, serverMedian=62),
        dict(path="/history/", requests=800, errors=10, missing=3, browserMean=165, browserMedian=144, serverMean=100, serverMedian=86),
    ]
    requests = [280 + (i*37)%230 for i in range(25)]
    requests[-1] += 10000-sum(requests)
    errors = [6 + i%8 for i in range(25)]
    errors[-1] += 240-sum(errors)
    network = dict(requests=10000, errors=240, missing=80,
                   browserMean=sum(row['browserMean']*row['requests'] for row in paths)/10000, browserMedian=143,
                   serverMean=100.8, serverMedian=88, paths=paths,
                   requestsSeries=[dict(at=t, value=v, observed=True) for t, v in zip(times, requests)],
                   errorsSeries=[dict(at=t, value=v, observed=True) for t, v in zip(times, errors)])
    kinds = [
        dict(id="burst", label="짧은 간격의 반복 요청", code="browser_request"),
        dict(id="replay", label="예매 확정 재전송", code="booking_confirm_replayed"),
        dict(id="captcha", label="보안문자 반복 실패", code="captcha_wrong"),
        dict(id="access", label="접근 거부 이후 요청", code="booking_access_rejected"),
        dict(id="expired", label="만료 이후 반복 요청", code="booking_confirm_rejected"),
    ]
    subjects = []
    for i in range(8):
        events = []
        for j in range(7 if i < 4 else 6):
            kind = kinds[(i+j%2)%len(kinds)]
            events.append(dict(at=(end-timedelta(minutes=i+1, seconds=50-j*6)).strftime("%H:%M:%S"),
                               kind=kind["id"], label=kind["label"], code=kind["code"],
                               detail="통신 실패와 재시도 가능성을 함께 확인해야 합니다." if kind["id"] == "replay" else "관측 이벤트를 바탕으로 행동 맥락을 확인합니다."))
        subjects.append(dict(id=f"VIEW-{i+1:03d}", attempt=f"ATT-{230+i}",
                             events=events, kinds=sorted({e["kind"] for e in events}), recent=events[-1]["at"]))
    counts = Counter(e["kind"] for subject in subjects for e in subject["events"])
    anomaly = dict(subjects=subjects, kinds=[k | {"count": counts[k["id"]]} for k in kinds],
                   total=sum(counts.values()))
    return dict(snapshot="2026.11.12 15:00 KST", flow=flow, network=network, anomaly=anomaly)
