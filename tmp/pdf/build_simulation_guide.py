from pathlib import Path
import ast, base64, hashlib, json, math
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.pagesizes import A4

ROOT=Path(r'C:/workspace/Ticket_Guard')
assert Path.cwd().resolve()==ROOT.resolve()
OUT=ROOT/'output/pdf/ticketguard-simulation-capture-kafka-guide.pdf'
TMP=ROOT/'tmp/pdf'
FILES=[
 ('static/app.js','행동 연결·중복 호출 정리'),('static/telemetry.js','브라우저 수집기 추가'),
 ('templates/base.html','수집기 선행 로드'),('web/views.py','수집 플래그·v1 호환'),
 ('web/capture_views.py','익명 v2 수신 API 추가'),('web/event_schema.py','v1/v2 검증'),
 ('web/events.py','구성·발행·분할·재조립'),('web/telemetry.py','본문 표현·마스킹·감사 내역'),
 ('web/middleware.py','서버 요청·응답·예외 관측'),('config/settings.py','수집 플래그·전송 한도'),
 ('config/urls.py','수집 API 경로 등록'),('compose.yml','수집 플래그 연결'),
 ('web/management/commands/consume_events.py','조각 소비·재조립 진단'),
 ('web/management/commands/verify_kafka.py','기존 Kafka 검증에 재조립 연결'),
 ('web/management/commands/verify_capture_kafka.py','원본 Kafka 왕복 검증 추가'),
 ('web/test_events.py','이벤트 회귀 갱신'),('web/test_capture.py','원본 수집 회귀 추가'),
 ('tests/capture-browser.cjs','헤드리스 브라우저 검사 추가'),('docs/telemetry.md','수집 계약·검증 이력'),('README.md','문서 진입 안내')]
SOURCES=[p for p,_ in FILES]+['web/tests.py','web/management/commands/init_kafka.py']
SNAPSHOT={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
(TMP/'source-snapshot.json').write_text(json.dumps(SNAPSHOT,indent=2),encoding='utf-8')
texts={p:(ROOT/p).read_text(encoding='utf-8-sig') for p in SOURCES}
# Static inspection only: no project imports, service calls or test execution.
counts={p:sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse(texts[p]))) for p in ('web/tests.py','web/test_events.py','web/test_capture.py')}
assert sum(counts.values())==56,counts
for marker in ('56개 통과','전송 레코드 46개','capture POST 68건'):
 assert marker in texts['docs/telemetry.md'],marker
for name in ('manage.py','Dockerfile','templates/components/progress.html','templates/components/poster.html'):
 assert (ROOT/name).is_file(),name

pdfmetrics.registerFont(TTFont('KR','C:/Windows/Fonts/malgun.ttf'))
pdfmetrics.registerFont(TTFont('KRB','C:/Windows/Fonts/malgunbd.ttf'))
pdfmetrics.registerFont(TTFont('Mono','C:/Windows/Fonts/consola.ttf'))
W,H=A4;M=44;CW=W-2*M
NAVY=colors.HexColor('#17324D');TEAL=colors.HexColor('#087E8B');INK=colors.HexColor('#233849');MUTED=colors.HexColor('#5C7080');LINE=colors.HexColor('#D6E1E9');PALE=colors.HexColor('#EFF6FA');WHITE=colors.white
c=canvas.Canvas(str(OUT),pagesize=A4)
c.setTitle('티켓가드 시뮬레이션 원본 수집 및 Kafka 전달 가이드')
c.setAuthor('Ticket Guard | 팀 공유 문서')
c.setSubject('실제 코드 확인·과거 검증 이력·Kafka 입력 및 출력 계약')
y=0;number=0;anchors=[]
STYLE={
 'body':ParagraphStyle('body',fontName='KR',fontSize=10,leading=16,textColor=INK,wordWrap='CJK'),
 'small':ParagraphStyle('small',fontName='KR',fontSize=8.3,leading=12.5,textColor=MUTED,wordWrap='CJK'),
 'cell':ParagraphStyle('cell',fontName='KR',fontSize=8.5,leading=12.6,textColor=INK,wordWrap='CJK'),
 'headcell':ParagraphStyle('headcell',fontName='KRB',fontSize=8.6,leading=12.6,textColor=NAVY,wordWrap='CJK'),
}
def check(h):
 if y-h<53:raise RuntimeError(f'Overflow page {number}: y={y:.1f}, block={h:.1f}')
def para(t,kind='body',gap=8,width=None):
 global y
 p=Paragraph(escape(t).replace('\n','<br/>'),STYLE[kind]);_,h=p.wrap(width or CW,H)
 check(h);p.drawOn(c,M,y-h);y-=h+gap

def section(t):
 global y
 check(25);c.setFillColor(TEAL);c.setFont('KRB',12);c.drawString(M,y-14,t);y-=25

