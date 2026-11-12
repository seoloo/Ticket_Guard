"""
[홍석환] 서버 요청·응답 관측 미들웨어
요청 식별자와 본문·응답·처리 시간을 수집하고 비밀값을 가린다.
관측 실패로 업무 응답을 대체하지 않는다.
"""
import logging
import time
import traceback
from uuid import UUID,uuid4
from urllib.parse import parse_qsl
from django.conf import settings
from .events import build_capture,publisher
from .telemetry import body_snapshot,credential_values

logger=logging.getLogger('ticketguard.capture')


class RequestTelemetryMiddleware:
    def __init__(self,get_response): self.get_response=get_response

    def process_exception(self,request,exception):
        request.capture_exception={'type':type(exception).__name__,'message':str(exception),
                                   'stack':''.join(traceback.format_exception(type(exception),exception,exception.__traceback__))}
        return None

    def __call__(self,request):
        if not getattr(settings,'CAPTURE_ENABLED',True): return self.get_response(request)
        owner=request.get_signed_cookie('tg_capture',default=None,salt='capture-owner')
        try: UUID(owner)
        except (ValueError,TypeError,AttributeError): owner=str(uuid4())
        request.capture_owner=owner
        excluded=request.path.startswith(('/api/events/','/api/capture/','/health/'))
        started=time.perf_counter()
        incoming=request.headers.get('X-Capture-Request-ID')
        try: request_id=str(UUID(incoming))
        except (ValueError,TypeError,AttributeError): request_id=str(uuid4())
        request_body={'state':'unavailable','reason':'not_observed'}
        known=[]
        if not excluded:
            try:
                request_body=body_snapshot(request.body,request.headers.get('Content-Type',request.content_type or ''),request.encoding or 'utf-8')
                known=credential_values(request_body)+list(request.COOKIES.values())
                for key in ('X-CSRFToken','Authorization'):
                    if request.headers.get(key): known.append(request.headers[key])
            except Exception as exc:
                request_body={'state':'failed','reason':type(exc).__name__}
        response=self.get_response(request)
        if request.get_signed_cookie('tg_capture',default=None,salt='capture-owner') != owner:
            response.set_signed_cookie('tg_capture',owner,salt='capture-owner',httponly=True,samesite='Lax',secure=not settings.DEBUG)
        if excluded or not getattr(settings,'CAPTURE_ENABLED',True): return response
        response['X-Request-ID']=request_id
        details={'requestId':request_id,'request':{'url':request.get_full_path(),'method':request.method,
                  'query':[{'name':k,'value':v} for k,v in parse_qsl(request.META.get('QUERY_STRING',''),keep_blank_values=True)],
                  'headers':[{'name':k,'value':v} for k,v in request.headers.items()], 'body':request_body,
                  'protocol':request.META.get('SERVER_PROTOCOL'), 'remoteAddress':request.META.get('REMOTE_ADDR')},
                 'response':{'status':response.status_code,'reason':response.reason_phrase,
                             'headers':[{'name':k,'value':v} for k,v in response.headers.items()],
                             'cookies':[{'name':k,'value':m.OutputString()} for k,m in response.cookies.items()],
                             'streaming':response.streaming},
                 'timing':{'headersReadyMs':(time.perf_counter()-started)*1000},
                 'limitations':['server_observation_not_wire_bytes','framework_header_normalization']}
        if hasattr(request,'capture_exception'): details['exception']=request.capture_exception
        context={'anonymousId':owner}
        try:
            import json
            data=json.loads(request.body) if request.content_type=='application/json' else {}
            if isinstance(data,dict):
                for src,dst in (('pageId','pageInstanceId'),('pageViewId','pageViewId'),('attemptId','bookingAttemptId'),('showId','showId')):
                    if isinstance(data.get(src),str): context[dst]=data[src] or None
        except Exception: pass
        def finish(body):
            try:
                details['response']['body']=body
                details['timing']['observationDurationMs']=(time.perf_counter()-started)*1000
                event=build_capture(request.session.get('user'),'server_request',details,context,known=known)
                publisher.publish(event)
            except Exception as exc:
                publisher.failed+=1
                logger.error('capture_failed requestId=%s errorClass=%s',request_id,type(exc).__name__)
        def snapshot(raw):
            if request.path=='/captcha.png':
                return {'state':'unavailable','reason':'authentication_challenge_image'}
            return body_snapshot(raw,response.get('Content-Type',''),response.charset,known)
        if response.streaming:
            try:
                header_details={**details,'response':{**details['response'],'body':{'state':'pending','reason':'stream_not_finished'}}}
                publisher.publish(build_capture(request.session.get('user'),'server_response_headers',header_details,context,known=known))
            except Exception as exc:
                logger.error('capture_headers_failed requestId=%s errorClass=%s',request_id,type(exc).__name__)
            original=response.streaming_content
            if response.is_async:
                async def stream():
                    chunks=[];complete=False
                    try:
                        async for chunk in original:
                            chunks.append(bytes(chunk));yield chunk
                        complete=True
                    finally:
                        try:
                            body=snapshot(b''.join(chunks));body['streamComplete']=complete
                            if not complete: body['state']='partial'
                            finish(body)
                        except Exception as exc:
                            finish({'state':'failed','reason':type(exc).__name__})
                response.streaming_content=stream()
            else:
                def stream():
                    chunks=[];complete=False
                    try:
                        for chunk in original:
                            chunks.append(bytes(chunk));yield chunk
                        complete=True
                    finally:
                        try:
                            body=snapshot(b''.join(chunks));body['streamComplete']=complete
                            if not complete: body['state']='partial'
                            finish(body)
                        except Exception as exc:
                            finish({'state':'failed','reason':type(exc).__name__})
                response.streaming_content=stream()
        else:
            try: finish(snapshot(response.content))
            except Exception as exc: finish({'state':'failed','reason':type(exc).__name__})
        return response
