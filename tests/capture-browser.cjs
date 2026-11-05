const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const config=spawnSync('docker',['exec','ticket-guard-web-1','python','-c',"import os,json;print(json.dumps({'user':os.environ.get('DEMO_USERNAME','ticketguard'),'password':os.environ.get('DEMO_PASSWORD','ticketguard-demo')}))"],{encoding:'utf8'});
 assert.equal(config.status,0);const account=JSON.parse(config.stdout);
 for(let attempt=0;attempt<50;attempt++){try{const r=await fetch('http://localhost:8000/health/');if(r.ok)break;}catch(_){}if(attempt===49)throw Error('Web readiness timeout');await new Promise(r=>setTimeout(r,200));}
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try {
  const context=await browser.newContext();const page=await context.newPage();
  const requests=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',req=>{if(req.url().includes('/api/capture/')&&req.method()==='POST')requests.push(JSON.parse(req.postData()));});
  await page.goto('http://localhost:8000/login/',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>!!window.ticketGuardCapture);
  await page.waitForFunction(()=>window.ticketGuardCapture.diagnostics.delivered>0);
  assert(requests.some(e=>e.eventType==='page_enter'&&e.details.pageName==='login'));
  await page.locator('#username').fill(account.user);await page.locator('#password').fill(account.password);
  await Promise.all([page.waitForURL('http://localhost:8000/'),page.locator('#login-form [type=submit]').click()]);
  await page.waitForFunction(()=>!!window.ticketGuardCapture);
  const outcomes=await page.evaluate(async()=>{
   const csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;
   const payload={action:'heartbeat',futureField:{text:'한글'.repeat(12000),array:Array.from({length:100},(_,i)=>i)},password:'browser-test-secret'};
   const response=await fetch('/api/action/?q=music&q=live&token=browser-test-secret',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf,'X-Simulation-Custom':'kept'},body:JSON.stringify(payload)});
   const body=await response.json();
   const xhr=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/action/?q=xhr');xhr.setRequestHeader('Content-Type','application/json');xhr.setRequestHeader('X-CSRFToken',csrf);xhr.onload=()=>resolve({status:xhr.status,text:xhr.responseText});xhr.onerror=reject;xhr.send(JSON.stringify({action:'heartbeat',future:'xhr-kept'}));});
   window.ticketGuardCapture.record('nested_performance_fixture',{serverTiming:[{toJSON(){return {name:'backend',duration:4.2,description:'kept'};}}]});
   window.ticketGuardCapture.record('future_unknown_event',{futureField:{array:Array.from({length:100},(_,i)=>i)},longString:'z'.repeat(25000)});
   // Request body is observed through a clone without consuming the original.
   const req=new Request('/api/action/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({action:'heartbeat',requestObjectField:'kept'})});
   await fetch(req);
   try {await fetch('http://127.0.0.1:1/intentional-network-failure');}catch(_) {}
   window.dispatchEvent(new ErrorEvent('error',{message:'simulation error detail',filename:location.href,lineno:7,error:new Error('simulation error detail')}));
   return {status:response.status,body,xhr};
  });
  assert([400,409].includes(outcomes.status));assert([400,409].includes(outcomes.xhr.status));
  await page.waitForFunction(()=>window.ticketGuardCapture.inspect().length===0,{},{timeout:30000});
  const diagnostics=await page.evaluate(()=>window.ticketGuardCapture.diagnostics);
  assert.equal(diagnostics.rejected,0);assert.equal(diagnostics.storageFailures,0);
  const fetchRecord=requests.find(e=>e.eventType==='browser_request'&&e.details.transport==='fetch'&&e.details.request.url.includes('q=music'));
  assert(fetchRecord);assert.equal(fetchRecord.details.request.body.value.futureField.text.length,24000);
  assert.equal(fetchRecord.details.request.body.value.futureField.array.length,100);
  assert(fetchRecord.details.request.url.includes('q=music'));assert(!JSON.stringify(fetchRecord).includes('browser-test-secret'));
  assert.equal(fetchRecord.details.response.status,outcomes.status);assert(fetchRecord.details.response.body.value.code);
  assert(fetchRecord.details.serverRequestId);
  assert(requests.some(e=>e.eventType==='browser_request'&&e.details.response?.reason==='network_failure'));
  assert(requests.some(e=>e.eventType==='browser_request'&&e.details.transport==='xhr'&&e.details.request.body.value.future==='xhr-kept'));
  assert(requests.some(e=>e.eventType==='nested_performance_fixture'&&e.details.serverTiming[0].duration===4.2));
  assert(requests.some(e=>e.eventType==='future_unknown_event'&&e.details.longString.length===25000));
  assert(requests.some(e=>e.eventType==='browser_request'&&e.details.request?.body?.value?.requestObjectField==='kept'));
  assert(requests.some(e=>e.eventType==='resource_timing'&&e.details.entry.name));
  assert(requests.some(e=>e.eventType==='browser_error'&&e.details.message==='simulation error detail'));
  assert(!JSON.stringify(requests).includes(account.password));
  assert(!JSON.stringify(requests).includes('browser-test-secret'));
  assert(!errors.length,errors.join(';'));
  console.log(JSON.stringify({result:'PASS',capturedPosts:requests.length,anonymousLogin:true,fetchAndXHR:true,requestAndResponseBodies:true,
    unicodeCharacters:24000,unknownFields:true,secretsRedacted:true,queueDrained:true,consolePageErrors:errors.length,diagnostics}));
  await context.close();
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});