def table(headers,rows,widths=None,small=False):
 global y
 widths=widths or [CW/len(headers)]*len(headers)
 def cell(x,head=False):return Paragraph(escape(str(x)).replace('\n','<br/>'),STYLE['headcell' if head else 'cell'])
 data=[[cell(x,True) for x in headers]]+[[cell(x) for x in row] for row in rows]
 t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DFEDF4')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,colors.HexColor('#F5F8FA')]),('LINEBELOW',(0,0),(-1,0),.7,LINE)]))
 _,h=t.wrap(CW,H);check(h);t.drawOn(c,M,y-h);y-=h+11

def note(t):
 global y
 p=Paragraph(escape(t).replace('\n','<br/>'),STYLE['body']);_,h=p.wrap(CW-24,H);h+=20
 check(h);c.setFillColor(PALE);c.roundRect(M,y-h,CW,h,6,fill=1,stroke=0);p.drawOn(c,M+12,y-h+10);y-=h+11

def code(t,size=8.25,leading=11):
 global y
 lines=t.strip('\n').splitlines();h=len(lines)*leading+18
 check(h);c.setFillColor(colors.HexColor('#F2F5F8'));c.roundRect(M,y-h,CW,h,5,fill=1,stroke=0)
 c.setFont('Mono',size);c.setFillColor(INK)
 for i,line in enumerate(lines):
  if pdfmetrics.stringWidth(line,'Mono',size)>CW-20:raise RuntimeError(f'Code too wide p{number}: {line}')
  c.drawString(M+10,y-12-i*leading,line)
 y-=h+10

def page(label,title,dek):
 global number,y
 if number:c.showPage()
 number+=1;c.bookmarkPage('p'+str(number));c.addOutlineEntry(title,'p'+str(number),level=0,closed=False)
 c.setFillColor(TEAL);c.rect(0,H-7,W,7,fill=1,stroke=0)
 c.setFont('KRB',8.5);c.setFillColor(TEAL);c.drawString(M,H-35,'TICKET GUARD / '+label)
 c.setFont('KRB',22);c.setFillColor(NAVY);c.drawString(M,H-67,title)
 y=H-86;para(dek,'small',gap=14)
 c.setStrokeColor(LINE);c.line(M,40,W-M,40)
 c.setFont('KR',7.5);c.setFillColor(MUTED);c.drawString(M,26,'팀 공유 | 실제 코드 기준 · 검증 이력 별도 표기 | 2026.11.05');c.drawRightString(W-M,26,f'{number:02d}')

def source(t):
 global y
 para('코드 근거: '+t,'small',gap=3)

def flow():
 global y
 h=225;check(h);top=y
 bw=(CW-24)/3;xs=[M,M+bw+12,M+2*(bw+12)]
 def box(x,top,w,h,title,sub,fill=PALE):
  c.setFillColor(fill);c.setStrokeColor(LINE);c.roundRect(x,top-h,w,h,6,fill=1,stroke=1)
  c.setFillColor(NAVY);c.setFont('KRB',9.5);c.drawCentredString(x+w/2,top-18,title)
  c.setFillColor(MUTED);c.setFont('KR',8);c.drawCentredString(x+w/2,top-33,sub)
 def arrow(x,a,b):
  c.setStrokeColor(TEAL);c.setLineWidth(1);c.line(x,a,x,b+4);c.line(x,b+4,x-3,b+8);c.line(x,b+4,x+3,b+8)
 for x,title,sub,title2,sub2 in zip(xs,['브라우저 관측','서버 업무 결과','Django HTTP'],['telemetry.js / app.js','services.py / views.py','middleware.py'],['수집 API','업무 이벤트 구성','서버 관측 구성'],['/api/capture/','build_event / emit','build_capture']):
  box(x,top,bw,46,title,sub);arrow(x+bw/2,top-46,top-65);box(x,top-65,bw,46,title2,sub2)
  arrow(x+bw/2,top-111,top-132)
 c.setStrokeColor(TEAL);c.line(xs[0]+bw/2,top-132,xs[2]+bw/2,top-132);arrow(M+CW/2,top-132,top-148)
 box(M+20,top-148,CW-40,32,'EventDispatcher → KafkaEventPublisher','',WHITE)
 arrow(M+CW/2,top-180,top-194)
 c.setFillColor(NAVY);c.roundRect(M+50,top-222,CW-100,28,5,fill=1,stroke=0);c.setFillColor(WHITE);c.setFont('KRB',10);c.drawCentredString(W/2,top-212,'Kafka : ticketguard.events.v1')
 y-=h+10

page('01 / PURPOSE & FLOW','수집을 먼저, 정제는 이후에','시뮬레이션 원본 수집 및 Kafka 전달 가이드 | 현재 구현을 팀원이 따라가기 위한 문서')
note('접근 가능한 원본을 폭넓게 확보하고, 분석용 필드 선택·제외·정제는 이후 Spark에서 수행한다. 지금은 기존 와이어프레임 위에 기본 수집 경로를 추가하는 단계다.')
para('구현 기준은 C:/workspace/Ticket_Guard다. 이번 문서는 해당 코드와 docs/telemetry.md만 확인했다. 다른 사본·이전 PDF를 구현 근거로 사용하지 않았다. 테스트·서비스·DB·Spark는 실행하지 않았다.')
section('세 출발점, 하나의 Kafka 전달 경로')
flow()
table(['변경 전','현재'],[
 ('선별된 통신·성능 메타데이터 중심','접근 가능한 본문·쿼리·헤더·추가 필드까지 보존'),
 ('헤더 허용 목록, 길이·항목 수 제한','비밀값 예외를 제외한 임의 선별·무표시 잘림 제거'),
 ('브라우저 로그인 화면 수집 제외','익명 수집과 로그인 후 흐름 연결'),
 ('새 큐에도 100개·15분 제한 적용 가능성','새 tg-capture-v2 큐의 해당 자동 잘림·삭제 제거')],[CW/2,CW/2])
