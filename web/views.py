import io
import json
import random
import secrets
import time
from datetime import datetime, timezone
from uuid import UUID
from django.conf import settings
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import render, redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.cache import never_cache
from PIL import Image, ImageDraw, ImageFont
from .services import repo, SHOWS, FlowError
from .events import emit, publisher, CLIENT_EVENTS

ADMIN_HOME_URL = '/qa/'  # 팀 입구(nginx)가 QA 대시보드로 넘김


def health(request):
    return JsonResponse({'status': 'ok', 'mode': 'phase-1-mock'})


def stage_url(a):
    if a['stage'] == 'complete':
        return '/complete/' + a['booking_id'] + '/'
    if a['stage'] in ('queue', 'captcha', 'select'):
        return '/' + a['stage'] + '/'
    return '/detail/' + a['show_id'] + '/'


def snapshot(a):
    return dict(id=a['id'], stage=a['stage'], redirect=stage_url(a),
                rank=max(1, a['rank'] - int((time.monotonic()-a['entered']) * 10)),
                wait=max(0, int(settings.QUEUE_WAIT_SECONDS-(time.monotonic()-a['entered']))),
                wrong=a['wrong'], sequence=a['sequence'], sold=sorted(repo.sold), remaining=repo.remaining)


@never_cache
@ensure_csrf_cookie
def page(request, screen, identifier=None):
    if screen not in {'login', 'signup', 'shows', 'detail', 'queue', 'captcha', 'select', 'complete', 'history'}:
        raise Http404
    user = request.session.get('user')
    # The show listing is the public landing page.  Guests can browse it;
    # starting a booking and all subsequent steps still require a login.
    if not user and screen not in {'login', 'signup', 'shows'}:
        return redirect('/login/')
    if user and screen in {'login', 'signup'}:
        return redirect(ADMIN_HOME_URL if request.session.get('role') == 'admin' else '/')
    context = dict(screen=screen, user=user, scenarios=settings.SHOW_SCENARIOS,
                   demo_user=settings.DEMO_USERNAME, genres=['전체', '콘서트', '뮤지컬', '연극', '페스티벌'])
    with repo.lock:
        try:
            if screen == 'shows':
                query, genre = request.GET.get('q', '')[:100], request.GET.get('genre', '전체')
                context.update(query=query, genre=genre, shows=[s for s in SHOWS.values()
                    if (not query or query.casefold() in (s['title'] + s['venue']).casefold())
                    and (genre == '전체' or s['genre'] == genre)], featured_shows=list(SHOWS.values())[:5])
            elif screen == 'detail':
                if identifier not in SHOWS:
                    raise Http404
                context.update(show=SHOWS[identifier], opens_at=int(repo.opens_at(user, identifier)*1000))
            elif screen in ('queue', 'captcha', 'select'):
                a = repo.current(user)
                if a['stage'] != screen:
                    return redirect(stage_url(a))
                context.update(show=SHOWS[a['show_id']], attempt_id=a['id'], sequence=a['sequence'],
                               rank=a['rank'], wrong=a['wrong'], remaining=repo.remaining,
                               rows=[dict(label=r, seats=[dict(id=f'{r}{c}', number=c, sold=f'{r}{c}' in repo.sold)
                                     for c in range(1, 11)]) for r in 'ABCDEFGHIJ'])
            elif screen == 'complete':
                b = repo.booking(user, identifier)
                context.update(booking=b, show=SHOWS[b['show_id']])
            elif screen == 'history':
                context['bookings'] = [dict(b, show=SHOWS[b['show_id']]) for b in repo.history(user)]
        except FlowError as e:
            if e.status == 404:
                raise Http404
            return redirect(e.redirect or '/')
    context['progress'] = [{'label': label, 'status': 'done' if i < {'queue': 1, 'captcha': 2, 'select': 3, 'complete': 5}.get(screen, 0)
                            else 'active' if i == {'queue': 1, 'captcha': 2, 'select': 3}.get(screen, -1) else ''}
                           for i, label in enumerate(['공연 선택', '접속 대기', '보안 확인', '좌석/인원 선택', '예매 완료'])]
    return render(request, 'page.html', context)


def is_admin_login(username, password):
    if not settings.DEMO_ADMIN_PASSWORD:
        return False
    return username == settings.DEMO_ADMIN_USERNAME and secrets.compare_digest(password, settings.DEMO_ADMIN_PASSWORD)


@require_GET
@never_cache
def check_admin(request):
    """팀 입구(nginx)가 /qa/ 요청마다 묻는 주소 · 관리자면 200 + X-Admin-User"""
    if request.session.get('role') != 'admin':
        return HttpResponse(status=401)
    response = HttpResponse(status=200)
    response['X-Admin-User'] = request.session['user']
    return response


def read_body(request):
    if len(request.body) > 16384:
        raise FlowError('요청이 너무 커요.')
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeDecodeError):
        raise FlowError('요청 형식이 올바르지 않아요.')


