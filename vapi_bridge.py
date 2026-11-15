"""Vapi tools installed in the purchasing gateway; no second server required."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
from typing import Annotated
import uuid
import httpx
from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import ValidationError

PUBLIC_KEY='7433c014-2d40-4183-8ddc-aacbe2eeb8db'  # Public browser identifier supplied by the team.
ASSISTANT_ID='08565774-130d-45d4-a29b-b49494eb96c5'


def install_voice_routes(app,g):
    def connection():
        c=g.db()
        c.execute('''CREATE TABLE IF NOT EXISTS voice_jobs
          (id TEXT PRIMARY KEY, customer TEXT NOT NULL, call_id TEXT NOT NULL,
           tool_id TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL,
           plan_id TEXT, error TEXT, created_at TEXT NOT NULL,
           UNIQUE(customer,call_id,tool_id))''')
        c.commit();return c

    def present(row):
        return {k:row[k] for k in ('id','status','plan_id','error','created_at')}

    async def gateway(method,path,**kwargs):
        # Internal transport, not a model-controlled URL. Agent credential only.
        key=g.setting('AIMO_AGENT_TOKEN')
        if not key:raise RuntimeError('Voice agent credential is not configured.')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://gateway.local',timeout=None) as client:
            return await client.request(method,path,headers={'Authorization':'Bearer '+key},**kwargs)

    async def build(job_id,body):
        plan_id=None;error=None;status='FAILED'
        try:
            response=await gateway('POST','/recipe-plans',json=body)
            if response.is_success:
                plan_id=response.json()['id'];status='READY'
            else:
                error='Meal planning failed (HTTP '+str(response.status_code)+'). Check server configuration or revise the request.'
                if response.status_code in {502,503,504}:
                    detail=response.json().get('detail')
                    prefixes=('Claude ', 'Recipe ', 'Could not reach the recipe', 'No retrieved recipe',
                              'No usable recipe', 'Extracted recipe', 'The selected recipe',
                              'A recipe ', 'Use a public ', 'Set AIMO_API_KEY')
                    if isinstance(detail,str) and detail.startswith(prefixes):
                        # These are the gateway's intentionally redacted diagnostic
                        # messages, never raw HTTP/provider response bodies.
                        import os
                        for name,value in os.environ.items():
                            if name.endswith(('_KEY','_TOKEN','_SECRET')) and len(value)>=6:
                                detail=detail.replace(value,'[hidden]')
                        error=detail[:1200]
                if response.status_code==422:
                    detail=response.json().get('detail')
                    if detail=='Delivery date is in the past.':
                        error=('Delivery date '+body['delivery_date']+' is in the past. '
                               'The server date is '+g.core.utc_now().date().isoformat()+
                               '. Start a new request with a confirmed future delivery date.')
                    elif isinstance(detail,list):
                        allowed={'request','portions','delivery_date','preferences','recipe_url','recipe_text','measurement_mode','autonomy','auto_commit','resolve_exceptions'}
                        fields=sorted({str(e.get('loc',[])[-1]) for e in detail if isinstance(e,dict) and e.get('loc') and str(e['loc'][-1]) in allowed})
                        error='Meal request validation failed'+(': check '+', '.join(fields) if fields else '')+'. Start a new request with corrected values.'
        except Exception:
            error='Meal planning could not complete. Check the gateway connection and try a new request.'
        with closing(connection()) as c:
            c.execute('UPDATE voice_jobs SET status=?,plan_id=?,error=? WHERE id=?',(status,plan_id,error,job_id));c.commit()

    @app.get('/voice/config',operation_id='voice_configuration')
    def config(identity:Annotated[str,Depends(g.role)]):
        return {'public_key':g.setting('VAPI_PUBLIC_KEY',PUBLIC_KEY),
                'assistant_id':g.setting('VAPI_ASSISTANT_ID',ASSISTANT_ID),
                'configured':bool(g.setting('VAPI_WEBHOOK_SECRET') and g.setting('AIMO_AGENT_TOKEN')),
                'current_date':g.core.utc_now().date().isoformat(),
                'first_message':('The ordering date is '+g.core.utc_now().strftime('%A, %d %B %Y')+'. What would you like to cook, for how many people, and on which delivery date?'),
                'approval':'Voice creates review-only baskets. Confirm the exact basket on screen.'}

    @app.get('/voice/jobs',operation_id='voice_plan_jobs')
    def jobs(identity:Annotated[str,Depends(g.role)],call_id:str=Query(min_length=1,max_length=200)):
        with closing(connection()) as c:
            rows=c.execute('SELECT * FROM voice_jobs WHERE customer=? AND call_id=? ORDER BY created_at DESC LIMIT 10',(g.buyer(),call_id)).fetchall()
        return {'jobs':[present(row) for row in rows]}

    @app.post('/vapi-webhook',operation_id='vapi_tool_webhook')
    async def webhook(request:Request,background:BackgroundTasks):
        secret=g.setting('VAPI_WEBHOOK_SECRET')
        if not secret:raise HTTPException(503,'Voice webhook is not configured.')
        if not hmac.compare_digest(request.headers.get('X-Vapi-Secret','').encode(),secret.encode()):
            raise HTTPException(401,'Invalid voice webhook credential.')
        raw=await request.body()
        if len(raw)>100000:raise HTTPException(413,'Voice message too large.')
        try:payload=json.loads(raw)
        except (ValueError,TypeError):raise HTTPException(400,'Invalid JSON.') from None
        message=payload.get('message',{}) if isinstance(payload,dict) else {}
        if not isinstance(message,dict):raise HTTPException(400,'Invalid voice message.')
        if message.get('type')!='tool-calls':return {'status':'ok'}
        call=message.get('call',{})
        call_id=call.get('id') if isinstance(call,dict) else None
        if not isinstance(call_id,str) or not 1<=len(call_id)<=200:raise HTTPException(400,'A voice call ID is required.')
        if call.get('assistantId') and call['assistantId']!=g.setting('VAPI_ASSISTANT_ID',ASSISTANT_ID):
            raise HTTPException(403,'Unexpected voice assistant.')
        calls=message.get('toolCalls',message.get('toolCallList',[]))
        if not isinstance(calls,list) or len(calls)>8:raise HTTPException(400,'Invalid tool call batch.')
        results=[]
        for tool in calls:
            tid=tool.get('id') if isinstance(tool,dict) else None
            result={'toolCallId':tid}
            try:
                if not isinstance(tid,str) or not 1<=len(tid)<=200:raise ValueError('A tool call ID is required.')
                fn=tool.get('function',{});name=fn.get('name');args=fn.get('arguments',{})
                if isinstance(args,str):args=json.loads(args)
                if not isinstance(args,dict):raise ValueError('Tool arguments must be an object.')
                if name=='create_recipe_plan':
                    from recipe_agent import RecipeRequest
                    # No supplied reviewer identity, URL, price, authority or fingerprint accepted.
                    body=RecipeRequest(request=args.get('request',''),portions=args.get('portions'),
                        delivery_date=args.get('delivery_date'),preferences=args.get('preferences',''),recipe_url=args.get('recipe_url',''),recipe_text=args.get('recipe_text',''),
                        planning_mode=args.get('planning_mode','quick'),autonomy='review',auto_commit=False,
                        measurement_mode='kitchen' if g.setting('AIMO_RECIPE_MEASUREMENTS')=='kitchen' else 'strict').model_dump(mode='json')
                    today=g.core.utc_now().date().isoformat()
                    if body['delivery_date']<today:
                        result['error']=('Delivery date '+body['delivery_date']+' is in the past. The ordering date is '+today+
                            '. Planning has NOT started and no job or order was created. Ask the caller to confirm a future date including the year, then call create_recipe_plan again. Do not silently change the year or announce that a basket is being prepared.')
                        results.append(result)
                        continue
                    digest=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
                    with g._write_lock,closing(connection()) as c:
                        old=c.execute('SELECT * FROM voice_jobs WHERE customer=? AND call_id=? AND tool_id=?',(g.buyer(),call_id,tid)).fetchone()
                        if old:
                            if old['digest']!=digest:raise ValueError('This tool call already refers to a different request.')
                            job=present(old)
                        else:
                            cutoff=(datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat()
                            c.execute("UPDATE voice_jobs SET status='FAILED',error='Planning interrupted or timed out. Start a new request.' WHERE status='PLANNING' AND created_at<?",(cutoff,))
                            if c.execute("SELECT COUNT(*) FROM voice_jobs WHERE status='PLANNING'").fetchone()[0]>=4:
                                raise ValueError('Planning is busy. Wait for the existing meal plans to complete.')
                            jid='V-'+uuid.uuid4().hex[:16];now=datetime.now(timezone.utc).isoformat()
                            c.execute('INSERT INTO voice_jobs VALUES(?,?,?,?,?,?,?,?,?)',(jid,g.buyer(),call_id,tid,digest,'PLANNING',None,None,now));c.commit()
                            job={'id':jid,'status':'PLANNING','plan_id':None,'error':None,'created_at':now}
                            background.add_task(build,jid,body)
                    result['result']=json.dumps({**job,'message':'Meal planning started. It may take several minutes. If planning succeeds, the basket will appear on screen for Yes/No review. Nothing has been ordered. Use get_recipe_plan_status to check progress.'})
                elif name=='get_recipe_plan_status':
                    with closing(connection()) as c:
                        row=c.execute('SELECT * FROM voice_jobs WHERE id=? AND call_id=? AND customer=?',(args.get('job_id',''),call_id,g.buyer())).fetchone()
                    if not row:raise ValueError('Meal plan job not found for this call.')
                    data=present(row)
                    if row['plan_id']:
                        response=await gateway('GET','/recipe-plans/'+row['plan_id'])
                        if not response.is_success:raise ValueError('Saved meal plan is not available.')
                        plan=response.json()
                        data.update(title=plan['recipe']['title'],basket_status=plan['status'],total_gross_eur=plan['total_gross_eur'],changes=plan['changes'],issues=plan['issues'],message='Review the exact basket on screen. No supplier order has been sent.')
                    result['result']=json.dumps(data)
                elif name=='search_products':
                    query=args.get('query','')
                    if not isinstance(query,str) or not 1<=len(query)<=100:raise ValueError('Provide a product query of 1–100 characters.')
                    response=await gateway('GET','/products',params={'q':query,'limit':3})
                    if not response.is_success:raise ValueError('Product search is unavailable. Check gateway configuration.')
                    result['result']=json.dumps(response.json())
                else:raise ValueError('Unknown voice tool. Voice cannot approve or place orders.')
            except ValidationError:
                result['error']='Provide a meal request, a whole number of portions (1–10000), and a delivery date in YYYY-MM-DD format.'
            except (ValueError,TypeError,AttributeError):
                result['error']='Invalid tool request or unavailable job. Check the tool name, required fields and job ID; do not claim an order was placed.'
            except Exception:
                result['error']='The gateway could not complete this tool. Check the server and retry; no order was placed.'
            results.append(result)
        return {'results':results}