para('기존 로그인·관리자 접근·공개 공연 목록·예매 기능은 보존 대상이다. DB·Spark의 추가 구현과 운영용 전체 시스템 설계는 이번 범위에 포함하지 않는다.','small')

page('02 / CAPTURE INVENTORY','무엇을 관측하는가','수집 위치·주요 필드·표현·한계를 함께 읽는다. 접근할 수 없는 정보는 값이 0인 정보와 다르다.')
table(['영역 / 위치','주요 필드·표현','제한 / 해석'],[
 ('명시적 행동\napp.js','page_enter/exit, 검색·장르·공연·일정·좌석·인원과 추가 details','정상 행동 이벤트를 유지하고 잘못된 중복 호출을 정리'),
 ('일반 UI\ntelemetry.js','click/submit/change의 tagName, id, name, inputType, href/action, dataset, value','모든 키 입력·DOM 전체 덤프는 아님'),
 ('로그인 전후\n수집 API','익명 ID, 세션 userId, 탭·화면 ID','수신 시 세션을 기준으로 사용자 결정. 익명 ID는 인증 자격이 아님'),
 ('fetch / XHR\n브라우저','URL·메서드·접근 가능한 헤더·본문·옵션, 응답 상태·본문·시간','원래 요청을 재전송하지 않고 복사. 자동 추가 헤더 전체는 비공개일 수 있음'),
 ('JSON·폼·파일\n브라우저/서버','JSON 값·text, 중복 name/value, multipart 파일 정보, Base64','파싱·재직렬화·문자코드·바이너리 변환을 표시'),
 ('리소스·페이지 성능\nPerformance API','지원 entryType의 entry.toJSON() 전체, 중첩 serverTiming 등','브라우저 지원·버퍼·외부 출처 정책에 따라 제한'),
 ('브라우저 오류\n이벤트 리스너','message, Error 속성·stack, 파일·줄·열, rejection, resourceUrl','외부 스크립트 오류 상세는 제한될 수 있음'),
 ('Django 요청·응답\n미들웨어','중복 쿼리, 노출 헤더, 본문, 프로토콜·원격 주소, 응답·예외','Django를 통과하는 요청만 관측. wire 바이트와 동일하지 않음'),
 ('페이지 생명주기\n브라우저','collector_ready, pageshow/hide, visibilitychange와 URL','수집기 실행 이전 정보·종료 직전 미완료 본문은 복원 불가')],[101,218,CW-319])
section('자동 리소스 요청과 본문은 다르다')
para('이미지·CSS·JS·폰트의 Resource Timing 관측은 가능하지만, 그것만으로 해당 파일의 응답 본문을 읽는 것은 아니다. 서버 관측은 Django를 거친 경우에만 본문을 볼 수 있다. 모든 HAR 필드·파일 본문을 수집했다고 표현하지 않는다.')
source('static/app.js, static/telemetry.js, web/middleware.py, web/telemetry.py')

page('03 / FILE RESPONSIBILITIES','어느 파일이 무엇을 처리하는가','파일을 읽는 순서: 브라우저 생성 → 수신 API → 정리·검증 → 이벤트 구성·Kafka 발행')
table(['파일 / 주요 함수','입력 → 처리 → 출력'],[
 ('static/app.js\nevent()','화면 행동 → 명시적 업무 details·문맥 → ticketGuardCapture.record()'),
 ('static/telemetry.js\nrecord / body / flush','브라우저 관측 → 복사·마스킹·표현 → 큐·/api/capture/ 전송'),
 ('web/capture_views.py\ncapture()','익명/로그인 JSON → ID·시각·구조 확인 → build_capture·접수 상태'),
 ('web/views.py\naction / events / page','기존 업무 처리와 v1 수신 유지. 템플릿에 capture_enabled 전달'),
 ('web/telemetry.py\nsanitize_capture / body_snapshot','관측값·본문 → 비밀값 처리·표현 변환 → 데이터와 audit'),
 ('web/event_schema.py\nvalidate_event / validate_capture_event','v1/v2 봉투·필드·자료형 → 검증 → JSON UTF-8 바이트'),
 ('web/middleware.py\nRequestTelemetryMiddleware','Django 요청·응답·예외 → 복사·X-Request-ID → 서버 v2 관측'),
 ('web/events.py\nbuild_event / build_capture','업무/관측 details → 기본값·시각·문맥·audit → 공통 이벤트'),
 ('web/events.py\nEventDispatcher / KafkaEventPublisher','이벤트 → 중복·접수 상태·분할·produce → 전달 콜백'),
 ('web/events.py\ntransport_records / CaptureReassembler','큰 v2 ↔ capture_chunk 목록. 진단용 재조립·무결성 확인')],[202,CW-202])
