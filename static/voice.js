'use strict';
let voiceClient=null,voiceConfig=null,voicePoll=null,voiceCall=null,voiceBusy=false,voiceDeadline=0;
const voiceSeen=new Set();
let voiceGeneration=0;
function voiceState(label,kind='') {
  $('orb').textContent=label;$('orb').className='orb'+(kind?' '+kind:'');
  $('foodRing').classList.toggle('fast',kind==='thinking');
}
function stopVoice() {
  voiceGeneration++;
  if(voiceClient)voiceClient.stop();
  clearTimeout(voicePoll);voicePoll=null;voiceCall=null;voiceBusy=false;
  if($('voice-dialog').open)$('voice-dialog').close();
}
async function checkVoicePlans() {
  if(!voiceCall||!token)return;
  const trackedCall=voiceCall,trackedGeneration=voiceGeneration;
  try {
    const response=await api('/voice/jobs?call_id='+encodeURIComponent(trackedCall));
    if(!token||trackedCall!==voiceCall||trackedGeneration!==voiceGeneration)return;
    for(const job of response.jobs) {
      if(voiceSeen.has(job.id))continue;
      if(job.status==='FAILED') {voiceSeen.add(job.id);$('status').textContent=job.error;voiceState('Try again');}
      else if(job.plan_id) {
        const p=await api('/recipe-plans/'+encodeURIComponent(job.plan_id));
        if(!token||trackedCall!==voiceCall||trackedGeneration!==voiceGeneration)return;
        voiceSeen.add(job.id);
        voiceClient?.stop();$('voice-dialog').close();openMealResult(p);await mealHistory();
        clearTimeout(voicePoll);voiceCall=null;return;
      } else {$('status').textContent='Building your basket. This can take a few minutes. You can end the call while we work.';voiceState('Planning…','thinking');}
    }
  } catch(e) {$('status').textContent=e.message;}
  if(voiceCall&&Date.now()<voiceDeadline)voicePoll=setTimeout(checkVoicePlans,2500);
  else if(voiceCall)$('status').textContent='Voice tracking ended. Check Recent meal plans for completed baskets.';
}
$('voice-open').onclick=async()=>{
  $('voice-dialog').showModal();$('status').textContent='Checking voice setup…';$('startBtn').disabled=true;
  try {
    voiceConfig=await api('/voice/config');
    $('status').textContent=voiceConfig.configured?'Ready. Tell us what you need.':'Voice setup needed: set VAPI_WEBHOOK_SECRET and configure the Vapi tools described in VOICE_SETUP.md.';
    $('startBtn').disabled=!voiceConfig.configured;
  } catch(e){$('status').textContent=e.message;}
};
$('voice-close').onclick=stopVoice;
$('voice-dialog').addEventListener('cancel',stopVoice);
$('startBtn').onclick=async()=>{
  if(voiceBusy||!voiceConfig?.configured)return;
  const generation=++voiceGeneration;
  voiceBusy=true;$('startBtn').disabled=true;voiceState('Connecting…');$('status').textContent='Connecting your microphone…';
  try {
    voiceConfig=await api('/voice/config');
    if(generation!==voiceGeneration)return;
    if(!voiceClient) {
      const {default:Vapi}=await import('https://esm.sh/@vapi-ai/web');
      if(generation!==voiceGeneration)return;
      voiceClient=new Vapi(voiceConfig.public_key);
      voiceClient.on('call-start',()=>{if(!$('voice-dialog').open){voiceClient.stop();return;}$('startBtn').style.display='none';$('stopBtn').style.display='inline-block';voiceState('Listening');$('status').textContent='Describe your meal, portions and delivery date.';});
      voiceClient.on('call-end',()=>{voiceBusy=false;$('startBtn').disabled=false;$('startBtn').style.display='inline-block';$('stopBtn').style.display='none';voiceState('Ready');$('status').textContent=voiceCall?'Call ended. Any basket being built will still appear here.':'Call ended.';});
      voiceClient.on('speech-start',()=>voiceState('Speaking','speaking'));
      voiceClient.on('speech-end',()=>voiceState('Listening'));
      voiceClient.on('message',msg=>{
        if(msg.type==='transcript'&&msg.transcriptType==='final')$('voice-caption').textContent=(msg.role==='user'?'You: ':'Assistant: ')+msg.transcript;
        if(msg.type==='tool-calls'){voiceState('Checking…','thinking');$('status').textContent='Checking your request…';}
      });
      voiceClient.on('error',()=>{voiceBusy=false;$('startBtn').disabled=false;$('startBtn').style.display='inline-block';$('stopBtn').style.display='none';voiceState('Try again');$('status').textContent='Could not connect the voice call. Check microphone permissions and your Vapi assistant setup.';});
    }
    clearTimeout(voicePoll);voiceCall=null;
    const call=await voiceClient.start(voiceConfig.assistant_id,{
      firstMessage:voiceConfig.first_message,
      variableValues:{current_date:voiceConfig.current_date,current_year:voiceConfig.current_date.slice(0,4)}
    });
    if(generation!==voiceGeneration){voiceClient.stop();return;}
    if(!call?.id)throw new Error('The voice service did not return a call ID. Check Vapi configuration.');
    voiceCall=call.id;voiceDeadline=Date.now()+20*60*1000;checkVoicePlans();
  } catch(e) {voiceBusy=false;$('startBtn').disabled=false;voiceState('Try again');$('status').textContent=e.message||'Voice could not start. Check microphone permissions.';voiceClient?.stop();}
};
$('stopBtn').onclick=()=>voiceClient?.stop();
