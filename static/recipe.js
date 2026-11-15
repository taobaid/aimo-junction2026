'use strict';
let mealPlan=null,mealViewInline=false,mealLoading=false,mealTimer=null,mealRun=0;
function currentMealHost(){return mealViewInline?$('detail'):$('meal-result');}
function clearMealProgress(invalidate=false){
  if(invalidate)mealRun++;
  clearInterval(mealTimer);mealTimer=null;mealLoading=false;$('planning-banner').classList.add('hidden');$('meal-submit').disabled=false;
}
function showMealProgress(){
  const root=$('meal-result');root.classList.remove('meal-page');root.replaceChildren();$('recipe-form').hidden=true;
  const box=element('div','recipe-loading');
  box.append(element('span','spinner'),element('h3','','Your agent is on it.'),element('p','','Preparing recipe quantities and checking catalogue offers. Any proposed changes will be shown before you confirm.'));
  const skeleton=element('div','loading-skeleton');for(let i=0;i<3;i++)skeleton.append(element('span'));box.append(skeleton);
  const elapsed=element('p','elapsed','Request in progress…');box.append(elapsed,element('p','field-help','You can close this panel while we work. Keep this browser tab open. No order has been placed.'));root.append(box);
  $('planning-banner').classList.remove('hidden');const started=Date.now();
  mealTimer=setInterval(()=>{const seconds=Math.floor((Date.now()-started)/1000),text=(seconds<60?seconds+' seconds':Math.floor(seconds/60)+' min '+seconds%60+' sec')+' elapsed · waiting for the recipe and offers';elapsed.textContent=text;$('planning-elapsed').textContent=text;},1000);
}
$('plan-meal').onclick=async()=>{
  $('recipe-dialog').showModal();$('meal-error').textContent='';
  if(mealLoading)return;
  if(sessionStorage.getItem('aimo-recipe-job')){await resumeMealJob();return;}
  $('recipe-form').hidden=false;$('meal-result').replaceChildren();$('meal-result').classList.remove('meal-page');
  if(!$('meal-date').value)$('meal-date').value=$('delivery-date').value||new Date(Date.now()+3*86400000).toISOString().slice(0,10);
  try{
    const [c,measures]=await Promise.all([api('/recipe-capabilities'),api('/recipe-measures')]);
    const kitchenAllowed=session?.role==='reviewer'||measures.agent_kitchen_mode_allowed;
    $('meal-measures').options[1].disabled=!kitchenAllowed;if(!kitchenAllowed)$('meal-measures').value='strict';
    $('meal-measure-rules').replaceChildren();
    for(const rule of measures.profiles){const row=element('p','field-help',rule.label+': '+rule.grams+' g/'+rule.per+(rule.always_review?' · approval required':''));if(rule.source){const a=element('a','',' Reference ↗');a.href=rule.source;a.target='_blank';a.rel='noopener noreferrer';row.append(a);}$('meal-measure-rules').append(row);}
    $('recipe-config').textContent=c.configured?'Tell us the dish and headcount. We’ll bring back the basket.':'Server setup needed: '+c.setup_help;
    $('meal-control').options[1].disabled=session?.role!=='reviewer'&&!c.agent_automatic_mode_allowed;
    if($('meal-control').selectedOptions[0].disabled)$('meal-control').value='review';
    await mealHistory();
  }catch(e){$('meal-error').textContent=e.message;}
};
$('close-recipe').onclick=()=>$('recipe-dialog').close();
async function mealHistory(){
  const plans=await api('/recipe-plans');if(!token)return;
  mealPlans=plans;syncPurchaseOverview();$('meal-history').replaceChildren();
  for(const p of plans){const state=mealState(p),b=element('button','proposal-card');b.type='button';b.append(append(element('div','card-top'),element('span','','Meal plan'),element('span','pill '+state.cls,state.label)),element('h3','',p.recipe.title),element('div','card-sub',p.portions+' people · '+dateText(p.delivery_date)));b.onclick=()=>openMealResult(p);$('meal-history').append(b);}
  if(!plans.length)$('meal-history').textContent='Your meal plans will appear here.';
}
$('refresh-meals').onclick=()=>mealHistory().catch(e=>$('meal-error').textContent=e.message);
$('recipe-form').onsubmit=async e=>{
  e.preventDefault();if(mealLoading)return;const run=++mealRun,requestToken=token;
  mealLoading=true;$('meal-submit').disabled=true;$('meal-error').textContent='';showMealProgress();
  try{
    const automatic=$('meal-control').value==='automatic';
    const job=await api('/recipe-jobs',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({planning_mode:$('meal-planning-mode').value,request:$('meal-request').value,refresh_recipe:$('meal-fresh-recipe').checked,recipe_url:$('meal-recipe-url').value.trim(),recipe_text:$('meal-recipe-text').value.trim(),portions:Number($('meal-portions').value),delivery_date:$('meal-date').value,preferences:$('meal-preferences').value,autonomy:automatic?'automatic':'review',auto_commit:automatic,measurement_mode:$('meal-measures').value})});
    if(run!==mealRun||token!==requestToken)return;
    sessionStorage.setItem('aimo-recipe-job',job.id);
    const p=await awaitMealJob(job.id,run,requestToken);
    if(!p)return;
    openMealResult(p);await mealHistory();
  }catch(error){if(run===mealRun&&token===requestToken){$('meal-result').replaceChildren();$('recipe-form').hidden=false;$('meal-error').textContent=error.message;if(!$('recipe-dialog').open)notice('The basket could not be completed: '+error.message,true);}}
  finally{if(run===mealRun)clearMealProgress();}
};
async function awaitMealJob(id,run,requestToken){
  let failures=0;
  while(run===mealRun&&token===requestToken){
    let job;
    try{job=await api('/recipe-jobs/'+encodeURIComponent(id));failures=0;}
    catch(e){if(e.status===404||e.status===403){sessionStorage.removeItem('aimo-recipe-job');throw e;}if(++failures>=4)throw new Error('Connection interrupted. Reopen the planner to resume this saved job. '+e.message);await new Promise(resolve=>setTimeout(resolve,2000));continue;}
    if(job.status==='FAILED'){sessionStorage.removeItem('aimo-recipe-job');throw new Error(job.error||'Recipe planning could not complete.');}
    if(job.status==='READY'){
      const p=await api('/recipe-plans/'+encodeURIComponent(job.plan_id));sessionStorage.removeItem('aimo-recipe-job');return p;
    }
    await new Promise(resolve=>setTimeout(resolve,1500));
  }
  return null;
}
async function resumeMealJob(){
  const id=sessionStorage.getItem('aimo-recipe-job');if(!id||mealLoading||!token)return;
  const run=++mealRun,requestToken=token;mealLoading=true;showMealProgress();
  try{const p=await awaitMealJob(id,run,requestToken);if(p)openMealResult(p);}
  catch(e){if(run===mealRun){$('recipe-form').hidden=false;$('meal-result').replaceChildren();$('meal-error').textContent=e.message;}}
  finally{if(run===mealRun)clearMealProgress();}
}
function mealWorkflow(p){
  const done=[p.recipe.ingredient_list_complete&&!p.recipe.missing_ingredients?.length,!p.issues.length,Boolean(p.mock_order)||p.status==='REJECTED'||p.status==='AUTO_AUTHORISED',Boolean(p.mock_order)];
  const first=done.indexOf(false),ol=element('ol','workflow');
  (p.partial_order?['Recipe saved','Selected offers','Review','Partial order']:['Recipe','Offers','Decision','Mock order']).forEach((label,i)=>ol.append(append(element('li',done[i]?'done':i===first?'current':''),element('span','',done[i]?'✓':String(i+1)),element('strong','',label))));return ol;
}
function basketPreview(p){
  const box=element('section','basket-preview');box.append(append(element('h3'),element('span','','Basket items'),element('span','',p.order_lines.length+' product'+(p.order_lines.length===1?'':'s'))));
  if(!p.order_lines.length){box.append(element('p','table-note','No complete product lines are available yet. Review the exception above.'));return box;}
  const table=element('table'),head=element('tr');for(const t of ['Product','Order quantity','Availability','Incl. tax'])head.append(element('th','',t));table.append(append(element('thead'),head));const tbody=element('tbody');
  for(const line of p.order_lines){const unknown=line.stock_status==='UNKNOWN_ORDERABLE',ready=line.readiness.startsWith('CHECKS PASSED');tbody.append(append(element('tr'),append(element('td'),element('span','',line.name),element('span','sku','SKU '+line.sku)),element('td','',number(line.quantity)+' '+line.sales_unit),append(element('td'),element('span','stock-label'+(unknown?' unknown':''),ready?(unknown?'Orderable · stock unknown':'Checks passed'):'Needs a check')),element('td','',money(line.gross))));}
  table.append(tbody);box.append(append(element('div','table-wrap'),table),element('p','table-note','Order quantities use the catalogue sales unit shown. Prices include tax; delivery charges and deposits are excluded. Stock is not reserved.'));return box;
}
function renderMeal(p,{inline=false}={}){
  mealPlan=p;mealViewInline=inline;const panel=inline?$('detail'):$('meal-result');panel.classList.add('meal-page');panel.replaceChildren();if(!inline)$('recipe-form').hidden=true;
  const state=mealState(p),title=element('div','meal-title');title.append(append(element('div','detail-top'),append(element('span','request-type'),icon('meal'),element('span','','MEAL REQUEST')),element('span','pill '+state.cls,state.label)),element('h2','',p.recipe.title),element('p','',p.portions+' people · Delivery '+dateText(p.delivery_date)));
  if(p.recipe.provenance==='generated')title.append(element('p','field-help','AI recipe draft · review quantities and suitability before confirming.'));
  panel.append(title,mealWorkflow(p));const decision=element('div','meal-decision');panel.append(decision);
  if(p.partial_order){decision.append(element('h3','','Partial purchase · not a complete recipe'),element('p','',p.mock_order?'These ingredients were NOT ordered:':'These ingredients will NOT be ordered:'));const list=element('ul','excluded-items');for(const item of p.excluded_ingredients||[])list.append(element('li','',item.name+(item.reasons?.length?' — '+item.reasons.join('; '):'')));decision.append(list,element('p','field-help','The remaining products do not complete this recipe. Confirm only if you accept arranging the missing ingredients yourself or changing what you cook.'));}
  if((p.resolution_attempts||[]).some(a=>a.step==='TIME_BUDGET'))decision.append(element('p','field-help','Returned the current basket at the planning time limit. Checked items are kept; use the options below to resolve remaining items without researching the recipe again.'));
  if((p.resolution_attempts||[]).some(a=>a.step==='RECIPE_REUSED')&&!(p.changes||[]).some(c=>c.type==='RECIPE_SELECTION'))decision.append(element('p','field-help','Using the same successful recipe. Prices and availability checked again.'));
  if(p.mock_order){decision.append(element('h3','',p.partial_order?'Partial mock order confirmed':'Mock order confirmed'),element('p','','Receipt '+p.mock_order.id+' · '+timestamp(p.mock_order.committed_at)),element('p','field-help','Your decision and revalidated basket are saved. No supplier order or payment was sent.'));}
  else if(p.status==='REJECTED')decision.append(element('h3','','Basket declined'),element('p','','No order was recorded. Your decision is saved in the history.'));
  else if(!p.issues.length){
    const omitted=(p.changes||[]).filter(c=>c.type==='OMISSION');decision.append(element('h3','',p.partial_order?'Order available items only?':omitted.length?'Continue without '+omitted.map(c=>c.original.toLowerCase()).join(' and ')+'?':'Your basket is ready to review'));
    if(p.total_gross_eur!=null)decision.append(append(element('div','basket-total'),element('span','',money(p.total_gross_eur)),element('small','','Product subtotal including tax')));
    for(const change of p.changes||[]){if(change.type==='EXCLUSION')continue;decision.append(element('p','meal-change',change.type==='OMISSION'?'Leave out '+change.original.toLowerCase():change.original+' → '+change.replacement));for(const caveat of change.caveats||[])decision.append(element('p','field-help',caveat));}
    for(const reason of p.recipe.review_reasons||[])decision.append(element('p','field-help',reason));
    if(p.expired)decision.append(element('p','error','This basket has expired. Recheck the saved basket below before confirming.'));
    else if(session?.role==='reviewer'){
      const why=(p.changes||[]).length?'The proposed changes need your approval.':Number(p.total_gross_eur)>Number(p.approval_limit_eur)?'Above your agent’s '+money(p.approval_limit_eur)+' spending authority. Your approval is required.':'You chose to review this basket before confirmation.';
      decision.append(element('p','field-help',why));const actions=element('div','meal-actions');
      const yes=element('button','button dark',p.partial_order?'Yes, confirm partial basket':omitted.length?'Yes, continue without it':'Approve & confirm basket');yes.type='button';yes.dataset.mealCommit='true';yes.onclick=()=>mealAction(yes,`/recipe-plans/${p.id}/approve-and-commit`,{fingerprint:p.fingerprint});
      const no=element('button','button outline','Decline');no.type='button';no.onclick=()=>mealAction(no,`/recipe-plans/${p.id}/decline`,{fingerprint:p.fingerprint});actions.append(yes,no);decision.append(actions,element('p','field-help','Confirmation rechecks the basket and records a mock order. Delivery fees and deposits are excluded.'));
    }else decision.append(element('p','','Reviewer approval is required here. Connect with reviewer access to make a decision.'));
  }else{
    const omissions=p.omission_options||[],onlySeasonings=omissions.length&&p.issues.every(issue=>omissions.some(o=>issue.startsWith(o.name+':')));
    decision.append(element('h3','',onlySeasonings?'A small recipe change will get you moving':'Let’s resolve the remaining items'),element('p','',onlySeasonings?'Keep this recipe and leave out '+omissions.map(o=>o.name.toLowerCase()).join(' and ')+'. The flavour will be slightly different.':'The agent could not source every required item. No order has been placed.'));
    for(const issue of p.issues)decision.append(element('p','field-help',issue));
    if((p.partial_order_options||[]).length){const partial=element('button','button dark','Continue with available items');partial.type='button';partial.onclick=()=>mealAction(partial,`/recipe-plans/${p.id}/partial`,{fingerprint:p.fingerprint});decision.append(partial,element('p','field-help','Prepare a partial basket without: '+p.partial_order_options.map(i=>i.name).join(', ')+'. You will review the new total and confirm what is not being ordered. No recipe research is repeated.'));}
    if(omissions.length){const omit=element('button','button dark','Continue without '+omissions.map(o=>o.name.toLowerCase()).join(' and '));omit.type='button';omit.onclick=()=>mealAction(omit,`/recipe-plans/${p.id}/omit-seasonings`,{fingerprint:p.fingerprint});decision.append(omit);}
  }
  if(!p.mock_order&&p.status!=='REJECTED'&&p.recipe.ingredient_list_complete&&!p.recipe.missing_ingredients?.length&&(p.issues.length||(p.omission_options||[]).length||(p.changes||[]).some(c=>c.type==='OMISSION'))){const alternative=element('button','button outline','Find substitutes instead');alternative.type='button';alternative.onclick=()=>mealAction(alternative,`/recipe-plans/${p.id}/substitutes`,{fingerprint:p.fingerprint});decision.append(alternative,element('p','field-help','Substitute lookup keeps this recipe and checks only the missing ingredients.'));}
  if(p.mock_order&&p.total_gross_eur!=null)decision.append(append(element('div','basket-total'),element('span','',money(p.total_gross_eur)),element('small','','Confirmed product subtotal including tax')));
  panel.append(basketPreview(p));const secondary=element('div','meal-secondary');
  const exportButton=append(element('button','button outline export-button'),icon('download'),element('span','',p.mock_order?'Download receipt':'Download basket & evidence'));exportButton.type='button';exportButton.onclick=()=>downloadJSON(p.mock_order||p,(p.mock_order?.id||p.id)+'.json');
  const restart=element('button','button outline','Plan another meal');restart.type='button';restart.onclick=()=>$('plan-meal').click();secondary.append(exportButton,restart);panel.append(secondary);
  const details=element('details','meal-details');details.append(element('summary','','Recipe, quantities & decision history'));panel.append(details);
  let url=null;try{url=new URL(p.recipe.source_url);}catch{}
  if(url&&['https:','http:'].includes(url.protocol)){const link=element('a','table-note','Recipe source: '+p.recipe.source_title+' ↗');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';details.append(link);}else details.append(element('p','table-note',p.recipe.provenance==='generated'?'AI-planned recipe draft. Not a published source; quantities and suitability require review.':'Buyer-provided recipe. Quantities require review.'));
  details.append(element('p','field-help','Original yield: '+(p.recipe.source_servings??'unknown')+' servings. All quantities below are for '+p.portions+' people. Kitchen inventory has not been deducted.'));
  if(!p.recipe.ingredient_list_complete||p.recipe.missing_ingredients?.length)details.append(element('p','error',p.partial_order?'The source ingredient list is incomplete. This purchase covers selected products only.':'The source ingredient list is incomplete. A complete recipe is needed before confirmation.'));
  const edits=[];
  for(const row of p.ingredients){
    const card=element('div','option-card');card.append(element('strong','',row.name),element('p','',row.status==='NOT_ORDERED_PENDING_APPROVAL'?'Excluded from partial purchase · not ordered':row.status==='OMITTED_PENDING_APPROVAL'?'Proposed omission · not ordered':row.optional?'Optional · not ordered':row.required_quantity==null?'Quantity unresolved':(row.quantity_evidence?.estimated?'≈ ':'')+number(row.required_quantity)+' '+row.unit+' needed'),element('p','field-help','Source amount: '+row.original_measure));
    if(row.quantity_evidence){card.append(element('p','field-help',row.quantity_evidence.description));if(row.quantity_evidence.limitation)card.append(element('p','field-help',row.quantity_evidence.limitation));}
    card.append(element('p','field-help',row.selected_name?row.selected_name+' · SKU '+row.selected_sku:row.match_reason),element('p','field-help',[row.uncertainty,...row.reasons].filter(Boolean).join(' · ')));
    if(!row.optional&&!['OMITTED_PENDING_APPROVAL','NOT_ORDERED_PENDING_APPROVAL'].includes(row.status)&&!p.mock_order&&p.status!=='REJECTED'&&session?.role==='reviewer'){
      const editor=element('details');editor.append(element('summary','','Adjust total quantity'));
      const label=element('label','','Required amount for all '+p.portions+' people'),qty=element('input');qty.type='number';qty.min='0.000001';qty.step='any';qty.value=row.required_quantity??'';qty.setAttribute('aria-label','Total quantity for '+row.name);
      const unit=element('select');unit.setAttribute('aria-label','Unit for '+row.name);for(const [v,t] of [['KG','Kilograms'],['L','Litres'],['PIECE','Pieces']]){const option=element('option','',t);option.value=v;unit.append(option);}if(row.unit!=='UNRESOLVED')unit.value=row.unit;
      const changed=()=>{const commit=panel.querySelector('[data-meal-commit]');if(commit){commit.disabled=true;commit.textContent='Recheck to apply quantity edits';}};qty.oninput=changed;unit.onchange=changed;editor.append(label,qty,unit);card.append(editor);edits.push({id:row.id,qty,unit});
    }details.append(card);
  }
  if(!p.mock_order&&p.status!=='REJECTED'&&session?.role==='reviewer'){
    const rebuild=element('button','button outline','Recheck basket / apply quantity edits');rebuild.type='button';rebuild.onclick=()=>mealAction(rebuild,`/recipe-plans/${p.id}/rebuild`,{fingerprint:p.fingerprint,quantities:edits.filter(x=>x.qty.value).map(x=>({ingredient_id:x.id,quantity:x.qty.value,unit:x.unit.value}))});details.append(rebuild);
  }
  details.append(element('p','field-help','Agent spending authority: '+money(p.approval_limit_eur)+'. Product subtotals include tax; delivery fees and deposits are excluded.'));
  for(const text of p.notices)details.append(element('p','field-help',text));
  const audit=element('details','meal-audit');audit.append(element('summary','','Decision history & exact basket fingerprint'));const timeline=element('ol','timeline');
  for(const ev of p.events)timeline.append(append(element('li'),element('span','dot'),append(element('div'),element('strong','',({CREATED:'Basket prepared',DECLINED:'Basket declined',RECIPE_APPROVED_AND_COMMITTED:'Basket approved and mock order confirmed',AUTO_COMMITTED:'Mock order confirmed within authority'}[ev.action]||ev.action)+' · '+ev.actor),element('time','',timestamp(ev.at)),element('p','',ev.note))));
  audit.append(timeline,element('code','fingerprint',p.fingerprint));for(const attempt of p.resolution_attempts||[])audit.append(element('p','field-help',attempt.result));details.append(audit);
}
async function mealAction(button,path,body){
  const host=currentMealHost(),inline=mealViewInline,planId=mealPlan?.id,requestToken=token;
  const controls=[...host.querySelectorAll('button')].map(b=>({b,disabled:b.disabled}));for(const {b}of controls)b.disabled=true;$('meal-error').textContent='';
  const progress=element('p','callout info',path.endsWith('/substitutes')?'Checking substitutes for the saved recipe…':'Rechecking the exact basket…');host.prepend(progress);
  try{const p=await api(path,{method:'POST',body:JSON.stringify(body)});if(token!==requestToken)return;if(inline&&selectedMealId!==planId){notice('Your revised basket is ready. Find it in Purchases.');}else if(inline)openMealResult(p);else renderMeal(p);await mealHistory();}
  catch(e){if(token===requestToken){notice(e.message,true);if(!inline)$('meal-error').textContent=e.message;}}
  finally{progress.remove();for(const {b,disabled}of controls)if(b.isConnected)b.disabled=disabled;}
}
