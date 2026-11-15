"""Voice webhook contracts with offline recipe/provider fixtures."""
import json
import os
import unittest
from unittest.mock import patch
import test_recipe_agent as fixture

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.test=fixture.RecipeTests();self.test.setUp()
        self.env=patch.dict(os.environ,{'VAPI_WEBHOOK_SECRET':'voice-test-only','AIMO_RECIPE_AUTONOMY':'automatic','AIMO_RECIPE_MEASUREMENTS':'kitchen'})
        self.env.start();self.headers={'X-Vapi-Secret':'voice-test-only'}
    def tearDown(self):self.env.stop();self.test.tearDown()
    def payload(self,name='create_recipe_plan',args=None,tid='tool-1',cid='call-1'):
        return {'message':{'type':'tool-calls','call':{'id':cid},'toolCalls':[{'id':tid,'function':{'name':name,'arguments':args if args is not None else {'request':'Macaroni and milk for 200 people','portions':200,'delivery_date':self.test.fixture.day,'auto_commit':True}}}]}}
    def send(self,payload):return self.test.client.post('/vapi-webhook',headers=self.headers,json=payload)
    def test_voice_creates_review_only_basket_and_status(self):
        response=self.send(self.payload());self.assertEqual(response.status_code,200,response.text)
        job=json.loads(response.json()['results'][0]['result']);self.assertEqual(job['status'],'PLANNING')
        jobs=self.test.client.get('/voice/jobs?call_id=call-1',headers=self.test.reviewer).json()['jobs']
        self.assertEqual(jobs[0]['status'],'READY',jobs)
        plan=self.test.client.get('/recipe-plans/'+jobs[0]['plan_id'],headers=self.test.reviewer).json()
        self.assertEqual(plan['status'],'PENDING_REVIEW');self.assertIsNone(plan['mock_order'])
        result=self.send(self.payload('get_recipe_plan_status',{'job_id':job['id']},tid='status')).json()['results'][0]
        self.assertEqual(json.loads(result['result'])['basket_status'],'PENDING_REVIEW')
        self.assertEqual(self.test.commit(plan).status_code,200)
    def test_duplicate_webhook_reuses_job_without_repeating_model_calls(self):
        p=self.payload();a=self.send(p);calls=fixture.r.provider_call.call_count;b=self.send(p)
        self.assertEqual(json.loads(a.json()['results'][0]['result'])['id'],json.loads(b.json()['results'][0]['result'])['id'])
        self.assertEqual(fixture.r.provider_call.call_count,calls)
    def test_secret_required_and_no_public_job_lookup(self):
        p=self.payload()
        self.assertEqual(self.test.client.post('/vapi-webhook',json=p).status_code,401)
        self.assertEqual(self.test.client.get('/voice/jobs?call_id=call-1').status_code,401)
        self.assertEqual(self.test.client.get('/voice/config').status_code,401)
    def test_string_arguments_and_product_response(self):
        p=self.payload('search_products',json.dumps({'query':'macaroni'}))
        response=self.send(p).json()['results'][0];self.assertIn('products',json.loads(response['result']))
    def test_invalid_arguments_and_unknown_tools_return_every_result(self):
        p=self.payload(args='not JSON');p['message']['toolCalls'].append({'id':'t2','function':{'name':'approve_and_commit','arguments':{}}})
        results=self.send(p).json()['results'];self.assertEqual(len(results),2);self.assertTrue(all('error' in r for r in results))
        self.assertIn('error',self.send(self.payload(args={'request':'Dinner'})).json()['results'][0])
    def test_job_status_is_bound_to_voice_call(self):
        job=json.loads(self.send(self.payload()).json()['results'][0]['result'])
        result=self.send(self.payload('get_recipe_plan_status',{'job_id':job['id']},cid='another-call')).json()['results'][0]
        self.assertIn('error',result)
    def test_failure_is_not_reported_as_an_order(self):
        fixture.r.provider_call.side_effect=RuntimeError('hidden provider error')
        self.send(self.payload())
        jobs=self.test.client.get('/voice/jobs?call_id=call-1',headers=self.test.reviewer).json()['jobs']
        self.assertEqual(jobs[0]['status'],'FAILED');self.assertIsNone(jobs[0]['plan_id'])
        self.assertNotIn('hidden provider',jobs[0]['error'])

    def test_past_date_is_rejected_before_any_job_or_provider_call(self):
        p=self.payload();p['message']['toolCalls'][0]['function']['arguments']['delivery_date']='2024-10-27'
        calls=fixture.r.provider_call.call_count
        response=self.send(p).json()['results'][0]
        self.assertIn('2024-10-27 is in the past',response['error'])
        self.assertIn('Planning has NOT started',response['error'])
        jobs=self.test.client.get('/voice/jobs?call_id=call-1',headers=self.test.reviewer).json()['jobs']
        self.assertEqual(jobs,[]);self.assertNotIn('result',response)
        self.assertEqual(fixture.r.provider_call.call_count,calls)

    def test_date_error_can_be_corrected_in_the_same_call(self):
        p=self.payload();p['message']['toolCalls'][0]['function']['arguments']['delivery_date']='2024-10-27'
        self.assertIn('error',self.send(p).json()['results'][0])
        response=self.send(self.payload(tid='corrected-date')).json()['results'][0]
        self.assertEqual(json.loads(response['result'])['status'],'PLANNING')
        jobs=self.test.client.get('/voice/jobs?call_id=call-1',headers=self.test.reviewer).json()['jobs']
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['status'],'READY')

    def test_voice_config_provides_authoritative_date_without_private_keys(self):
        import aimo_api as g
        config=self.test.client.get('/voice/config',headers=self.test.reviewer).json()
        self.assertEqual(config['current_date'],g.core.utc_now().date().isoformat())
        self.assertIn(g.core.utc_now().strftime('%Y'),config['first_message'])
        self.assertNotIn('voice-test-only',json.dumps(config))

    def test_redacted_claude_failure_reaches_voice_ui(self):
        fixture.r.provider_call.side_effect=RuntimeError('Claude recipe provider HTTP 429. Rate limit or credit limit reached.')
        self.send(self.payload())
        job=self.test.client.get('/voice/jobs?call_id=call-1',headers=self.test.reviewer).json()['jobs'][0]
        self.assertEqual(job['error'],'Claude recipe provider HTTP 429. Rate limit or credit limit reached.')
        self.assertEqual(job['status'],'FAILED');self.assertIsNone(job['plan_id'])

    def test_diagnostics_redact_configured_secrets(self):
        fixture.r.provider_call.side_effect=RuntimeError('Claude recipe provider failed: voice-test-only')
        self.send(self.payload())
        job=self.test.client.get('/voice/jobs?call_id=call-1',headers=self.test.reviewer).json()['jobs'][0]
        self.assertNotIn('voice-test-only',job['error']);self.assertIn('[hidden]',job['error'])

if __name__=='__main__':unittest.main()
