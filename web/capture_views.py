"""Anonymous simulation capture; business authentication remains unchanged."""
import json
from uuid import UUID
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.cache import never_cache
from .events import build_capture, publisher
from .event_schema import timestamp


@never_cache
def capture(request):
    if not getattr(settings,'CAPTURE_ENABLED',True): return JsonResponse({'state':'rejected','errorCode':'CAPTURE_DISABLED'},status=404)
    owner=request.capture_owner
    user=request.session.get('user')
    if request.method=='GET':
        receipt=publisher.status(request.GET.get('eventId'),user,owner=owner)
        if receipt is None: return JsonResponse({'state':'unknown'},status=404)
        return JsonResponse({k:receipt[k] for k in ('state','attempts','retryable','errorCode')})
    if request.method!='POST': return JsonResponse({'error':'method not allowed'},status=405)
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict): raise ValueError('object required')
        event_id=data.get('eventId');UUID(event_id)
        occurred=data.get('occurredAt');timestamp(occurred)
        kind=data.get('eventType')
        if not isinstance(kind,str) or not kind: raise ValueError('eventType required')
        details=data.get('details',{})
        if not isinstance(details,dict): raise ValueError('details object required')
        # Preserve unknown top-level observer fields without letting them spoof server provenance.
        known={'eventId','eventType','occurredAt','details','capture','pageInstanceId','pageViewId','showId','scheduleId','bookingAttemptId'}
        extras={k:v for k,v in data.items() if k not in known}
        if extras: details={**details,'observerExtensions':extras}
        context={k:data[k] for k in ('pageInstanceId','pageViewId','showId','scheduleId','bookingAttemptId') if k in data}
        context['anonymousId']=owner
        event=build_capture(user,kind,details,context,event_id,occurred,source='browser',client_capture=data.get('capture'))
        receipt=publisher.publish(event,owner=owner)
        result={k:receipt[k] for k in ('state','attempts','retryable','duplicate','errorCode')}
        result['accepted']=receipt['state']!='failed'
        return JsonResponse(result,status=503 if receipt['state']=='failed' else 200 if receipt['state']=='delivered' else 202)
    except RequestDataTooBig:
        return JsonResponse({'accepted':False,'state':'rejected','errorCode':'HTTP_BODY_LIMIT','retryable':False},status=413)
    except BufferError:
        return JsonResponse({'accepted':False,'state':'failed','errorCode':'BUFFER_FULL','retryable':True},status=503)
    except (ValueError,TypeError,AttributeError,RecursionError):
        return JsonResponse({'accepted':False,'state':'rejected','errorCode':'INVALID_CAPTURE','retryable':False},status=400)