@require_POST
@never_cache
def action(request):
    try:
        data = read_body(request)
        command = data.get('action')
        if command == 'login':
            username, password = data.get('username', ''), data.get('password', '')
            if not isinstance(username, str) or not isinstance(password, str):
                raise FlowError('아이디와 비밀번호를 확인해 주세요.')
            is_admin = is_admin_login(username, password)
            is_customer = username in (settings.DEMO_USERNAME, settings.DEMO_SECOND_USERNAME) and secrets.compare_digest(password, settings.DEMO_PASSWORD)
            if not (is_admin or is_customer):
                emit(None, 'login_fail', result='failure', errorCode='INVALID_CREDENTIALS')
                raise FlowError('아이디 또는 비밀번호를 확인해 주세요.', 'LOGIN_FAILED', 401)
            request.session.flush()
            request.session['user'] = username
            request.session['role'] = 'admin' if is_admin else 'customer'
            emit(username, 'login_success')
            return JsonResponse({'redirect': ADMIN_HOME_URL if is_admin else '/'})
        user = request.session.get('user')
        if not user:
            raise FlowError('로그인이 필요해요.', 'AUTH_REQUIRED', 401, '/login/')
        page_id, attempt_id = data.get('pageId'), data.get('attemptId')
        if command == 'logout':
            with repo.lock:
                a = repo.current(user, False)
                if a and a['stage'] not in ('complete', 'cancelled', 'expired'):
                    a['stage'], a['captcha'] = 'cancelled', ''
                    emit(user, 'queue_cancel', a)
            request.session.flush()
            return JsonResponse({'redirect': '/login/'})
        if command == 'start':
            a = repo.start(user, data.get('showId'), page_id)
        elif command == 'heartbeat':
            a = repo.tick(user, page_id, attempt_id)
        elif command == 'verify':
            if not isinstance(data.get('answer', ''), str):
                raise FlowError('보안문자를 입력해 주세요.')
            a = repo.verify(user, page_id, attempt_id, data.get('answer', ''))
        elif command == 'cancel':
            a = repo.cancel(user, page_id, attempt_id)
        elif command == 'confirm':
            b = repo.confirm(user, page_id, attempt_id, data.get('sequence'), data.get('seats'), data.get('quantity'))
            return JsonResponse({'redirect': '/complete/' + b['id'] + '/', 'sequence': data.get('sequence')})
        elif command == 'scenario' and settings.SHOW_SCENARIOS:
            repo.scenario(user, page_id, attempt_id, data.get('name'), data.get('seats', []), data.get('showId'))
            return JsonResponse({'ok': True})
        else:
            raise FlowError('사용할 수 없는 요청이에요.')
        with repo.lock:
            return JsonResponse(snapshot(a))
    except FlowError as e:
        body = dict(error=e.message, code=e.code, redirect=e.redirect)
        if e.code in ('SEAT_SOLD', 'INSUFFICIENT_STOCK'):
            with repo.lock:
                body.update(sold=sorted(repo.sold), remaining=repo.remaining)
        return JsonResponse(body, status=e.status)


@require_GET
@never_cache
def captcha(request):
    user = request.session.get('user')
    if not user:
        return HttpResponse(status=401)
    try:
        answer = repo.challenge(user, request.GET.get('pageId'), request.GET.get('attemptId'))
    except FlowError as e:
        return HttpResponse(status=e.status)
    image = Image.new('RGB', (300, 94), '#edf2fc')
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 39)
    except OSError:
        font = ImageFont.load_default(size=39)
    for _ in range(250):
        x, y = random.randrange(300), random.randrange(94)
        draw.point((x, y), fill='#95acd2')
    for i, char in enumerate(answer):
        draw.text((25 + i*50, 20 + random.randint(-6, 6)), char, font=font, fill='#182d51')
    for _ in range(5):
        draw.line((random.randrange(300), random.randrange(94), random.randrange(300), random.randrange(94)), fill='#6584ae', width=1)
    output = io.BytesIO()
    image.save(output, 'PNG')
    return HttpResponse(output.getvalue(), content_type='image/png')


@never_cache
def events(request):
    user = request.session.get('user')
    if not user:
        return JsonResponse({'error': '로그인이 필요해요.'}, status=401)
    if request.method == 'GET':
        if not settings.SHOW_SCENARIOS:
            return HttpResponse(status=404)
        return JsonResponse({'events': publisher.for_user(user)})
    if request.method != 'POST':
        return HttpResponse(status=405)
    try:
        data = read_body(request)
        kind, event_id = data.get('eventType'), data.get('eventId')
        if kind not in CLIENT_EVENTS:
            raise FlowError('허용되지 않은 이벤트예요.')
        UUID(event_id)
        page_id = data.get('pageInstanceId')
        if not isinstance(page_id, str) or len(page_id) > 80:
            raise FlowError('페이지 식별자가 필요해요.')
        occurred = datetime.fromisoformat(data.get('occurredAt', ''))
        if occurred.tzinfo is None or abs((datetime.now(timezone.utc)-occurred).total_seconds()) > 86400:
            raise FlowError('이벤트 시간이 올바르지 않아요.')
        show_id = data.get('showId')
        if show_id is not None and show_id not in SHOWS:
            raise FlowError('공연 식별자가 올바르지 않아요.')
        with repo.lock:
            key = (user, event_id)
            if key in repo.client_events:
                return JsonResponse({'accepted': True, 'duplicate': True})
            repo.client_events.append(key)
            a = repo.current(user, False)
            if not a or a['page_id'] != page_id or a['stage'] in ('cancelled', 'expired', 'complete'):
                a = None
            emit(user, kind, a, eventId=event_id, occurredAt=occurred.astimezone(timezone.utc).isoformat(),
                 pageInstanceId=page_id, showId=show_id or (a['show_id'] if a else None), source='browser')
        return JsonResponse({'accepted': True})
    except (FlowError, ValueError, TypeError) as e:
        return JsonResponse({'error': e.message if isinstance(e, FlowError) else '이벤트 형식이 올바르지 않아요.'}, status=400)
