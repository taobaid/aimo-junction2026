"""Run the key-free demo in a separate process so live fixtures remain isolated."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

class LaptopDemoTests(unittest.TestCase):
    def test_sample_mode_uses_real_guardrails_without_network(self):
        script=r'''
import asyncio,tempfile
from pathlib import Path
import httpx
# Any accidental external httpx call must fail; ASGI requests never use this transport.
def deny(*args,**kwargs):raise AssertionError('Unexpected network call')
httpx.HTTPTransport.handle_request=deny
from demo import create_demo
with tempfile.TemporaryDirectory() as folder:
 g,env,day=create_demo(Path(folder)/'demo.sqlite3')
 async def check():
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=g.app),base_url='http://sample.local') as c:
   reviewer={'Authorization':'Bearer '+env['AIMO_REVIEWER_TOKEN']}
   agent={'Authorization':'Bearer '+env['AIMO_AGENT_TOKEN']}
   assert (await c.get('/health')).json()['mode']=='offline sample demo'
   assert (await c.get('/recipe-plans')).status_code==401
   plans=(await c.get('/recipe-plans',headers=reviewer)).json()
   meal=plans[0]
   assert not meal['issues'],meal
   assert any(change['type']=='OMISSION' for change in meal['changes'])
   assert not any(line['sku']=='D-BEEF-A' for line in meal['order_lines'])
   assert any(line['sku']=='D-BEEF-B' for line in meal['order_lines'])
   assert (await c.post('/recipe-plans/'+meal['id']+'/approve-and-commit',headers=agent,json={'fingerprint':meal['fingerprint']})).status_code==403
   receipt=await c.post('/recipe-plans/'+meal['id']+'/approve-and-commit',headers=reviewer,json={'fingerprint':meal['fingerprint']})
   assert receipt.status_code==200,receipt.text
   assert receipt.json()['mock_order']['upstream_order_submitted'] is False
   proposals=(await c.get('/proposals',headers=reviewer)).json()['proposals']
   big=next(p for p in proposals if p['basket']['gross']=='1770.00')
   assert (await c.post('/orders',headers=agent,json={'proposal_id':big['id']})).status_code==409
   for dish in ['Chickpea curry','Lohikeitto']:
    response=await c.post('/recipe-plans',headers=reviewer,json={'request':dish,'portions':200,'delivery_date':day,'planning_mode':'quick'})
    assert response.status_code==201,response.text
    assert not response.json()['issues'],response.text
    assert response.json()['mock_order'] is None
   response=await c.post('/recipe-plans',headers=reviewer,json={'request':'An arbitrary unseen dish','portions':200,'delivery_date':day,'planning_mode':'quick'})
   assert response.status_code==502 and 'offline demo supports' in response.text
 asyncio.run(check())
'''
        result=subprocess.run([sys.executable,'-c',textwrap.dedent(script)],cwd=Path(__file__).parent,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_live_config_is_data_and_does_not_override_terminal(self):
        import tempfile
        from unittest.mock import patch
        from run_live import load_config
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AIMO_CUSTOMER':'terminal'}):
            path=Path(folder)/'config.env';path.write_text('# local\nAIMO_CUSTOMER=file\nSAMPLE_VALUE="$(not-executed)"\n')
            try:
                load_config(path)
                self.assertEqual(os.environ['AIMO_CUSTOMER'],'terminal')
                self.assertEqual(os.environ['SAMPLE_VALUE'],'$(not-executed)')
            finally:os.environ.pop('SAMPLE_VALUE',None)

if __name__=='__main__':unittest.main()
