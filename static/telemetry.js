/* Simulation observer. Copies observable values; never replays business requests. */
(() => {
  'use strict';
  const nativeFetch = window.fetch.bind(window);
  const queueKey = 'tg-capture-v2';
  let pageInstanceId=crypto.randomUUID(),bootstrapStorageError=null;
  try {pageInstanceId=sessionStorage.getItem('tg-page')||pageInstanceId;sessionStorage.setItem('tg-page',pageInstanceId);}
  catch(error){bootstrapStorageError=error.name;console.error('Capture storage unavailable; using memory',error.name);}
  const pageViewId = crypto.randomUUID();
  const secretKey = /^(?:password|passwd|current[-_]?password|new[-_]?password|confirm[-_]?password|authorization|proxy[-_]?authorization|(?:set[-_]?)?cookie|sessionid|csrf|csrf[-_]?token|x[-_]?csrf[-_]?token|csrfmiddlewaretoken|(?:x[-_]?)?api[-_]?key|access[-_]?token|refresh[-_]?token|id[-_]?token|token|auth|secret|client[-_]?secret|answer|captcha[-_]?answer|captcha[-_]?response|g[-_]?recaptcha[-_]?response|otp)$/i;
  const secrets = new Set();
  const diagnostics = {storageFailures:bootstrapStorageError?1:0, serializationFailures:0, rejected:0, networkFailures:0, delivered:0, lastError:null};
  let queue=[], busy=false;
  try { queue=JSON.parse(sessionStorage.getItem(queueKey)||'[]'); }
  catch (error) { diagnostics.lastError='restore:'+error.name;console.error('Capture queue restore failed',error.name); }
  const excluded = url => {
    try { const u=new URL(url,location.href);return u.origin===location.origin && /^\/(api\/(events|capture)\/|health\/)/.test(u.pathname); }
    catch (_) { return false; }
  };
  function persist() {
    try { sessionStorage.setItem(queueKey,JSON.stringify(queue)); }
    catch(error) { diagnostics.storageFailures++;diagnostics.lastError='storage:'+error.name;console.error('Capture remains in memory; persistence failed',error.name); }
  }
  function jsonCopy(value, seen=new WeakSet()) {
    if(value===undefined)return {state:'unavailable',reason:'undefined'};
    if(value===null||typeof value!=='object') {
      if(typeof value==='number'&&!Number.isFinite(value))return {state:'unavailable',reason:'nonfinite',value:String(value)};
      if(['bigint','symbol','function'].includes(typeof value))return {representation:typeof value,value:String(value)};
      return value;
    }
    if(seen.has(value))return {state:'unavailable',reason:'circular_reference'};
    seen.add(value);
    if(typeof value.toJSON==='function') {
      try {const serialized=value.toJSON();if(serialized!==value){const result=jsonCopy(serialized,seen);seen.delete(value);return result;}}catch(_) {}
    }
    let out;
    if(Array.isArray(value))out=value.map(v=>jsonCopy(v,seen));
    else {
      out={};
      for(const key of Object.getOwnPropertyNames(value)) {
        try { out[key]=jsonCopy(value[key],seen); }
        catch(error) {out[key]={state:'unavailable',reason:error.name};}
      }
    }
    seen.delete(value);return out;
  }
  function remember(value) {
    if(!value||typeof value!=='object')return;
    const name=value.name??value.key;
    for(const [k,v] of Object.entries(value)) {
      if((secretKey.test(k)||(k==='value'&&typeof name==='string'&&secretKey.test(name)))&&typeof v==='string'&&v!=='[REDACTED]')secrets.add(v);
      if(v&&typeof v==='object')remember(v);
    }
  }
  function textRedact(text,path,audit) {
    for(const secret of secrets)if(secret&&text.includes(secret)){text=text.split(secret).join('[REDACTED]');audit.redactions.push({path,reason:'known_credential'});}
    text=text.replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi,()=>{audit.redactions.push({path,reason:'bearer'});return 'Bearer [REDACTED]';});
    text=text.replace(/((?:password|passwd|csrfmiddlewaretoken|access_token|refresh_token|api_key|answer)\s*[=:]\s*["']?)([^\s&<>"']+)/gi,(_,prefix)=>{audit.redactions.push({path,reason:'credential_text'});return prefix+'[REDACTED]';});
    text=text.replace(/<input\b[^>]*>/gi,tag=>{
      if(/name\s*=\s*["'](?:csrfmiddlewaretoken|password|answer)["']/i.test(tag))return tag.replace(/(value\s*=\s*)(["'])(.*?)\2/gi,(_,a,q)=>{audit.redactions.push({path,reason:'credential_html'});return a+q+'[REDACTED]'+q;});
      return tag;
    });
    return text;
  }
  function redact(value,path,audit) {
    if(value&&typeof value==='object') {
      if(Array.isArray(value))return value.map((v,i)=>redact(v,path+'.'+i,audit));
      if(value.representation==='base64'&&typeof value.value==='string') {
        try {
          let bytes=atob(value.value);
          for(const secret of secrets) {
            const encoded=String.fromCharCode(...new TextEncoder().encode(secret));
            if(encoded&&bytes.includes(encoded)){bytes=bytes.split(encoded).join('[REDACTED]');audit.redactions.push({path:path+'.value',reason:'known_credential_in_binary'});value={...value,state:'redacted',value:btoa(bytes),transformation:'binary_credential_redaction'};}
          }
          const raw=Uint8Array.from(bytes,c=>c.charCodeAt(0));
          const text=new TextDecoder('utf-8',{fatal:true}).decode(raw);
          const safe=textRedact(text,path+'.value',audit);
          if(safe!==text){value={...value,state:'redacted',value:base64(new TextEncoder().encode(safe)),transformation:'binary_credential_redaction'};}
        }catch(_) {}
      }
      const out={},name=value.name??value.key;
      for(const [k,v] of Object.entries(value)) {
        const p=path+'.'+k;
        if(secretKey.test(k)||(k==='value'&&typeof name==='string'&&secretKey.test(name))) {
          out[k]='[REDACTED]';if(v!=='[REDACTED]')audit.redactions.push({path:p,reason:'credential'});
        } else out[k]=redact(v,p,audit);
      }
      return out;
    }
    if(typeof value==='string') {
      if(/\.(url|name|referer|referrer|location)$/i.test(path)&&(/[?]/.test(value)||value.includes('://'))) {
        try {
          const u=new URL(value,location.href);let changed=false;
          for(const key of new Set(u.searchParams.keys()))if(secretKey.test(key)) {
            const vals=u.searchParams.getAll(key);u.searchParams.delete(key);for(const v of vals)u.searchParams.append(key,'[REDACTED]');
            changed=true;audit.redactions.push({path:path+'.query.'+key,reason:'credential'});
          }
          if(u.username||u.password){u.username='[REDACTED]';u.password='';changed=true;audit.redactions.push({path,reason:'url_credentials'});}
          if(changed){value=u.href;audit.transformations.push({path,reason:'url_reencoded_for_redaction'});}
        } catch(_) {}
      }
      if(/^[\s]*[\[{]/.test(value)) {
        try {const parsed=JSON.parse(value),clean=redact(parsed,path,audit);if(JSON.stringify(parsed)!==JSON.stringify(clean)){value=JSON.stringify(clean);audit.transformations.push({path,reason:'json_reserialized_for_redaction'});}}
        catch(_) {}
      }
      return textRedact(value,path,audit);
    }
    return value;
  }
  function csrf() { return document.querySelector('[name=csrfmiddlewaretoken]')?.value; }
  function record(eventType, details={}, context={}) {
    try {
      const audit={status:'complete',redactions:[],transformations:[],limitations:[],truncations:[]};
      const copy=jsonCopy(details);remember(copy);
      const clean=redact(copy,'details',audit);
      if(audit.redactions.length)audit.status='redacted';
      const token=csrf();if(token)secrets.add(token);
      const safeContext=redact(jsonCopy(context),'context',audit);
      queue.push({payload:{eventId:crypto.randomUUID(),eventType,occurredAt:new Date().toISOString(),pageInstanceId,pageViewId,
        ...safeContext,details:clean,capture:audit},pending:false,failures:0});
      persist();void flush();
    } catch(error) {diagnostics.serializationFailures++;diagnostics.lastError='capture:'+error.name;console.error('Capture failed',eventType,error.name);}
  }
  async function flush(keepalive=false) {
    if(busy)return;busy=true;
    try {
      for(const item of [...queue]) {
        if(item.rejected||Date.now()<(item.next||0))continue;
        try {
          let response;
          if(item.pending)response=await nativeFetch('/api/capture/?eventId='+encodeURIComponent(item.payload.eventId));
          if(!item.pending||response.status===404) {
            const body=JSON.stringify(item.payload),headers={'Content-Type':'application/json'};
            const token=csrf();if(token)headers['X-CSRFToken']=token;
            // Fetch keepalive has a browser-wide body quota. Larger records stay queued.
            response=await nativeFetch('/api/capture/',{method:'POST',headers,body,keepalive:keepalive&&new TextEncoder().encode(body).length<60000});
          }
          const result=await response.json();
          if(result.state==='delivered'){queue=queue.filter(x=>x!==item);diagnostics.delivered++;}
          else if([400,403,405,413].includes(response.status)||result.state==='rejected') {
            item.rejected=true;item.error={status:response.status,code:result.errorCode||'HTTP_REJECTED'};
            diagnostics.rejected++;diagnostics.lastError=item.error;console.error('Capture rejected; record retained',item.payload.eventId,item.error);
          } else if(result.state==='failed'&&result.retryable===false) {
            item.rejected=true;item.error={status:response.status,code:result.errorCode||'DELIVERY_EXHAUSTED'};
            diagnostics.rejected++;diagnostics.lastError=item.error;console.error('Capture delivery exhausted; record retained',item.payload.eventId);
          } else {item.pending=result.state==='pending';item.next=Date.now()+1000;if(result.state==='failed')item.pending=false;}
        } catch(error) {
          item.failures++;item.next=Date.now()+Math.min(30000,1000*2**Math.min(item.failures,5));
          diagnostics.networkFailures++;diagnostics.lastError='delivery:'+error.name;
        }
        persist();
      }
    } finally {busy=false;}
  }
  window.ticketGuardCapture={record,pageInstanceId,pageViewId,diagnostics,
    inspect:()=>queue.map(x=>({eventId:x.payload.eventId,eventType:x.payload.eventType,pending:x.pending,rejected:!!x.rejected,error:x.error})),
    retry:()=>{for(const item of queue){item.rejected=false;item.pending=false;item.next=0;}persist();return flush();}};
  setInterval(()=>void flush(),1000);
  window.addEventListener('pagehide',()=>{record('page_lifecycle',{phase:'pagehide',url:location.href});void flush(true);});
  const pairs = headers => Array.from(new Headers(headers||{}),([name,value])=>({name,value}));
  function base64(bytes) {let text='';for(let i=0;i<bytes.length;i+=32768)text+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(text);}
  async function body(value,contentType='') {
    if(value===undefined||value===null)return {state:'not_applicable',representation:'none'};
    if(typeof value==='string') {
      if(!value)return {state:'empty',representation:'text',value:''};
      if(contentType.includes('json')) {try{return {state:'captured',representation:'json',value:JSON.parse(value),text:value,transformation:'parsed_json_with_text_copy_not_wire_headers'};}catch(_) {}}
      if(contentType.includes('application/x-www-form-urlencoded'))return {state:'captured',representation:'form',value:Array.from(new URLSearchParams(value),([name,value])=>({name,value})),text:value,transformation:'parsed_form_not_wire_bytes'};
      return {state:'captured',representation:'text',value};
    }
    if(value instanceof URLSearchParams)return {state:'captured',representation:'form',value:Array.from(value,([name,value])=>({name,value}))};
    if(value instanceof FormData) {
      const fields=[];
      for(const [name,value] of value)fields.push({name,value:typeof value==='string'?value:{filename:value.name,type:value.type,size:value.size,lastModified:value.lastModified,webkitRelativePath:value.webkitRelativePath,body:await body(value,value.type)}});
      return {state:'captured',representation:'multipart',value:fields,transformation:'formdata_observation_not_wire_boundary'};
    }
    if(value instanceof Blob) {
      const raw=new Uint8Array(await value.arrayBuffer());
      if(contentType.startsWith('text/')||/json|javascript|xml/.test(contentType)) {
        try {const charset=/charset\s*=\s*["']?([^;\s"']+)/i.exec(contentType)?.[1]||'utf-8';return {...await body(new TextDecoder(charset,{fatal:true}).decode(raw),contentType),bytes:raw.length,charset};}catch(_) {}
      }
      return {state:raw.length?'captured':'empty',representation:'base64',bytes:raw.length,value:base64(raw)};
    }
    if(value instanceof ArrayBuffer||ArrayBuffer.isView(value))return body(new Blob([value]),contentType);
    return {state:'unavailable',reason:'stream_or_unsupported_body_copy_would_change_consumption',type:Object.prototype.toString.call(value)};
  }
  function failedBody(error){return {state:'failed',reason:error.name};}
  function requestOptions(input) {
    if(!(input instanceof Request))return {};
    const out={};
    for(const key of new Set([...Object.getOwnPropertyNames(input),...Object.getOwnPropertyNames(Object.getPrototypeOf(input))])) {
      if(['constructor','body','headers'].includes(key))continue;
      try {
        const value=input[key];
        if(typeof value==='function')continue;
        out[key]=key==='signal'?{aborted:value.aborted,reason:jsonCopy(value.reason)}:jsonCopy(value);
      }catch(error){out[key]={state:'unavailable',reason:error.name};}
    }
    return out;
  }
  window.fetch=function(input,init={}) {
    const rawUrl=input instanceof Request?input.url:String(input);
    if(excluded(rawUrl))return nativeFetch(input,init);
    const began=performance.now(),requestId=crypto.randomUUID();
    let request;
    try {
      const headers=pairs(init.headers||(input instanceof Request?input.headers:undefined));
      const type=new Headers(init.headers||(input instanceof Request?input.headers:undefined)).get('content-type')||'';
      let observedBody;
      if(init.body!==undefined)observedBody=body(init.body,type).catch(failedBody);
      else if(input instanceof Request&&input.body) {
        try {observedBody=input.clone().blob().then(blob=>body(blob,type)).catch(failedBody);}
        catch(error){observedBody=Promise.resolve(failedBody(error));}
      }
      else observedBody=body(null,type);
      request=Promise.resolve(observedBody).then(snapshot=>({url:rawUrl,method:init.method||(input instanceof Request?input.method:'GET'),headers,body:snapshot,
        options:{...requestOptions(input),...jsonCopy(Object.fromEntries(Object.entries(init).filter(([k])=>!['body','headers','signal'].includes(k))))},
        limitations:['browser_generated_headers_not_fully_exposed','not_wire_bytes']}));
    } catch(error){request=Promise.resolve({url:rawUrl,body:failedBody(error)});}
    void request.then(req=>record('browser_request_body',{requestId,transport:'fetch',request:req}),error=>record('collector_failure',{phase:'request_body',requestId,error:jsonCopy(error)}));
    record('browser_request_start',{requestId,transport:'fetch',request:{url:rawUrl,method:init.method||(input instanceof Request?input.method:'GET'),
      headers:pairs(init.headers||(input instanceof Request?input.headers:undefined)),body:{state:'pending'}}});
    const result=nativeFetch(input,init);
    result.then(response=>{
      const headersMs=performance.now()-began;
      record('browser_response_headers',{requestId,transport:'fetch',serverRequestId:response.headers.get('X-Request-ID'),
        response:{url:response.url,status:response.status,statusText:response.statusText,headers:pairs(response.headers),body:{state:'pending'}},timing:{headersReadyMs:headersMs}});
      let responseCopy;
      try {responseCopy=response.clone();}catch(error){responseCopy=null;}
      void (async()=>{
        try {
          const req=await request;
          const isChallenge=new URL(rawUrl,location.href).pathname==='/captcha.png';
          const snapshot=response.type==='opaque'?{state:'unavailable',reason:'opaque_response'}:
            isChallenge?{state:'unavailable',reason:'authentication_challenge_image'}:
            responseCopy?await body(await responseCopy.blob(),response.headers.get('content-type')||''):{state:'failed',reason:'response_clone_failed'};
          record('browser_request',{requestId,transport:'fetch',request:req,response:{url:response.url,status:response.status,statusText:response.statusText,
            headers:pairs(response.headers),type:response.type,redirected:response.redirected,body:snapshot},
            serverRequestId:response.headers.get('X-Request-ID'),timing:{headersReadyMs:headersMs,bodyObservedMs:performance.now()-began}});
        } catch(error){record('browser_request',{requestId,transport:'fetch',request:await request,response:{body:failedBody(error)}});}
      })();
    },error=>{void request.then(req=>record('browser_request',{requestId,transport:'fetch',request:req,
      response:{state:'unavailable',reason:'network_failure'},error:jsonCopy(error),timing:{durationMs:performance.now()-began}}));});
    return result;
  };
  const xhrProto=XMLHttpRequest.prototype,open=xhrProto.open,send=xhrProto.send,setHeader=xhrProto.setRequestHeader;
  const xhrData=new WeakMap();
  xhrProto.open=function(method,url,...args){const result=open.call(this,method,url,...args);xhrData.set(this,{method,url:String(url),headers:[],async:args[0]!==false});return result;};
  xhrProto.setRequestHeader=function(name,value){const result=setHeader.call(this,name,value);xhrData.get(this)?.headers.push({name,value});return result;};
  xhrProto.send=function(value){
    const info=xhrData.get(this);if(!info||excluded(info.url))return send.call(this,value);
    const began=performance.now(),requestId=crypto.randomUUID();
    const type=info.headers.find(x=>x.name.toLowerCase()==='content-type')?.value||'';
    const requestBody=body(value,type).catch(failedBody);
    void requestBody.then(snapshot=>record('browser_request_body',{requestId,transport:'xhr',request:{...info,body:snapshot}}));
    for(const kind of ['abort','timeout','error'])this.addEventListener(kind,()=>{info.failure=kind;},{once:true});
    record('browser_request_start',{requestId,transport:'xhr',request:{...info,body:{state:'pending'}}});
    this.addEventListener('loadend',()=>{void(async()=>{
      try {
        const headers=this.getAllResponseHeaders().trim().split(/[\r\n]+/).filter(Boolean).map(line=>{const i=line.indexOf(':');return {name:line.slice(0,i),value:line.slice(i+1).trim()};});
        let snapshot;
        if(this.responseType==='json')snapshot={state:'captured',representation:'json',value:jsonCopy(this.response),transformation:'xhr_parsed_json'};
        else if(this.responseType==='document')snapshot={state:'captured',representation:'text',value:this.response?new XMLSerializer().serializeToString(this.response):'',transformation:'serialized_document_not_wire_bytes'};
        else snapshot=await body(this.responseType===''||this.responseType==='text'?this.responseText:this.response,this.getResponseHeader('content-type')||'');
        if(this.status===0)snapshot={state:'unavailable',reason:info.failure||'no_http_response'};
        record('browser_request',{requestId,transport:'xhr',request:{...info,body:await requestBody},
          response:{url:this.responseURL,status:this.status,statusText:this.statusText,responseType:this.responseType,headers,body:snapshot},
          serverRequestId:this.getResponseHeader('X-Request-ID'),timing:{durationMs:performance.now()-began}});
      } catch(error){record('browser_request',{requestId,transport:'xhr',request:info,error:jsonCopy(error),response:{state:'failed',reason:error.name}});}
    })();},{once:true});
    try {return send.call(this,value);}catch(error){record('browser_request',{requestId,transport:'xhr',request:info,error:jsonCopy(error)});throw error;}
  };
  if(typeof PerformanceObserver!=='undefined') {
    for(const type of PerformanceObserver.supportedEntryTypes||['resource','navigation']) {
      try {
        const observer=new PerformanceObserver(list=>{for(const entry of list.getEntries()) {
          if(excluded(entry.name))continue;
          try {record(type==='resource'?'resource_timing':type==='navigation'?'navigation_timing':'performance_entry',
            {entry:entry.toJSON(),limitations:['browser_api_fields_only','cross_origin_fields_may_be_restricted']});}
          catch(error){record('collector_failure',{phase:'performance',error:jsonCopy(error)});}
        }});observer.observe({type,buffered:true});
      }catch(error){diagnostics.lastError='performance:'+type+':'+error.name;}
    }
  }
  performance.addEventListener?.('resourcetimingbufferfull',()=>record('collector_limitation',{kind:'resource_timing_buffer_full',reason:'some_prior_entries_may_be_unavailable'}));
  window.addEventListener('error',e=>record('browser_error',{kind:e.target&&e.target!==window?'resource_load':'script',
    message:e.message,error:jsonCopy(e.error),filename:e.filename,lineNumber:e.lineno,columnNumber:e.colno,
    resourceUrl:e.target?.src||e.target?.href,limitations:['cross_origin_errors_may_be_restricted']}),true);
  window.addEventListener('unhandledrejection',e=>record('browser_error',{kind:'unhandled_rejection',reason:jsonCopy(e.reason)}));
  window.addEventListener('pageshow',e=>record('page_lifecycle',{phase:'pageshow',persisted:e.persisted,url:location.href}));
  document.addEventListener('visibilitychange',()=>record('page_lifecycle',{phase:'visibilitychange',visibilityState:document.visibilityState,url:location.href}));
  // Generic interactions complement, rather than replace, explicit business events.
  for(const type of ['click','submit','change'])document.addEventListener(type,e=>{
    const el=e.target;
    record('ui_interaction',{type,tagName:el?.tagName,id:el?.id,name:el?.name,inputType:el?.type,
      href:el?.href,formAction:el?.action,dataset:el?.dataset?{...el.dataset}:{},
      value:el?.type==='password'?'[REDACTED]':el?.value});
  },true);
  record('page_lifecycle',{phase:'collector_ready',url:location.href,readyState:document.readyState});
})();
