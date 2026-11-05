"""Simulation capture: preserve observable fields; redact credentials with an audit."""
import base64
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from django.conf import settings

TELEMETRY_EVENTS = {'browser_request', 'resource_timing', 'navigation_timing', 'browser_error', 'server_request'}
SECRET = re.compile('^(?:password|passwd|current[-_]?password|new[-_]?password|confirm[-_]?password|authorization|proxy[-_]?authorization|(?:set[-_]?)?cookie|sessionid|csrf|csrf[-_]?token|x[-_]?csrf[-_]?token|csrfmiddlewaretoken|(?:x[-_]?)?api[-_]?key|access[-_]?token|refresh[-_]?token|id[-_]?token|token|auth|secret|client[-_]?secret|answer|captcha[-_]?answer|captcha[-_]?response|g[-_]?recaptcha[-_]?response|otp)$', re.I)
REDACTED = '[REDACTED]'


def audit_template():
    return dict(status='complete', redactions=[], transformations=[], limitations=[], failures=[], truncations=[])


def configured_secrets():
    return [v for v in (getattr(settings, k, '') for k in ('SECRET_KEY','DEMO_PASSWORD','DEMO_ADMIN_PASSWORD')) if isinstance(v,str) and v]


def scrub_text(text, path, audit, known):
    for secret in known:
        if secret and secret != REDACTED and secret in text:
            text = text.replace(secret, REDACTED)
            audit['redactions'].append({'path':path,'reason':'known_credential'})
    # Form/log text and HTML hidden CSRF inputs, without discarding the document.
    pattern = r'(?i)((?:password|passwd|csrfmiddlewaretoken|access_token|refresh_token|api_key|answer)\s*[=:]\s*[\"\']?)([^\s&<>\"\']+)'
    text, n = re.subn(pattern, lambda m:m[1]+REDACTED, text)
    if n: audit['redactions'].append({'path':path,'reason':'credential_text','count':n})
    def hidden(m):
        tag=m[0]
        if re.search(r'(?i)name\s*=\s*[\"\'](?:csrfmiddlewaretoken|password|answer)[\"\']',tag):
            tag,n=re.subn(r'(?i)(value\s*=\s*)([\"\'])(.*?)\2',lambda x:x[1]+x[2]+REDACTED+x[2],tag)
            if n: audit['redactions'].append({'path':path,'reason':'credential_html'})
        return tag
    text=re.sub(r'(?is)<input\b[^>]*>',hidden,text)
    text,n=re.subn(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+','Bearer '+REDACTED,text)
    if n: audit['redactions'].append({'path':path,'reason':'bearer'})
    return text


def redact_url(text, path, audit, known):
    try:
        u=urlsplit(text)
        pairs=parse_qsl(u.query,keep_blank_values=True)
        changed=False
        for i,(k,v) in enumerate(pairs):
            if SECRET.search(k):
                pairs[i]=(k,REDACTED);changed=True
                audit['redactions'].append({'path':path+'.query.'+k,'reason':'credential'})
        netloc=u.netloc
        if '@' in netloc:
            netloc=REDACTED+'@'+netloc.rsplit('@',1)[1];changed=True
            audit['redactions'].append({'path':path+'.userinfo','reason':'credential'})
        if changed:
            text=urlunsplit((u.scheme,netloc,u.path,urlencode(pairs),u.fragment))
            audit['transformations'].append({'path':path,'reason':'url_reencoded_for_redaction'})
    except ValueError:
        audit['limitations'].append({'path':path,'reason':'url_parse_failed'})
    return scrub_text(text,path,audit,known)


def redact(value, path, audit, known):
    if isinstance(value,dict):
        # Header/query/form arrays are name/value pairs; keep duplicate entries.
        pair_name=value.get('name',value.get('key'))
        result={}
        for key,item in value.items():
            if not isinstance(key,str): raise ValueError('JSON object keys must be strings')
            p=path+'.'+key
            if SECRET.search(key) or (key=='value' and isinstance(pair_name,str) and SECRET.search(pair_name)):
                result[key]=REDACTED
                if item != REDACTED: audit['redactions'].append({'path':p,'reason':'credential'})
            else: result[key]=redact(item,p,audit,known)
        return result
    if isinstance(value,list):
        return [redact(v,path+'.'+str(i),audit,known) for i,v in enumerate(value)]
    if isinstance(value,str):
        if path.rsplit('.',1)[-1].lower() in ('url','referer','referrer','location','name') and ('?' in value or '://' in value):
            return redact_url(value,path,audit,known)
        # Textual JSON is still a body: redact fields before reserializing it.
        if value.lstrip().startswith(('{','[')):
            try:
                parsed=json.loads(value)
                cleaned=redact(parsed,path,audit,known)
                if cleaned != parsed:
                    audit['transformations'].append({'path':path,'reason':'json_reserialized_for_redaction'})
                    value=json.dumps(cleaned,ensure_ascii=False,allow_nan=False)
            except (ValueError,RecursionError): pass
        return scrub_text(value,path,audit,known)
    if value is None or type(value) in (bool,int,float): return value
    raise ValueError('not a JSON value')


def sanitize_capture(value, known=()):
    audit=audit_template()
    cleaned=redact(value,'details',audit,tuple(known)+tuple(configured_secrets()))
    json.dumps(cleaned,allow_nan=False)
    if audit['redactions']: audit['status']='redacted'
    def inspect(item,path):
        if isinstance(item,dict):
            if path.endswith('.body') or 'representation' in item:
                state=item.get('state')
                if state in ('unavailable','partial','pending'):
                    audit['limitations'].append({'path':path,'state':state,'reason':item.get('reason',state)})
                elif state=='failed':
                    audit['failures'].append({'path':path,'reason':item.get('reason','observation_failed')})
                elif state=='redacted':
                    audit['redactions'].append({'path':path,'reason':item.get('reason','observer_redaction')})
                if item.get('transformation'):
                    audit['transformations'].append({'path':path,'reason':item['transformation']})
            for key,value in item.items(): inspect(value,path+'.'+key)
        elif isinstance(item,list):
            for index,value in enumerate(item): inspect(value,path+'.'+str(index))
    inspect(cleaned,'details')
    if audit['failures'] or audit['limitations']: audit['status']='partial'
    elif audit['redactions']: audit['status']='redacted'
    return cleaned,audit


def sanitize(value, depth=0):
    return sanitize_capture(value)[0]


def body_snapshot(data, content_type='', charset='utf-8', known=()):
    if not data: return {'state':'empty','representation':'base64','bytes':0,'value':''}
    if 'multipart/form-data' in content_type:
        from email.parser import BytesParser
        from email.policy import default
        message=BytesParser(policy=default).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+data)
        if message.is_multipart():
            fields=[]
            for part in message.iter_parts():
                raw=part.get_payload(decode=True) or b''
                fields.append({'name':part.get_param('name',header='content-disposition'),
                               'filename':part.get_filename(),'headers':[{'name':k,'value':v} for k,v in part.items()],
                               'value':body_snapshot(raw,part.get_content_type(),part.get_content_charset() or 'utf-8',known)})
            return {'state':'captured','representation':'multipart','bytes':len(data),'value':fields,
                    'transformation':'parsed_multipart_not_wire_bytes'}
    if 'application/json' in content_type:
        try:
            return {'state':'captured','representation':'json','bytes':len(data),
                    'value':json.loads(data.decode(charset)), 'text':data.decode(charset), 'transformation':'parsed_json_with_text_copy_not_wire_headers'}
        except (ValueError,LookupError,UnicodeError): pass
    if 'application/x-www-form-urlencoded' in content_type:
        try:
            return {'state':'captured','representation':'form','bytes':len(data),
                    'value':[{'name':k,'value':v} for k,v in parse_qsl(data.decode(charset),keep_blank_values=True)],'text':data.decode(charset),
                    'transformation':'parsed_form_not_wire_bytes'}
        except (ValueError,LookupError,UnicodeError): pass
    if content_type.startswith('text/') or any(x in content_type for x in ('javascript','xml','json')):
        try: return {'state':'captured','representation':'text','bytes':len(data),'charset':charset,'value':data.decode(charset)}
        except (LookupError,UnicodeError): pass
    original_size=len(data)
    changed=False
    for secret in tuple(known)+tuple(configured_secrets()):
        if secret and secret.encode('utf-8') in data:
            data=data.replace(secret.encode('utf-8'),REDACTED.encode());changed=True
    if changed:
        return {'state':'redacted','representation':'base64','bytes':original_size,'value':base64.b64encode(data).decode(),
                'reason':'known_credential_in_binary','transformation':'binary_redacted'}
    return {'state':'captured','representation':'base64','bytes':len(data),'value':base64.b64encode(data).decode()}


def credential_values(value):
    found=[]
    if isinstance(value,dict):
        pair=value.get('name',value.get('key'))
        for k,v in value.items():
            if (SECRET.search(str(k)) or (k=='value' and isinstance(pair,str) and SECRET.search(pair))) and isinstance(v,str):
                found.append(v)
            found.extend(credential_values(v))
    elif isinstance(value,list):
        for v in value: found.extend(credential_values(v))
    return found