section('설정·진단·기존 기능 경계')
para('base.html은 telemetry.js를 app.js보다 먼저 defer 로드한다. settings.py·urls.py·compose.yml은 플래그·수집 경로·환경을 연결한다. consume_events는 재조립/원조각 진단, verify_kafka와 verify_capture_kafka는 검증 명령이다.')
para('기존 관리자 로그인·공개 목록·메인 hover·예매 동작과 수집 API는 구분한다. 전체 파일 절대 경로는 부록 A에 있다. init_kafka.py는 설정 근거로 읽었으며 이번 수집 확장에서는 변경하지 않았다.','small')

page('04 / ENVELOPE & IDS','v1·v2와 식별자 연결','토픽 이름의 v1과 이벤트 내부 schemaVersion을 혼동하지 않는다.')
table(['구분','현재 동작'],[
 ('업무 v1','기존 공통 봉투·알려진 업무 필드 검증 유지. 추가 details 필드는 보존'),
 ('관측 v2','기존 공통 필드 + capture. 새 이벤트 이름·확장 details를 수용'),
 ('업무의 v2 전환','마스킹 발생, 새로운 이벤트 이름, 직렬화 크기 16KB 초과 시 build_event가 v2로 구성')],[111,CW-111])
table(['공통 필드','역할'],[
 ('schemaVersion / eventId / eventType','구조 버전 / 개별 이벤트 ID / 행동·관측 종류'),
 ('occurredAt / receivedAt','발생 시각 / 서버 이벤트 구성 시각. UTC 문자열'),
 ('source / userId','browser 또는 server / 서버가 수신 시 정한 사용자 또는 null'),
 ('pageInstanceId / pageViewId','탭 / 개별 화면 조회 연결'),
 ('bookingAttemptId / requestSequence','예매 흐름 / 업무 요청 순서. 없으면 null'),
 ('showId / scheduleId','관련 공연 / 회차. 문맥이 없으면 null'),
 ('result / errorCode','결과 / 오류 코드. HTTP 실패·접근 불가는 details도 함께 해석'),
 ('isSimulation / scenarioName','개발 시나리오 문맥. 시뮬레이션 앱의 모든 기록이 true라는 뜻은 아님'),
 ('details / capture(v2)','원본 관측 영역 / 처리·제한·출처에 대한 감사 정보')],[197,CW-197])
section('두 관측을 연결하는 ID')
para('브라우저 details.requestId는 start/body/headers/완료 단계 사이를 연결한다. 응답 X-Request-ID를 읽은 details.serverRequestId는 서버 details.requestId와 일치한다. 브라우저 자체 requestId와 서버 requestId는 별개다.')
note('동일 요청의 브라우저·서버 관측은 서로 다른 이벤트로 보존한다. 같은 이름이라도 source=browser인 이벤트를 서버 업무 성공으로 신뢰하지 않는다.')
source('web/event_schema.py, web/events.py, web/capture_views.py, web/middleware.py')

seat={
 'schemaVersion':2,'eventId':'11111111-1111-4111-8111-111111111111','eventType':'seat_select',
 'occurredAt':'2026-11-05T02:26:41.809Z','receivedAt':'2026-11-05T02:26:41.850+00:00',
 'userId':'example-user','bookingAttemptId':'33333333-3333-4333-8333-333333333333',
 'pageInstanceId':'44444444-4444-4444-8444-444444444444','pageViewId':'55555555-5555-4555-8555-555555555555',
 'showId':'blue-hour','scheduleId':'blue-hour-evening','requestSequence':None,'result':'success','errorCode':None,
 'source':'browser','isSimulation':False,'scenarioName':None,
 'details':{'seatId':'D7','selectedCount':1},
 'capture':{'status':'complete','collectorVersion':'2.0','policyVersion':'simulation-raw-1',
 'anonymousId':'66666666-6666-4666-8666-666666666666','redactions':[],'transformations':[],
 'limitations':[],'failures':[],'truncations':[],'observer':{'status':'complete'}}}
