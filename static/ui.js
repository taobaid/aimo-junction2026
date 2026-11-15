'use strict';
$('workspace-date').textContent=new Intl.DateTimeFormat('en-GB',{weekday:'short',day:'numeric',month:'long'}).format(new Date());
for(const [id,name] of [['plan-meal','meal'],['new-comparison','products'],['voice-open','voice']]){
  const host=$(id).querySelector('.start-icon');host.replaceChildren(icon(name));
}
for(const node of document.querySelectorAll('[data-close]'))node.onclick=()=>$(node.dataset.close).close();
function requireWorkspace(){if(token)return true;notice('Connect your workspace to start a purchase.');$('token').focus();return false;}
function chooseNav(id){for(const b of document.querySelectorAll('.sidebar nav .nav-item'))b.classList.toggle('active',b.id===id);}
function filterPurchases(value){$('filter').value=value;renderQueue();}
$('nav-overview').onclick=()=>{chooseNav('nav-overview');filterPurchases('all');window.scrollTo({top:0,behavior:'smooth'});};
$('nav-purchases').onclick=()=>{chooseNav('nav-purchases');filterPurchases('all');$('purchases-section').scrollIntoView({behavior:'smooth',block:'start'});};
$('nav-review').onclick=()=>{chooseNav('nav-review');filterPurchases('pending');$('purchases-section').scrollIntoView({behavior:'smooth',block:'start'});};
for(const b of document.querySelectorAll('[data-filter]'))b.onclick=()=>filterPurchases(b.dataset.filter);
$('nav-help').onclick=()=>$('help-dialog').showModal();
$('example-meal').onclick=()=>{if(!requireWorkspace())return;$('meal-request').value='Spaghetti bolognese for 200 people';$('meal-portions').value='200';$('plan-meal').click();};
$('example-milk').onclick=()=>{
  if(!requireWorkspace())return;$('new-comparison').click();$('product-mode').value='milk';$('product-mode').onchange();$('requested-unit').value='L';$('litres').value='1000';$('product-diet').value='FREE_FROM_LACTOSE';
};
$('view-planning').onclick=()=>$('recipe-dialog').showModal();
async function openPermissions(){
  $('policy-dialog').showModal();const host=$('policy-content');
  if(!token){host.replaceChildren(element('p','','Connect your workspace to see its spending authority and approval rules.'));return;}
  host.replaceChildren(element('p','','Loading your buying policy…'));
  try{
    const [policy,capabilities]=await Promise.all([api('/policy'),api('/recipe-capabilities')]);policyState=policy;syncPurchaseOverview();
    const value=append(element('div','policy-value'),element('span','','Configured agent spending authority'),element('strong','',money(policy.approval_limit_eur_including_tax)),element('span','','Product subtotal including tax. Delivery fees and deposits are excluded.'));
    host.replaceChildren(value);
    const rules=[['Spending beyond authority','A human must approve spending above this limit. The limit is configured by the buyer on the gateway.'],['Recipe changes need your decision','Substitutions, omissions and uncertain recipe facts are presented for review. Approval never overrides a stock, quantity or delivery blocker.'],['Fresh checks before commitment','Price, availability, permissions and the exact basket are validated again before a mock receipt is recorded.'],['Reviewer and agent are separate','Agent access can request and compare. Only reviewer access can record a human approval.']];
    for(const [title,text] of rules)host.append(append(element('div','policy-rule'),icon('shield'),append(element('div'),element('strong','',title),element('p','',text))));
    if(policy.buyer_required_claims.length||policy.buyer_required_origin)host.append(element('p','field-help','Mandatory buyer requirements: '+[...policy.buyer_required_claims,policy.buyer_required_origin?'Origin '+policy.buyer_required_origin:''].filter(Boolean).join(' · ')));
    const label=element('label','','Control for your next meal request');label.htmlFor='next-meal-control';const control=element('select');control.id='next-meal-control';
    for(const [v,t] of [['review','Review every basket before confirming'],['automatic','Automatically confirm unchanged baskets within authority']]){const option=element('option','',t);option.value=v;option.disabled=v==='automatic'&&session.role!=='reviewer'&&!capabilities.agent_automatic_mode_allowed;control.append(option);}
    control.value=$('meal-control').value;const apply=element('button','button dark','Use this control level');
    apply.onclick=()=>{$('meal-control').value=control.value;$('policy-dialog').close();notice(control.value==='automatic'?'Next meal: unchanged, eligible baskets may be mock-confirmed within authority. Recipe changes still need review.':'Next meal: you will review the full basket before confirmation.');};
    host.append(element('div','block-title'),label,control,element('p','field-help','Applies to the next meal request in this tab. It does not change the configured spending limit.'),apply);
  }catch(e){host.replaceChildren(element('p','error',e.message));}
}
$('nav-permissions').onclick=openPermissions;$('policy-card').onclick=openPermissions;

fetch('/health').then(r=>r.json()).then(h=>{
  if(h.mode==='offline sample demo'){
    const banner=element('p','offline-banner','OFFLINE SAMPLE DEMO · Fixed recipes, products and stock. No Claude or supplier calls. Resets on restart.');
    $('workspace').before(banner);$('voice-open').disabled=true;$('voice-open').title='Voice requires live Vapi setup';
    $('meal-planning-mode').value='quick';$('meal-planning-mode').options[1].disabled=true;
    const hint=element('p','field-help','Sample dishes: Spaghetti bolognese, Chickpea curry, Lohikeitto. Leave preferences blank. New dishes require live mode.');$('recipe-form').prepend(hint);
  }
}).catch(()=>{});
