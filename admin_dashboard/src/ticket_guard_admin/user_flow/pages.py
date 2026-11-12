"""
[홍석환] 실제 사용자 흐름 공개 지표 페이지
조회·표시 변환을 연결하고 공개 결과 없음과 오류를 샘플 없이 렌더링한다.
"""
from fastapi.responses import HTMLResponse

from ticket_guard_admin.pages import templates
from .contracts import FlowError, scope_key
from .presentation import for_display, scope_label
from .reader import PublishedFlowReader


def render_published_dashboard(request, mongo_uri) -> HTMLResponse:
    context = dict(base_path=request.app.state.base_path,
                   admin_user=getattr(request.state, 'admin_user', ''), is_preview=False,
                   flow=None, flow_error=None, scope='all', scope_choices=[{'value': 'all', 'label': '전체 공개 지표'}],
                   header_status='공개 지표 확인', header_error=False, header_tone='neutral')
    try:
        if set(request.query_params) - {'scope'} or len(request.query_params.getlist('scope')) > 1:
            raise FlowError('unsupported_filter', '지원하지 않는 조회 조건 · 기존 기간·공연 단독 필터 대신 공개된 범위 조합을 선택해 주세요.')
        context['scope'] = scope_key(request.query_params.get('scope', 'all'))
        result = PublishedFlowReader(mongo_uri).read(context['scope'])
        context['flow'] = for_display(result)
        context['scope_choices'] = [dict(value=value, label=scope_label(value)) for value in result['scopes']]
        context['header_status'] = '공개 지표 조회 완료'
        context['header_tone'] = 'normal'
    except FlowError as exc:
        context['flow_error'] = dict(code=exc.code, message=exc.message)
        context['header_status'] = {'no_publication': '공개 결과 없음', 'scope_not_found': '조회 범위 없음',
                                    'unsupported_filter': '조회 조건 확인'}.get(exc.code, '공개 지표 조회 실패')
        context['header_error'] = exc.code not in ('no_publication', 'scope_not_found', 'unsupported_filter')
    context['dashboard_data'] = {'flow': context['flow']}
    response = templates.TemplateResponse(request, 'monitor_live.html', context)
    response.headers['Cache-Control'] = 'no-store'
    return response
