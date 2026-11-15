"""Offline native Claude contract and full recipe integration tests."""
import copy
import json
import os
import unittest
from unittest.mock import patch
import httpx
import aimo_api as g
import claude_recipe as c
import recipe_agent as r
import test_api
from test_recipe_agent import RECIPE


def search_blocks():
    return [{"type":"server_tool_use","id":"srv-1","name":"web_search","input":{"query":"synthetic recipe fixture"}},
        {"type":"web_search_tool_result","tool_use_id":"srv-1","content":[{"type":"web_search_result","url":RECIPE['source_url'],"title":"Synthetic source","encrypted_content":"opaque-search-result"}]},
        {"type":"server_tool_use","id":"fetch-1","name":"web_fetch","input":{"url":RECIPE['source_url']}},
        {"type":"web_fetch_tool_result","tool_use_id":"fetch-1","content":{"type":"web_fetch_result","url":RECIPE['source_url'],"content":{"type":"document","source":{"type":"text","data":"Synthetic complete recipe: 4 portions, 400 g macaroni, 200 ml milk."},"title":"Synthetic source"}}},
        {"type":"text","text":"Synthetic source gives macaroni 400 g and milk 200 ml for 4 servings.",
         "citations":[{"type":"web_search_result_location","url":RECIPE['source_url'],"title":"Synthetic source"}]}]


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_api.GatewayTests();self.fixture.setUp();self.fixture.add_pasta()
        self.env=patch.dict(os.environ,{'RECIPE_PROVIDER':'anthropic','ANTHROPIC_API_KEY':'synthetic-claude-test-secret',
            'ANTHROPIC_MODEL':'claude-sonnet-4-6','ANTHROPIC_BASE_URL':'https://api.anthropic.com/v1',
            'ANTHROPIC_WORKSPACE_ID':'','RECIPE_MODEL':'','LLM_MODEL':'ignored-openai-model'})
        self.env.start();self.requests=[];self.reply_override=None
        real_client=httpx.Client
        self.http=patch('claude_recipe.httpx.Client',side_effect=lambda **kwargs:real_client(transport=httpx.MockTransport(self.handler),**kwargs))
        self.http.start()

    def tearDown(self):
        self.http.stop();self.env.stop();self.fixture.tearDown()

    def handler(self,request):
        body=json.loads(request.content);self.requests.append((request,body))
        if self.reply_override:return self.reply_override(request,body)
        if body.get('tools'):blocks=search_blocks()
        else:
            schema=body['output_config']['format']['schema']
            if 'ingredients' in schema['properties']:
                self.assertEqual(set(schema['properties']),set(r.SourcedRecipe.model_fields))
                self.assertIn('title',schema['required'])
                # Contract check for the real provider subset: the old wire
                # schema with maxItems=80 would be rejected with HTTP 400.
                if 'maxItems' in schema['properties']['ingredients']:
                    return httpx.Response(400,json={'error':{'message':'Unsupported schema maxItems'}})
                value=RECIPE
            else:
                items=json.loads(body['messages'][0]['content'])
                value={'matches':[{'ingredient_id':i['ingredient']['id'], 'product_ids':[p['sku'] for p in i['catalogue_candidates']][:1], 'reason':'Synthetic identity match','requires_review':False} for i in items]}
            blocks=[{'type':'text','text':json.dumps(value)}]
        return httpx.Response(200,json={'content':blocks,'stop_reason':'end_turn'})

    def test_native_search_extract_match_whole_basket_and_commit(self):
        response=self.fixture.client.post('/recipe-plans',headers=self.fixture.reviewer,json={'request':'Macaroni and milk for 200','portions':200,'delivery_date':self.fixture.day})
        self.assertEqual(response.status_code,201,response.text);p=response.json()
        self.assertEqual(p['status'],'PENDING_REVIEW');self.assertEqual(p['total_gross_eur'],'63.10')
        self.assertEqual(p['recipe']['source_url'],RECIPE['source_url']);self.assertEqual(len(self.requests),3)
        for req,body in self.requests:
            self.assertEqual(str(req.url),'https://api.anthropic.com/v1/messages')
            self.assertEqual(req.headers['x-api-key'],'synthetic-claude-test-secret')
            self.assertEqual(req.headers['anthropic-version'],'2023-06-01')
            self.assertNotIn('authorization',req.headers)
            self.assertEqual(body['model'],'claude-sonnet-4-6')
            self.assertNotIn('store',body);self.assertNotIn('instructions',body)
        self.assertNotIn('output_config',self.requests[0][1])
        self.assertEqual(self.requests[0][1]['tools'][0]['type'],'web_search_20250305')
        self.assertNotIn('tools',self.requests[1][1]);self.assertNotIn('tools',self.requests[2][1])
        committed=self.fixture.client.post('/recipe-plans/'+p['id']+'/approve-and-commit',headers=self.fixture.reviewer,json={'fingerprint':p['fingerprint']})
        self.assertEqual(committed.status_code,200,committed.text)
        self.assertFalse(committed.json()['mock_order']['upstream_order_submitted'])
        self.assertNotIn('synthetic-claude-test-secret',response.text+committed.text)

    def test_capabilities_never_expose_key(self):
        response=self.fixture.client.get('/recipe-capabilities',headers=self.fixture.agent)
        self.assertEqual(response.json()['provider'],'anthropic');self.assertTrue(response.json()['configured'])
        self.assertNotIn('synthetic-claude-test-secret',response.text)

    def test_missing_key_configuration_no_requests(self):
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':''}):
            with self.assertRaisesRegex(RuntimeError,'ANTHROPIC_API_KEY'):r.provider_call(g,{'input':'hello'})
            self.assertFalse(self.requests)

    def test_auto_select_claude_when_only_claude_key(self):
        with patch.dict(os.environ,{'RECIPE_PROVIDER':'','LLM_API_KEY':''}):
            self.assertEqual(c.configuration(g)['provider'],'anthropic')

    def test_explicit_openai_is_preserved(self):
        with patch.dict(os.environ,{'RECIPE_PROVIDER':'openai','LLM_API_KEY':'synthetic-openai','LLM_MODEL':'model-test'}):
            self.assertEqual(c.configuration(g)['provider'],'openai')
            self.assertEqual(c.configuration(g)['key'],'synthetic-openai')

    def test_http_errors_are_redacted(self):
        for status in (400,401,402,403,404,429,529):
            self.reply_override=lambda request,body:httpx.Response(status,json={'error':{'message':'synthetic-claude-test-secret'}})
            with self.assertRaisesRegex(RuntimeError,'HTTP '+str(status)) as error:r.provider_call(g,{'input':'test'})
            self.assertNotIn('synthetic-claude-test-secret',str(error.exception))

    def test_wire_schema_removes_bounds_but_local_recipe_limit_remains(self):
        from pydantic import ValidationError
        schema=r.schema_for(r.SourcedRecipe)
        converted=c.compatible_schema(schema)
        self.assertEqual(schema['properties']['ingredients']['maxItems'],80)
        self.assertNotIn('maxItems',converted['properties']['ingredients'])
        self.assertEqual(converted['properties']['ingredients']['minItems'],1)
        self.assertIn('maxItems=80',converted['properties']['ingredients']['description'])
        too_many={**RECIPE,'ingredients':[RECIPE['ingredients'][0]]*81}
        with self.assertRaises(ValidationError):r.SourcedRecipe.model_validate(too_many)

    def test_wire_schema_preserves_names_which_look_like_keywords(self):
        schema={'type':'object','properties':{'maxItems':{'type':'string','maxLength':20},'title':{'type':'string'}},'additionalProperties':False}
        converted=c.compatible_schema(schema)
        self.assertIn('maxItems',converted['properties']);self.assertIn('title',converted['properties'])
        self.assertNotIn('maxLength',converted['properties']['maxItems'])
        self.assertEqual(schema['properties']['maxItems']['maxLength'],20)

    def test_provider_error_identifies_failed_stage(self):
        self.reply_override=lambda request,body:httpx.Response(400,json={'error':{'message':'hidden'}})
        with self.assertRaisesRegex(RuntimeError,'HTTP 400 during recipe extraction'):
            r.json_model(g,r.SourcedRecipe,'Extract recipe',{})

    def test_no_actual_search_is_rejected(self):
        self.reply_override=lambda request,body:httpx.Response(200,json={'content':[{'type':'text','text':'I recall a recipe at '+RECIPE['source_url']}],'stop_reason':'end_turn'})
        with self.assertRaisesRegex(RuntimeError,'No retrieved recipe sources'):r.find_recipe(g,r.RecipeRequest(request='Macaroni',delivery_date=self.fixture.day))

    def test_search_tool_error_with_http_200_is_not_success(self):
        self.reply_override=lambda request,body:httpx.Response(200,json={'content':[{'type':'web_search_tool_result','content':{'type':'web_search_tool_result_error','error_code':'unavailable'}}],'stop_reason':'end_turn'})
        with self.assertRaisesRegex(RuntimeError,'web search failed'):r.provider_call(g,{'input':'test','tools':[{'type':'web_search'}]})

    def test_truncated_json_refused(self):
        self.reply_override=lambda request,body:httpx.Response(200,json={'content':[{'type':'text','text':'{"title":'}],'stop_reason':'max_tokens'})
        with self.assertRaisesRegex(RuntimeError,'incomplete'):r.provider_call(g,{'input':'test'})

    def test_pause_continuation_preserves_search_blocks(self):
        first=search_blocks()[:2]
        def reply(request,body):
            if len(self.requests)==1:return httpx.Response(200,json={'content':first,'stop_reason':'pause_turn'})
            self.assertEqual(body['messages'][1],{'role':'assistant','content':first})
            return httpx.Response(200,json={'content':search_blocks()[2:],'stop_reason':'end_turn'})
        self.reply_override=reply
        response=r.provider_call(g,{'input':'test','tools':[{'type':'web_search'}]})
        self.assertEqual(r.source_links(response)[0]['url'],RECIPE['source_url'])
        self.assertEqual(len(self.requests),2)

    def test_search_budget_is_bounded(self):
        self.reply_override=lambda request,body:httpx.Response(200,json={'content':search_blocks()[:2],'stop_reason':'pause_turn'})
        with self.assertRaisesRegex(RuntimeError,'incomplete'):r.provider_call(g,{'input':'test','tools':[{'type':'web_search'}]})
        self.assertEqual(len(self.requests),3)

    def test_model_cannot_inject_source_link_via_text_citation(self):
        blocks=search_blocks();blocks[-1]['citations'].append({'url':'https://example.com/not-returned','title':'fabrication'})
        self.assertNotIn('https://example.com/not-returned',[x['url'] for x in r.source_links(c.normalize(blocks,True))])

    def test_search_snippet_without_opened_recipe_is_not_source_evidence(self):
        blocks=search_blocks()[:2]+[search_blocks()[-1]]
        self.assertEqual(r.source_links(c.normalize(blocks,True)),[])

    def test_fetched_source_is_preserved(self):
        response=c.normalize(search_blocks(),True)
        self.assertEqual(r.source_links(response),[{'url':RECIPE['source_url'],'title':'Synthetic source'}])

    def test_network_failure_classification_is_redacted_and_not_retried(self):
        cases=[(httpx.ReadTimeout,'read timeout'),(httpx.ConnectTimeout,'connection timeout'),
               (httpx.ConnectError,'connection failed'),(httpx.ReadError,'transport failed'),
               (httpx.WriteTimeout,'request timed out')]
        for error_type,expected in cases:
            self.requests.clear()
            def fail(request,body):raise error_type('PRIVATE_TRANSPORT_DETAILS',request=request)
            self.reply_override=fail
            with self.assertRaisesRegex(RuntimeError,expected) as error:r.provider_call(g,{'input':'test','tools':[{'type':'web_search'}]})
            self.assertIn('recipe web research',str(error.exception))
            self.assertNotIn('PRIVATE_TRANSPORT_DETAILS',str(error.exception))
            self.assertEqual(len(self.requests),1)

    def test_non_json_html_does_not_expose_body(self):
        self.reply_override=lambda request,body:httpx.Response(200,text='<html>PRIVATE_GATEWAY_PAGE</html>',headers={'Content-Type':'text/html'})
        with self.assertRaisesRegex(RuntimeError,'non-JSON data') as error:r.provider_call(g,{'input':'test'})
        self.assertIn('text/html',str(error.exception));self.assertNotIn('PRIVATE_GATEWAY_PAGE',str(error.exception))

    def test_unexpected_json_shape_is_actionable(self):
        self.reply_override=lambda request,body:httpx.Response(200,json=['not a message'])
        with self.assertRaisesRegex(RuntimeError,'unexpected JSON shape'):r.provider_call(g,{'input':'test'})

    def test_long_read_timeout_keeps_connection_timeout_short(self):
        with patch.dict(os.environ,{'ANTHROPIC_READ_TIMEOUT':'600'}):r.provider_call(g,{'input':'test','tools':[{'type':'web_search'}]})
        self.assertEqual(self.requests[0][0].extensions['timeout']['read'],600)
        self.assertEqual(self.requests[0][0].extensions['timeout']['connect'],20)

    def test_invalid_timeout_fails_before_request(self):
        for value in ['NaN','0','601','not-seconds']:
            with patch.dict(os.environ,{'ANTHROPIC_READ_TIMEOUT':value}):
                with self.assertRaisesRegex(RuntimeError,'30–600'):r.provider_call(g,{'input':'test'})
        self.assertEqual(self.requests,[])

    def test_diagnostic_uses_short_message_and_no_supplier_api(self):
        import io
        import claude_check
        self.reply_override=lambda request,body:httpx.Response(200,json={'content':[{'type':'text','text':'OK'}],'stop_reason':'end_turn'})
        out=io.StringIO()
        with patch('sys.argv',['claude_check.py']),patch('sys.stdout',out):
            self.assertEqual(claude_check.main(),0)
        self.assertIn('PASS:',out.getvalue());self.assertNotIn('synthetic-claude-test-secret',out.getvalue())
        self.assertEqual(self.requests[0][1]['max_tokens'],32)
        self.assertFalse(g.core.api_post.called)


if __name__=='__main__':unittest.main()
