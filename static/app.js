'use strict';
const $ = id => document.getElementById(id);
let token = '', session = null, proposals = [], mealPlans = [], selectedMealId = null, policyState = null, selected = null, decisionTarget = null, decisionKind = '', loading = false, selectionRun = 0;
const money = value => value === null || value === undefined ? 'Unknown' : new Intl.NumberFormat('en-FI', {style:'currency', currency:'EUR', maximumFractionDigits:2}).format(Number(value));
const basketAmount = b => number(b.provided_quantity ?? b.litres)+' '+({L:'litres',KG:'kg',SALES_UNIT:'sales units'}[b.requested_unit||'L']||b.requested_unit);
const number = value => value === null || value === undefined ? 'Unknown' : new Intl.NumberFormat('en-FI', {maximumFractionDigits:3}).format(Number(value));
const dateText = value => { const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'}); };
const timestamp = value => { const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleString('en-GB', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit', timeZoneName:'short'}); };
const expired = p => p.expired || new Date(p.expires_at).getTime() <= Date.now();
const status = p => p.mock_order_id ? 'Mock order committed' : expired(p) && p.spending_status === 'PENDING' ? 'Expired' : ({PENDING:'Awaiting approval', APPROVED:'Approved', REJECTED:'Rejected', WITHIN_LIMIT:'Within authority', AUTO_AUTHORISED:'Auto-authorised'}[p.spending_status] || p.spending_status);
const kind = p => expired(p) && p.spending_status === 'PENDING' ? 'expired' : ({PENDING:'pending',APPROVED:'approved',REJECTED:'rejected',WITHIN_LIMIT:'approved', AUTO_AUTHORISED:'approved'}[p.spending_status] || '');
function icon(name) {
  const paths={meal:['M4 12h16','M6 12a6 6 0 0 1 12 0','M3 16h18','M10 4h4'],products:['M3 7l9-4 9 4-9 4-9-4Z','M3 7v10l9 4 9-4V7','M12 11v10'],voice:['M9 5a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0V5Z','M5 10v1a7 7 0 0 0 14 0v-1','M12 18v4','M8 22h8'],check:['m5 12 4 4L19 6'],shield:['M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7l-9-4Z','m8 12 3 3 5-6'],download:['M12 3v12','m7 10 5 5 5-5','M4 16v5h16v-5']};
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.classList.add('ui-icon');
  for(const d of paths[name]||paths.check){const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',d);svg.append(path);}return svg;
}
function mealState(p) {
  if(p.mock_order||p.status==='COMMITTED_MOCK')return {label:p.partial_order?'Partial mock order':'Mock order',group:'ordered',cls:'ordered'};
  if(p.status==='REJECTED')return {label:'Declined',group:'rejected',cls:'rejected'};
  if(p.status==='BLOCKED'||p.issues?.length)return {label:'Needs a change',group:'issues',cls:'blocked'};
  if(expired(p))return {label:'Expired',group:'expired',cls:'expired'};
  if(p.status==='AUTO_AUTHORISED')return {label:'Within authority',group:'autonomous',cls:'approved'};
  return {label:p.partial_order?'Review partial basket':'Needs review',group:'pending',cls:'pending'};
}
function productState(p) {
  if(p.mock_order_id)return {label:'Mock order',group:'ordered',cls:'ordered'};
  if(p.spending_status==='REJECTED')return {label:'Declined',group:'rejected',cls:'rejected'};
  if(expired(p))return {label:'Expired',group:'expired',cls:'expired'};
  if(p.basket?.reasons?.length)return {label:'Needs a change',group:'issues',cls:'blocked'};
  if(p.spending_status==='APPROVED')return {label:'Approved',group:'approved',cls:'approved'};
  if(['AUTO_AUTHORISED','WITHIN_LIMIT'].includes(p.spending_status))return {label:'Within authority',group:'autonomous',cls:'approved'};
  return {label:'Needs review',group:'pending',cls:'pending'};
}
function purchaseEntries(includeVersions=false) {
  const parents=new Set(mealPlans.map(p=>p.parent_plan).filter(Boolean));
  return [...proposals.map(p=>({type:'product',p,state:productState(p),title:p.basket.name,amount:p.basket.gross})),...mealPlans.filter(p=>includeVersions||!parents.has(p.id)).map(p=>({type:'meal',p,state:mealState(p),title:p.recipe.title,amount:p.total_gross_eur}))].sort((a,b)=>new Date(b.p.created_at)-new Date(a.p.created_at));
}
function syncPurchaseOverview() {
  const entries=purchaseEntries();
  $('pending-count').textContent=entries.filter(e=>e.state.group==='pending').length;
  $('approved-count').textContent=entries.filter(e=>e.state.group==='issues').length;
  $('expired-count').textContent=entries.filter(e=>e.state.group==='ordered').length;
  $('nav-review-count').textContent=entries.filter(e=>e.state.group==='pending').length;
  if(policyState)$('authority-amount').textContent=money(policyState.approval_limit_eur_including_tax);
  renderQueue();
}
function downloadJSON(data,name) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=element('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function element(tag, cls='', text='') { const node = document.createElement(tag); if(cls) node.className=cls; if(text) node.textContent=text; return node; }
function append(parent, ...children) { parent.append(...children); return parent; }
function pill(p) { return element('span', 'pill '+kind(p), status(p)); }
function notice(message, error=false) { $('notice').textContent=message; $('notice').className='notice'+(error?' error':''); }
async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'Authorization':'Bearer '+token, ...(options.body?{'Content-Type':'application/json'}:{}), ...options.headers}});
  const data = await response.json().catch(()=>({detail:'Unexpected server response.'}));
  if(!response.ok) { const detail=data.detail;let message=typeof detail==='string'?detail:detail?.message?detail.message+(detail.issues?.length?'\n'+detail.issues.join('\n'):''):Array.isArray(detail)?detail.map(e=>(e.loc||[]).filter(x=>x!=='body').join(' → ')+': '+e.msg).join('\n'):'The server could not complete this request.';if(response.status===401)message='Access token not accepted. Reconnect using the current token from your server terminal.';const error=new Error(message);error.status=response.status;throw error; }
  return data;
}
function reset() {
  if(typeof stopVoice==='function')stopVoice(); $('voice-open').classList.add('hidden');
  token=''; session=null; proposals=[];mealPlans=[];selectedMealId=null;policyState=null; selected=null; selectionRun++;
  $('workspace').classList.add('hidden'); $('login').classList.remove('hidden');
  $('plan-meal').classList.add('hidden'); $('recipe-dialog').close(); $('meal-result').replaceChildren(); $('meal-history').replaceChildren(); $('new-comparison').classList.add('hidden'); $('disconnect').classList.add('hidden');
  $('session-label').textContent='Local review workspace'; $('token').value='';
  $('planning-banner').classList.add('hidden');if(typeof clearMealProgress==='function')clearMealProgress(true);
  $('notice').classList.add('hidden'); $('compare-dialog').close(); $('decision-dialog').close();
}
$('disconnect').onclick=reset;
$('login-form').onsubmit=async event=>{
  event.preventDefault(); const button=event.submitter; button.disabled=true; $('login-error').textContent=''; token=$('token').value.trim();
  try {
    session=await api('/session');
    $('token').value=''; $('login').classList.add('hidden'); $('workspace').classList.remove('hidden');
    $('plan-meal').classList.remove('hidden'); $('voice-open').classList.remove('hidden'); $('disconnect').classList.remove('hidden'); $('new-comparison').classList.remove('hidden');
    $('session-label').textContent='Buyer '+session.customer+' · '+(session.role==='reviewer'?session.reviewer_name:'Agent access · decisions disabled');
    await refresh();
  } catch(error) { token=''; $('login-error').textContent=error.message; }
  finally { button.disabled=false; }
};
async function refresh() {
  if(loading || !token) return;
  loading=true; $('refresh').disabled=true;
  try {
    const [products,meals,policy]=await Promise.allSettled([api('/proposals?limit=100'),api('/recipe-plans'),api('/policy')]);
    if(!token)return;
    if(products.status==='fulfilled')proposals=products.value.proposals;else notice(products.reason.message,true);
    if(meals.status==='fulfilled')mealPlans=meals.value;else notice(meals.reason.message,true);
    if(policy.status==='fulfilled')policyState=policy.value;
    syncPurchaseOverview();
    if(selectedMealId&&mealPlans.some(p=>p.id===selectedMealId)) {
      const p=mealPlans.find(p=>p.id===selectedMealId);
      if(typeof mealPlan==='undefined'||!mealPlan||mealPlan.id!==p.id||mealPlan.status!==p.status||mealPlan.fingerprint!==p.fingerprint||mealPlan.expired!==p.expired)renderMeal(p,{inline:true});
    } else if(selected&&proposals.some(p=>p.id===selected.id))await selectProposal(selected.id);
    else {
      const first=purchaseEntries()[0];
      if(first)first.type==='meal'?await selectMeal(first.p.id):await selectProposal(first.p.id);
      else showEmptyDetail();
    }
  } catch(error) { notice(error.message,true); }
  finally { loading=false; $('refresh').disabled=false; }
}
function showEmptyDetail() {
  const empty=append(element('div','empty'),element('span','','↗'),element('h2','','Your next purchase starts here.'),element('p','','Plan a meal or compare products. Your agent will bring back one clear basket to review.'));
  const start=element('button','button dark','Plan a meal ↗');start.onclick=()=>$('plan-meal').click();empty.append(start);$('detail').replaceChildren(empty);$('detail').classList.remove('meal-page');
}
$('refresh').onclick=refresh;
$('filter').onchange=renderQueue;
$('purchase-search').oninput=renderQueue;
function renderQueue() {
  const filter=$('filter').value,query=$('purchase-search').value.toLowerCase().trim();
  const entries=purchaseEntries(filter==='versions');
  const visible=entries.filter(e=>(filter==='all'||filter==='versions'||e.state.group===filter)&&(!query||(e.title+' '+e.p.id).toLowerCase().includes(query)));
  $('queue-count').textContent=visible.length; $('proposal-list').replaceChildren();
  for(const b of document.querySelectorAll('[data-filter]'))b.classList.toggle('active',b.dataset.filter===filter);
  if(!visible.length)$('proposal-list').append(element('p','table-note',query?'No matching requests. Try another search.':'No requests in this view yet.'));
  for(const e of visible) {
    const p=e.p,isMeal=e.type==='meal',active=isMeal?selectedMealId===p.id:!selectedMealId&&selected?.id===p.id;
    const button=element('button','proposal-card'+(active?' selected':''));button.type='button';button.setAttribute('aria-pressed',String(active));
    const type=append(element('span','request-type'),icon(isMeal?'meal':'products'),element('span','',isMeal?'Meal plan':'Product request'));
    const badge=element('span','pill '+e.state.cls,e.state.label);
    append(button,append(element('div','card-top'),type,badge),element('h3','',e.title),element('div','card-sub',(isMeal?p.portions+' people':basketAmount(p.basket))+' · '+dateText(p.delivery_date)),append(element('div','card-bottom'),element('span','card-price',e.amount==null?'Needs a check':money(e.amount)),element('small','',e.amount==null?'': 'incl. tax')));
    button.onclick=()=>isMeal?selectMeal(p.id):selectProposal(p.id);$('proposal-list').append(button);
  }
}
async function selectMeal(id) {
  const run=++selectionRun;
  try {
    const p=mealPlans.find(p=>p.id===id)||await api('/recipe-plans/'+encodeURIComponent(id));if(run!==selectionRun)return;
    selected=null;selectedMealId=id;renderMeal(p,{inline:true});renderQueue();
  } catch(error){if(run===selectionRun)notice(error.message,true);}
}
function openMealResult(p) {
  selected=null;selectedMealId=p.id;selectionRun++;
  mealPlans=[p,...mealPlans.filter(x=>x.id!==p.id)];
  $('recipe-dialog').close();renderMeal(p,{inline:true});syncPurchaseOverview();
  $('detail').scrollIntoView({behavior:'smooth',block:'start'});
}
async function selectProposal(id) {
  selectedMealId=null;const run=++selectionRun;
  try {
    const p=await api('/proposals/'+encodeURIComponent(id)); if(run!==selectionRun)return;
    selected=p; renderQueue(); renderDetail(p);
    const alternatives=await api('/proposals/'+encodeURIComponent(id)+'/alternatives');
    if(run!==selectionRun)return; renderAlternatives(alternatives,p);
  } catch(error) { if(run===selectionRun)notice(error.message,true); }
}
function fact(label,value) { return append(element('div','fact'),element('span','',label),element('strong','',value)); }
function renderDetail(p) {
  $('detail').classList.remove('meal-page');
  const b=p.basket, head=element('div','detail-head');
  append(head,append(element('div','detail-top'),element('span','mono',p.id),pill(p)),element('h2','',b.name),element('p','detail-sub','SKU '+b.sku+' · Customer '+p.customer));
  const amount=element('div','amount',money(b.gross));amount.append(element('small','','Product subtotal including tax'));
  const limit=Number(p.policy.limit_eur_including_tax), over=Number(b.gross)-limit;
  const limitNote=append(element('div','limit-note'),element('div','','Autonomous limit '+money(limit)),element('strong','',over>0?money(over)+' above authority':'Within configured authority'));
  append(head,append(element('div','amount-row'),amount,limitNote));
  const download=element('button','subtle','Download structured order draft ↓');
  download.onclick=async()=>{download.disabled=true;try{const draft=await api('/proposals/'+encodeURIComponent(p.id)+'/order-draft');const url=URL.createObjectURL(new Blob([JSON.stringify(draft,null,2)],{type:'application/json'}));const link=element('a');link.href=url;link.download=p.id+'-order-draft.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notice(error.message,true);}finally{download.disabled=false;}};
  head.append(download);
  const body=element('div','detail-body');
  append(body,append(element('div','facts'),fact('Requested delivery',dateText(p.delivery_date)),fact('Basket quantity',basketAmount(b)),fact('Order quantity',number(b.quantity)+' '+b.sales_unit),fact('Product subtotal excluding tax',money(b.net))));
  if(expired(p)) body.append(append(element('div','callout blocked'),element('strong','','Review window has ended'),element('span','','This saved decision remains in history. Create a fresh comparison for a new proposal.')));
  for(const reason of b.reasons)body.append(append(element('div','callout blocked'),element('strong','','Readiness issue'),element('span','',reason)));
  for(const warning of b.warnings)body.append(append(element('div','callout'),element('strong','','Stock unknown · orderable under mock rules'),element('span','',warning)));
  body.append(append(element('div','callout info'),element('strong','','A spending decision, not an order submission'),element('span','','Delivery charges and deposits are excluded. No stock reservation or delivery guarantee is created.')));
  append(body,append(element('div','block-title'),element('h3','','Why this option?'),element('span','','EVIDENCE, NOT GUESSWORK')));
  body.append(element('p','table-note',(b.selection_reason||'Candidate evaluated against the saved purchase request.')+' Quantity calculated using '+b.conversion_source+'. '+(b.readiness.startsWith('CHECKS PASSED')?'Listed price and delivery checks passed at evaluation.':'See the recorded readiness issues above.')));
  const alternatives=element('div');alternatives.id='alternatives';alternatives.append(element('p','table-note','Loading original comparison…'));body.append(alternatives);
  append(body,append(element('div','block-title'),element('h3','','Decision history'),element('span','','SAVED AUDIT TRAIL')));
  const timeline=element('ol','timeline');
  for(const ev of p.events) append(timeline,append(element('li'),element('span','dot'),append(element('div'),element('strong','',({CREATED:'Purchase proposed',APPROVED:'Spending approved',REJECTED:'Spending rejected',AUTO_AUTHORISED:'Automatically authorised within policy',COMMITTED_MOCK:'Mock order committed',COMMIT_BLOCKED:'Mock commitment blocked'}[ev.action]||ev.action)+' · '+ev.actor),element('time','',timestamp(ev.at)),element('p','',ev.note))));
  body.append(timeline);
  if(b.evidence && Object.keys(b.evidence).length) {
    const proof=append(element('details','fingerprint'),element('summary','','Source evidence and validity'));
    for(const [key,value] of Object.entries(b.evidence)) if(value)proof.append(element('p','table-note',key.replaceAll('_',' ')+': '+value));
    if(b.product_labels?.length)proof.append(element('p','table-note','Recorded label codes: '+b.product_labels.join(', ')+'. Label codes are catalogue claims, not independently verified certificates.'));
    body.append(proof);
  }
  const fingerprint=append(element('details','fingerprint'),element('summary','','Exact basket fingerprint'),element('code','',p.fingerprint));body.append(fingerprint);
  if(p.mock_order_id)body.append(append(element('div','callout info'),element('strong','','Mock order committed · '+p.mock_order_id),element('span','','A local receipt is saved. No supplier order was submitted.')));
  const bar=element('div','decision-bar'), active=session.role==='reviewer'&&p.spending_status==='PENDING'&&!expired(p);
  const explanation=session.role!=='reviewer'?'Connect with the reviewer token to record decisions.':p.spending_status!=='PENDING'?(p.spending_status==='AUTO_AUTHORISED'?'Within configured authority; no human sign-off needed.':'Decision recorded for this exact basket.'):expired(p)?'Create a fresh comparison to continue.':'Review window ends '+timestamp(p.expires_at)+'.';
  append(bar,append(element('p'),element('strong','',active?'Your review is required.':status(p)),element('span','',explanation)));
  const reject=element('button','button reject','Reject'),approve=element('button','button approve','Approve spending ↗');
  reject.disabled=approve.disabled=!active;reject.onclick=()=>openDecision('reject');approve.onclick=()=>openDecision('approve');
  const buttons=element('div','decision-buttons');
  if(p.mock_order_id) {
    const receipt=element('button','button outline','Download mock receipt');
    receipt.onclick=async()=>{try{const data=await api('/orders/'+encodeURIComponent(p.mock_order_id));const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=element('a');link.href=url;link.download=p.mock_order_id+'-receipt.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notice(error.message,true);}};
    buttons.append(receipt);
  } else if(['APPROVED','AUTO_AUTHORISED','WITHIN_LIMIT'].includes(p.spending_status)&&!expired(p)) {
    const commit=element('button','button approve','Commit mock order');commit.onclick=()=>openDecision('commit');buttons.append(commit);
  } else buttons.append(reject,approve);
  bar.append(buttons);$('detail').replaceChildren(head,body,bar);
}
function renderAlternatives(data,p) {
  const host=$('alternatives');if(!host)return;host.replaceChildren(append(element('div','block-title'),element('h3','','Alternatives compared'),element('span','',data.offer_id?'ORIGINAL SNAPSHOT':'NO LINKED SNAPSHOT')));
  if(data.options.length) {
    const table=element('table'),header=element('tr'); for(const title of ['Product','Incl. tax','Assessment'])header.append(element('th','',title));
    table.append(append(element('thead'),header));const tbody=element('tbody');
    for(const option of data.options) {
      const row=element('tr',option.sku===p.basket.sku?'chosen':'');
      const name=append(element('td'),element('span','',option.name),element('span','sku',option.sku+(option.sku===p.basket.sku?' · selected':'')));
      const assessment=option.readiness.startsWith('CHECKS PASSED')?(option.stock_status==='UNKNOWN_ORDERABLE'?'Eligible · stock unknown':'Eligible'):option.reasons.join('; ');
      append(row,name,element('td','',money(option.gross)),element('td','',assessment));tbody.append(row);
    }
    table.append(tbody);host.append(append(element('div','table-wrap'),table));
  }
  host.append(element('p','table-note',data.message+(data.created_at?' Captured '+timestamp(data.created_at)+'.':'')+(data.expired?' The comparison review window has expired.':'')));
}
function openDecision(action) {
  if(!selected||expired(selected))return;
  if(action==='commit' ? !['APPROVED','AUTO_AUTHORISED','WITHIN_LIMIT'].includes(selected.spending_status)||selected.mock_order_id : selected.spending_status!=='PENDING')return;
  decisionTarget=structuredClone(selected);decisionKind=action;
  const yes=action==='approve', commit=action==='commit';
  $('decision-title').textContent=commit?'Commit a mock order?':yes?'Approve this spending?':'Reject this proposal?';
  $('confirm-decision').textContent=commit?'Recheck and commit mock order':yes?'Confirm approval':'Confirm rejection';
  $('decision-note').classList.toggle('hidden',commit);$('decision-note').labels[0].classList.toggle('hidden',commit);
  $('decision-help').textContent=commit?'The gateway will recheck price, availability and authority, then save a local receipt. Changes stop the commitment. No supplier order or payment is sent.':'This records a decision for this exact saved basket. It does not reserve stock or send a supplier order.';
  $('decision-summary').replaceChildren(element('strong','',decisionTarget.basket.name),element('div','',basketAmount(decisionTarget.basket)+' · '+money(decisionTarget.basket.gross)+' including tax'),element('div','',decisionTarget.id));
  $('decision-note').value='';$('decision-note').required=!yes&&!commit;$('note-required').textContent=yes?'(optional)':'(required)';$('decision-error').textContent='';$('decision-dialog').showModal();
}
for(const id of ['close-decision','cancel-decision'])$(id).onclick=()=>$('decision-dialog').close();
$('decision-form').onsubmit=async event=>{
  event.preventDefault();const button=$('confirm-decision');button.disabled=true;$('decision-error').textContent='';
  try {
    let message;
    if(decisionKind==='commit') {
      const order=await api('/orders',{method:'POST',body:JSON.stringify({proposal_id:decisionTarget.id})});
      message='Mock order '+order.id+' committed. Receipt saved; no supplier order sent.';
    } else {
      await api('/proposals/'+encodeURIComponent(decisionTarget.id)+'/'+decisionKind,{method:'POST',body:JSON.stringify({fingerprint:decisionTarget.fingerprint,note:$('decision-note').value.trim()})});
      message=decisionKind==='approve'?'Spending approved. You can now commit the mock order after fresh checks.':'Proposal rejected. Your reason is saved to the audit history.';
    }
    $('decision-dialog').close();notice(message);await refresh();
  } catch(error) { $('decision-error').textContent=error.message; }
  finally {button.disabled=false;}
};
$('new-comparison').onclick=()=>{
  $('compare-error').textContent='';$('comparison-results').replaceChildren();
  $('product-mode').value='catalogue';$('product-query').disabled=false;$('product-query').value='';$('requested-unit').value='KG';$('litres').value='10';$('product-diet').value='';
  const day=new Date();day.setDate(day.getDate()+2);$('delivery-date').value=day.toLocaleDateString('en-CA');$('compare-dialog').showModal();
};
$('close-compare').onclick=()=>$('compare-dialog').close();
function comparisonRequest(offset=0) {
  return {delivery_date:$('delivery-date').value,quantity:$('litres').value,unit:$('requested-unit').value,query:$('product-query').value.trim(),plain_milk:$('product-mode').value==='milk',required_claims:[...new Set([...$('required-claims').value.split(',').map(x=>x.trim()).filter(Boolean),$('product-diet').value].filter(Boolean))],scan_offset:offset};
}
function changeUnitMeaning() {
  $('litres').value='';
  $('unit-help').textContent=$('requested-unit').value==='SALES_UNIT'?'Enter the number of whole catalogue sales units (packs/cases). This is NOT the number of kilograms or litres.':'Enter a new quantity in the selected unit. Only products with recorded, supported conversions can be calculated.';
  $('comparison-results').replaceChildren();$('litres').focus();
}
$('requested-unit').onchange=changeUnitMeaning;
$('product-mode').onchange=()=>{
  $('product-query').disabled=$('product-mode').value==='milk';$('product-query').required=!$('product-query').disabled;if($('product-query').disabled)$('product-query').value='';
  $('requested-unit').value=$('product-mode').value==='milk'?'L':'SALES_UNIT';
  changeUnitMeaning();
};
$('compare-form').onsubmit=event=>{event.preventDefault();loadComparison(comparisonRequest());};
async function loadComparison(request) {
  const button=$('compare-submit');button.disabled=true;button.textContent='Checking price and availability…';$('compare-error').textContent='';$('comparison-results').replaceChildren();
  try {
    const offer=await api('/offers',{method:'POST',body:JSON.stringify(request)});
    const host=$('comparison-results'), summary=offer.search_summary;
    const ready=offer.options.filter(o=>o.readiness.startsWith('CHECKS PASSED'));
    host.append(element('p','table-note','Product subtotals include tax; delivery charges/deposits excluded. Only eligible options can be saved.'));
    const outcome=append(element('div','callout '+(ready.length?'info':'blocked')),element('strong','',ready.length?ready.length+' eligible option'+(ready.length===1?'':'s')+' found':'No eligible options in this checked batch'));
    if(summary)outcome.append(element('span','',summary.checked_count+' products checked from '+summary.match_count+' matching catalogue records. '+summary.convertible_count+' have a supported '+request.unit+' quantity conversion.'));
    if(!ready.length)outcome.append(element('p','table-note','Missing quantity conversion, passed cut-off and unavailable stock are separate issues. Sales units can resolve a missing conversion, but cannot override stock or delivery restrictions.'));
    host.append(outcome);
    if(summary?.missing_conversion_count && request.unit!=='SALES_UNIT') {
      const units=element('button','button outline','Use sales units instead');units.type='button';
      units.onclick=()=>{$('requested-unit').value='SALES_UNIT';changeUnitMeaning();};host.append(units);
    }
    const eligibleHost=element('div'), blockedHost=element('details','blocked-options');
    const blockedCount=offer.options.length-ready.length;
    if(blockedCount){blockedHost.open=!ready.length;blockedHost.append(element('summary','',blockedCount+' excluded or unresolved option'+(blockedCount===1?'':'s')));}
    for(const option of offer.options) {
      const eligible=option.readiness.startsWith('CHECKS PASSED');
      const choose=element('button','button '+(eligible?'dark':'outline'),eligible?'Review this option ↗':'Unavailable');choose.type='button';choose.disabled=!eligible;
      const priceText=option.gross!==null?money(option.gross)+' incl. tax':option.sales_unit_price_gross!==null&&option.sales_unit_price_gross!==undefined?money(option.sales_unit_price_gross)+' per '+option.sales_unit+' incl. tax':'Price unavailable';
      const quantityText=option.quantity===null?'Basket quantity cannot be calculated in '+request.unit:basketAmount(option);
      const text=append(element('div'),element('h3','',option.name),element('p','',priceText+' · '+quantityText),element('p','table-note',option.readiness+(option.reasons.length?' · '+option.reasons.join('; '):'')));
      choose.onclick=async()=>{
        choose.disabled=true;
        try {const p=await api('/proposals',{method:'POST',body:JSON.stringify({offer_id:offer.id,sku:option.sku})});$('compare-dialog').close();selected=p;selectedMealId=null;await refresh();notice(p.spending_status==='AUTO_AUTHORISED'?'Proposal '+p.id+' automatically authorised within configured authority. Commit a mock order after fresh checks.':'Proposal '+p.id+' saved. Review the exact basket before recording a decision.');}
        catch(error){$('compare-error').textContent=error.message;choose.disabled=false;}
      };
      (eligible?eligibleHost:blockedHost).append(append(element('div','comparison-option'+(eligible?' eligible-option':'')),text,choose));
    }
    host.append(eligibleHost);if(blockedCount)host.append(blockedHost);
    if(summary?.next_scan_offset!==null && summary?.next_scan_offset!==undefined) {
      const more=element('button','button outline','Check more matching products');more.type='button';
      more.onclick=()=>{
        const current=comparisonRequest(0), previous={...request,scan_offset:0};
        if(JSON.stringify(current)!==JSON.stringify(previous)){$('compare-error').textContent='Search criteria changed. Click Find eligible options to start a fresh comparison.';return;}
        loadComparison({...request,scan_offset:summary.next_scan_offset});
      };host.append(more);
    }
  } catch(error) {$('compare-error').textContent=error.message;}
  finally {button.disabled=false;button.textContent='Compare offers ↗';}
}
setInterval(()=>{if(token&&!document.hidden&&!$('decision-dialog').open&&!$('compare-dialog').open&&!$('recipe-dialog').open&&!document.activeElement?.matches('input,select,textarea'))refresh();},60000);
