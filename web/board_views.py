"""Public board pages. Persistence and authoring will be connected separately."""
from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET


BOARDS = {
    'notices': {
        'title': '공지사항', 'eyebrow': 'TICKET GUARD NOTICE',
        'description': '티켓가드의 새로운 소식과 이용 안내를 확인하세요.',
        'categories': ('전체', '서비스 안내', '예매 안내', '점검 안내'),
        'empty': '등록된 공지사항이 없습니다.',
    },
    'free_board': {
        'title': '자유게시판', 'eyebrow': 'TICKET GUARD COMMUNITY',
        'description': '공연 이야기와 관람 경험을 자유롭게 나눠보세요.',
        'categories': ('전체', '공연 이야기', '관람 후기', '질문'),
        'empty': '등록된 게시글이 없습니다.',
    },
}


@require_GET
@never_cache
@ensure_csrf_cookie
def board_page(request, board):
    if board not in BOARDS:
        raise Http404
    config = BOARDS[board]
    category = request.GET.get('category', '전체')
    if category not in config['categories']:
        category = '전체'
    return render(request, 'boards/list.html', {
        'screen': board, 'board': config,
        'user': request.session.get('user'),
        'capture_enabled': settings.CAPTURE_ENABLED,
        'query': request.GET.get('q', '')[:100], 'category': category,
        # No preview/sample records are exposed in the actual user pages.
        'posts': [], 'total_count': 0,
    })