fields=next(ast.literal_eval(n.value) for n in ast.parse(texts['web/event_schema.py']).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FIELDS' for t in n.targets))
assert set(seat)==fields|{'capture'}
(TMP/'seat-example.json').write_text(json.dumps(seat,ensure_ascii=False,indent=2),encoding='utf-8')
page('05 / EXAMPLE 1','예시 1. 좌석 선택의 전체 봉투','설명용 JSON 예시 · 실측값 아님 · v2의 필수 최상위 필드를 모두 포함')
seat_code='''{
  "schemaVersion": 2,
  "eventId": "11111111-1111-4111-8111-111111111111",
  "eventType": "seat_select", "source": "browser",
  "occurredAt": "2026-11-05T02:26:41.809Z",
  "receivedAt": "2026-11-05T02:26:41.850+00:00",
  "userId": "example-user",
  "bookingAttemptId": "33333333-3333-4333-8333-333333333333",
  "pageInstanceId": "44444444-4444-4444-8444-444444444444",
  "pageViewId": "55555555-5555-4555-8555-555555555555",
  "showId": "blue-hour", "scheduleId": "blue-hour-evening",
  "requestSequence": null, "result": "success", "errorCode": null,
  "isSimulation": false, "scenarioName": null,
  "capture": {
    "status": "complete", "collectorVersion": "2.0",
    "policyVersion": "simulation-raw-1",
    "anonymousId": "66666666-6666-4666-8666-666666666666",
    "redactions": [], "transformations": [], "limitations": [],
    "failures": [], "truncations": [],
    "observer": {"status": "complete"}
  },
  "details": {"seatId": "D7", "selectedCount": 1}
}'''
assert json.loads(seat_code)==seat
code(seat_code,size=8.6,leading=12)
section('capture를 읽는 순서')
para('redactions는 마스킹 위치·사유, transformations는 파싱·재인코딩 등의 변경을 설명한다. limitations와 failures는 접근 제한·관측 실패다. truncations는 잘림 표시 영역이며, 현재 코드가 임의 길이 제한을 수행한다는 뜻은 아니다.')
para('capture.observer는 브라우저가 보고한 관측 내역이다. 서버가 별도로 확인한 사실과 혼동하지 않는다. 이 예시에서는 설명을 위해 observer를 간단한 유효 객체로 구성했다.')
para('추가 좌석 정보나 새로운 details 필드를 보내도 분석상 불필요하다는 이유로 버리지 않는다. 다만 JSON 직렬화·봉투 구조와 v1의 알려진 업무 필드 규칙은 계속 검증한다.','small')
source('static/app.js의 event(), web/capture_views.py, build_capture(), validate_capture_event()')

page('06 / EXAMPLE 2','예시 2. 요청을 양쪽에서 관측','두 JSON 모두 설명용이며 일부 공통·본문 필드를 생략했다. 동일 요청을 재전송한 것이 아니다.')
section('브라우저: fetch 완료 관측의 일부')
code('''{
  "schemaVersion": 2, "source": "browser",
  "eventType": "browser_request",
  "details": {
    "requestId": "77777777-7777-4777-8777-777777777777",
    "serverRequestId": "88888888-8888-4888-8888-888888888888",
    "transport": "fetch",
    "request": {
      "url": "/api/action/?q=music&q=live", "method": "POST",
      "body": {"state":"captured", "representation":"json",
               "value":{"action":"confirm","seats":["D7"],"quantity":1}}
    },
    "response": {"status":200, "body":{"state":"captured"}}
  }
}''',size=8.4,leading=11)
section('서버: 같은 요청의 HTTP 관측 일부')
code('''{
  "schemaVersion": 2, "source": "server",
  "eventType": "server_request",
  "details": {
    "requestId": "88888888-8888-4888-8888-888888888888",
    "request": {
      "url":"/api/action/?q=music&q=live", "method":"POST",
      "query":[{"name":"q","value":"music"},{"name":"q","value":"live"}]
    },
    "response": {"status":200, "body":{"state":"captured"}},
    "timing": {"headersReadyMs":5.2, "observationDurationMs":5.8}
  }
}''',size=8.4,leading=11)
para('브라우저 serverRequestId = 서버 requestId. eventId는 관측별로 다르다. 브라우저에는 요청 시작·본문·응답 헤더·완료 이벤트가 별도로 남을 수 있으므로 요청 건수를 단순 이벤트 수로 계산하지 않는다.')
para('headersReadyMs는 해당 관측자의 헤더 시점까지다. 서버 시간은 네트워크 왕복과 다르며, 브라우저 bodyObservedMs는 복사본 읽기까지 포함한다.','small')

page('07 / PRESERVATION POLICY','원본 복사본과 처리 내역','원래 업무 요청·응답은 유지하고, 수집용 복사본에 인증 비밀값 처리를 적용한다.')
table(['표현','보존 내용 / 변환'],[
 ('JSON','파싱한 value와 text 복사본. 마스킹 시 text도 재직렬화하며 변환 표시'),
 ('텍스트','문자열·가능한 charset·원래 크기. 인증값 교체 시 동일 바이트 원본이 아님'),
 ('URL encoded form','중복 name/value 배열과 가능한 text 복사본'),
 ('multipart / 파일','필드·파일 정보·본문 표현. wire boundary를 그대로 재현하지 않음'),
 ('바이너리','Base64·byte 수. 알려진 인증값 교체 가능. Base64는 암호화가 아님')],[118,CW-118])
section('상태는 세 층으로 구분')
para('capture.status의 complete는 수행한 관측의 정리 상태다. redacted는 비밀값 처리, partial은 제한·실패가 있음을 뜻한다. 모든 네트워크 정보의 완전 수집이나 전달 성공을 뜻하지 않는다.')
table(['본문 state','해석'],[
 ('captured / redacted','본문 확보 / 수집 복사본의 일부 인증값 처리'),
 ('pending','본문 관측 진행 중. 시작·헤더 기록에 사용'),
 ('empty / not_applicable','실제 빈 본문 / 본문이 없거나 비해당'),
 ('unavailable','정책·API·소비 방식 제약으로 접근 불가. reason 확인'),
 ('failed / partial','관측 실패 / 일부 확보 또는 스트림 미완료')],[145,CW-145])
section('인증 비밀값 예외와 재귀 제외')
para('비밀번호·Cookie/Set-Cookie·Authorization·CSRF·API key·인증 token·보안문자 답은 [REDACTED]와 위치·사유를 남긴다. 비민감 쿼리·fragment·일반 헤더는 보존한다. /captcha.png 인증 challenge 이미지 본문은 unavailable로 표시한다.')
para('/api/events/, /api/capture/, /health/의 자체 수집·조회·재시도는 재귀 기록하지 않는다. 비밀값 탐지는 이름·표현·알려진 값 기반이며, 알 수 없는 바이너리 속 의미적 비밀을 완벽히 찾는 기능은 아니다.','small')
source('web/telemetry.py, static/telemetry.js, web/middleware.py')

page('08 / KAFKA CONFIG & DELIVERY','Kafka는 보관·전달을 담당한다','JSON 내부를 분석·정제하지 않는다. 아래는 코드·초기화 기본값이며 실행 중 설정을 이번에 조회하지 않았다.')
table(['항목','코드 기준 값 / 의미'],[
 ('topic / schema','ticketguard.events.v1 안에 value의 v1·v2·capture_chunk가 함께 존재'),
 ('연결 / 모드','kafka:9092(Compose 내부). Compose 기본 kafka, settings.py 로컬 기본 mock'),
 ('key','bookingAttemptId → userId → capture.anonymousId → eventId'),
 ('value','검증한 JSON UTF-8 바이트. 큰 v2는 분할 후 각 봉투도 JSON 바이트'),
 ('전달 보장 설정','enable.idempotence=true, acks=all, retries=3. end-to-end exactly-once 아님'),
 ('파티션 / 복제','초기화 요청: 3 partitions / RF=1 / min.insync.replicas=1'),
 ('보존 / 세그먼트','delete, 7일·파티션당 256MiB 기준, 세그먼트 64MiB·1시간'),
 ('설정 적용 주의','기존 토픽은 init_kafka가 자동 덮어쓰지 않고 차이를 보고. 상세값은 부록 B')],[139,CW-139])
section('접수·관측 상태와 Kafka 전달 상태는 별개')
table(['상태','의미 / 처리'],[
 ('accepted','발행 접수 여부. 브로커·DB 저장 완료와 다름'),
 ('pending','비동기 전송 중. 보통 HTTP 202'),
 ('delivered','모든 전송 레코드 callback 성공. 보통 HTTP 200. DB 저장 완료 아님'),
 ('failed','발행 실패. retryable·attempts·errorCode에 따라 재시도 또는 보존'),
 ('rejected','CSRF·형식·HTTP 크기 등 거부. 브라우저가 레코드를 보존·오류 표시')],[107,CW-107])
para('브라우저는 같은 eventId로 재시도하고, 전달 성공 후 큐에서 제거한다. terminal 실패·거부는 유지한다. 서버 emit은 best effort이며 영속 outbox는 없다. topic·key만으로 전체 사용자·여러 Producer의 실제 발생 순서를 보장하지 않는다.','small')
source('KafkaEventPublisher, EventDispatcher, config/settings.py, compose.yml, init_kafka.py')

large=dict(seat);large['eventId']='99999999-9999-4999-8999-999999999999';large['eventType']='future_observation';large['details']={'text':'x'*20000}
raw=json.dumps(large,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode();chunk_count=math.ceil(len(raw)/8192);digest=hashlib.sha256(raw).hexdigest()
page('09 / OUTPUT & EXAMPLE 3','소비자가 받는 값과 분할 레코드','설명용 예시 · callback metadata와 Consumer가 읽는 본문을 구분한다.')
table(['레코드 필드','소비 측 자료형 예시','역할'],[
 ('key / value','Binary / Binary','UTF-8 key / JSON 바이트'),('topic / partition','String / Integer','토픽 / 저장 파티션'),
 ('offset','Long','파티션 내 위치. topic+partition+offset으로 레코드 식별'),
 ('timestamp / timestampType','Timestamp / Integer','Kafka 레코드 시각 / 유형. occurredAt과 별개')],[130,132,CW-262])
para('성공 콜백은 단건이면 {topic, partition, offset}, 분할이면 {recordId, chunks:[각 조각 메타데이터]}를 반환한다. chunks 배열은 callback 완료 순서일 수 있으므로 본문 재조립은 details.index를 사용한다.','small')
section('예시 3. 큰 v2의 조각 한 개: 일부 필드 생략')
chunk_example={"schemaVersion":2,"eventType":"capture_chunk","details":{"recordId":large['eventId'],"index":0,"count":chunk_count,"encoding":"base64-json-utf8","totalBytes":len(raw),"sha256":digest,"data":"<omitted for display>"}}
code(json.dumps(chunk_example,indent=2),size=8.25,leading=11)
para('위 예시는 표시용으로 data와 공통 필드를 생략했으므로 직접 재조립할 수 없다. 실제 원본 JSON 바이트는 기본 8,192바이트씩 나뉘고, 각 Kafka 레코드는 16,384바이트 한도를 확인한다.','small')
section('소비 순서')
para('① eventType이 capture_chunk인지 구분 → ② recordId별 index 조각 모음 → ③ Base64 디코딩·index 순 결합 → ④ totalBytes·SHA-256 확인 → ⑤ JSON 해석·원본 eventId 확인')
para('모든 조각은 원본의 동일 key를 사용한다. 조각 eventId는 원본 ID+index의 UUID5다. 재시도 중복은 recordId/index로 처리한다. 한 논리 이벤트가 여러 offset을 가지며, 진단 재조립 출력의 단일 offset은 마지막 수신 조각 위치일 수 있다.','small')
source('transport_records(), CaptureReassembler.feed(), consume_events.py')

page('10 / EVIDENCE & LIMITS','검증 이력과 남아 있는 한계','아래 실행 결과는 직전 구현 작업의 기록이다. 이번 PDF 작성 중 재실행하지 않았다.')
table(['검증 구분','기록된 결과'],[
 ('회귀 / mock','전체 web 56개 통과. 현재 테스트 메서드 정적 집계도 22+14+20=56개. 실행 결과 자체를 재검증한 것은 아님'),
 ('문법·형식','app.js·telemetry.js의 node --check와 git diff --check 통과 이력'),
 ('실제 개발 Kafka / 신규','논리 2개·전송 46개, 한글 120,000자 재조립 일치. 익명→로그인 후 재시도·추가 필드·마스킹 확인'),
 ('실제 개발 Kafka / 기존','기존 예매·재확정 등 업무 흐름 17개 이벤트 확인'),
 ('별도 실제 Chrome','로그인 전후·fetch/XHR/Request 복사·본문·쿼리·성능·오류·중첩 toJSON 확인. 한글 24,000자 보존'),
 ('브라우저 최종 기록','POST 68건 / 현재 화면 delivered 62건. 거부·저장·직렬화 실패·페이지 오류 0, 종료 전 큐 비움')],[134,CW-134])
para('화면 전환마다 diagnostics가 새로 생성되므로 전체 POST 수와 한 화면 delivered 수는 같지 않다. 이번 코드 확인은 docs/telemetry.md의 이력을 뒷받침하는 구조 확인이며 현재 실행 상태·성능 보장은 아니다.','small')
section('세 종류의 미완료·제한을 구분')
table(['분류','내용'],[
 ('기술적 접근 제한','외부 비공개·opaque 본문/헤더, 자동 리소스 본문, TCP/TLS·DevTools 전용 정보'),
 ('전용 계측 미구현','Worker·다른 iframe·WebSocket/EventSource 메시지 본문 등'),
 ('추가 실행 검증 필요','강제 종료·실제 quota 고갈·무한 스트림·대량 사용자·Kafka 실제 중단 복구·게이트웨이 경유 한도')],[145,CW-145])
para('HTTP 한계·메모리·저장 quota는 남아 있다. 문서에 기록된 상속 기본값은 Django 2.5MiB, Nginx 경유 시 1MiB이며 이번에 운영값을 조회하지 않았다. 원본 복사 중 종료되면 시작/헤더만 남을 수 있다. 서버 영속 outbox가 없어 유실 가능하며 “모든 데이터 완전 수집”·“유실 없음”으로 표현하지 않는다.','small')

page('APPENDIX A / FILE INDEX','부록 A. 실제 파일 절대 경로','수집 변경 파일 목록은 docs/telemetry.md의 이력과 현재 파일 존재·내용을 대조했다. 이번 PDF 작업은 이 파일들을 수정하지 않았다.')
rows=[]
for i,(name,role) in enumerate(FILES,1):rows.append((f'{i:02d}',str(ROOT/name).replace('\\','/'),role))
table(['번호','절대 경로','역할'],rows,[36,328,CW-364])
para('추가 설정 근거(수집 확장에서 변경하지 않음):\nC:/workspace/Ticket_Guard/web/management/commands/init_kafka.py\n테스트 정적 집계 근거: C:/workspace/Ticket_Guard/web/tests.py','small')
para('작성 시 위 파일들의 SHA-256을 tmp/pdf/source-snapshot.json에 기록했다. 산출 후 동일성을 확인하여 문서 작성 중 애플리케이션 파일이 바뀌지 않았는지 점검한다.','small')

page('APPENDIX B / PARAMETERS','부록 B. 코드 기준 설정값','실행 중 브로커·컨테이너 설정을 이번에 조회하지 않았다. 환경변수·기존 토픽 상태에 따라 실제 값은 다를 수 있다.')
table(['Producer 파라미터','기본값','역할'],[
 ('bootstrap.servers','kafka:9092','Compose 내부 연결'),('client.id','ticketguard-web-PID','프로세스 식별'),
 ('enable.idempotence / acks','true / all','재전송 중복 억제 / ISR 확인'),('retries','3','라이브러리 전송 재시도'),
 ('max.in.flight.requests.per.connection','5','연결당 동시 요청'),('message.timeout.ms','5000','전체 메시지 전달 제한시간'),
 ('request.timeout.ms / socket.timeout.ms','2000 / 3000','브로커 응답 / 소켓 제한시간'),('retry.backoff.ms / linger.ms','250 / 10','재시도 간격 / 배치 대기'),
 ('queue.buffering.max.messages','2000','Producer 큐 개수'),('queue.buffering.max.kbytes','8192','Producer 큐 약 8MiB'),
 ('allow.auto.create.topics / log_level','false / 3','자동 토픽 생성 방지 / 로그 수준')],[244,95,CW-339])
table(['토픽 초기화 요청값','값'],[
 ('partitions / replication_factor / min.insync.replicas','3 / 1 / 1'),('cleanup.policy','delete'),
 ('retention.ms / retention.bytes','604800000(7일) / 268435456(파티션당 256MiB)'),
 ('segment.bytes / segment.ms','67108864(64MiB) / 3600000(1시간)')],[254,CW-254])
table(['앱·큐 파라미터','현재 코드'],[
 ('CAPTURE_ENABLED','기본 1. 템플릿·수집 API·미들웨어 관측 제어'),
 ('CAPTURE_KAFKA_RECORD_BYTES','16384. 조각 원본은 wire_limit // 2 = 8192바이트'),
 ('EVENT_RECEIPT_MAX / TTL / MAX_ATTEMPTS','2000 / 900초 / 3'),
 ('브라우저 flush / 네트워크 backoff','1초 주기 / 실패 시 지수 대기, 최대 30초'),
 ('브라우저 저장 / 종료 전송','memory+sessionStorage, keepalive는 본문 60000바이트 미만에서만 사용')],[254,CW-254])
para('진단 records deque 1,000개·사용자 최근 조회 100개는 Kafka 원본 보존 정책과 다르다. 새 브라우저 큐에는 100개·15분 자동 삭제를 적용하지 않는다. 전송 후 Kafka 데이터는 보존 정책에 의해 제거될 수 있다.','small')

page('APPENDIX C / COMMANDS','부록 C. 확인 방법과 근거','아래 명령은 팀의 후속 검증용 안내다. 이번 PDF 작성에서는 실행하지 않았다.')
section('회귀·문법·실제 Kafka 확인')
code('''docker exec -e EVENT_PUBLISHER=mock ticket-guard-web-1 \
  python manage.py test web -v 1
node --check static/app.js
node --check static/telemetry.js

docker exec ticket-guard-web-1 \
  python manage.py verify_capture_kafka
docker exec ticket-guard-web-1 \
  python manage.py verify_kafka''',size=8.3,leading=12)
para('위 코드의 줄바꿈은 표시용이다. PowerShell에서는 각 docker exec 명령을 한 줄로 입력한다. verify_capture_kafka·verify_kafka는 개발 Kafka에 테스트 이벤트를 발행하므로 단순 조회 명령이 아니다.','small')
section('소비·재조립 진단')
code('''docker exec ticket-guard-web-1 python manage.py consume_events
  --group ticketguard-debug-team-review
  --max-messages 10 --timeout 20 --from-beginning

# --raw-chunks : print transport chunks without reassembly''',size=8.3,leading=12)
para('첫 세 줄은 한 명령이다. 진단 소비자는 offset을 커밋하지 않는다. 재조립 중 미완료 레코드 수를 출력한다. 출력값에는 사용자 데이터가 포함될 수 있다.','small')
section('브라우저 검사와 런타임 상태')
code('''$env:PLAYWRIGHT_MODULE = '<installed playwright module path>'
$env:CHROME_PATH = '<installed Chrome executable path>'
node tests/capture-browser.cjs

window.ticketGuardCapture.inspect()
window.ticketGuardCapture.diagnostics
window.ticketGuardCapture.retry()''',size=8.3,leading=12)
para('마지막 세 줄은 브라우저 Console에서 사용한다. retry()는 거부/실패 레코드를 같은 ID로 다시 시도하며 서버 terminal 접수 TTL·재시도 제한을 해제하지는 않는다. 저장 quota 실패 시 메모리에 남아 있더라도 탭 강제 종료 후 보존은 보장되지 않는다.','small')
section('근거와 남은 불확실성')
para('설명 근거: 현재 소스와 docs/telemetry.md. 과거 실행 수치는 문서에 남은 기록이며 별도 결과 로그 파일을 새로 만들거나 재실행하지 않았다. 실행 중 토픽 설정·HTTP 배포 한계·브라우저별 지원 범위는 이번 문서에서 확인하지 않았다. DB·Spark는 출력 계약 설명에만 포함했다.','small')

# Check static application files have not changed during documentation generation.
assert SNAPSHOT=={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
c.save()
(TMP/'document-check.json').write_text(json.dumps({'pages':number,'sourceFiles':len(SNAPSHOT),'sourceUnchanged':True,'staticTestMethodCounts':counts,'applicationTestsRun':False,'serviceCallsMade':False,'output':str(OUT)},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'output':str(OUT),'pages':number,'sourceUnchanged':True},ensure_ascii=False))
