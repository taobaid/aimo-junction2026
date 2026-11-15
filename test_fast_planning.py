"""Offline latency-path contracts, not live recipe quality or speed benchmarks."""
import copy
from datetime import date
import json
from decimal import Decimal
import os
import unittest
from unittest.mock import patch
import planning_budget as budget
import recipe_agent as r
import recipe_cache
import aimo_api as g
import test_recipe_agent as recipe_fixtures
RECIPE=recipe_fixtures.RECIPE
import test_dish_ordering as dish_fixtures
item=dish_fixtures.item


class QuickNativeTests(unittest.TestCase):
    def setUp(self):
        self.d=dish_fixtures.DishOrderingTests();self.d.setUp()
        self.env=patch.dict(os.environ,{'AIMO_RECIPE_CACHE':'0'});self.env.start()
    def tearDown(self):self.env.stop();self.d.tearDown()

    def test_varied_dishes_use_draft_and_match_without_web_research(self):
        cases=[('Lohikeitto',['Salmon','Potato']),('Dal tadka',['Red lentils','Onion']),
               ('Vegetable curry',['Chickpeas','Rice']),('Tofu stir fry',['Tofu','Broccoli']),
               ('Pancakes',['Flour','Butter']),('Apple crumble',['Apples','Oats']),
               ('Spaghetti bolognese',['Spaghetti','Beef mince']),('Pumpkin soup',['Pumpkin','Carrot'])]
        for index,(dish,foods) in enumerate(cases):
            with self.subTest(dish=dish):
                for n,food in enumerate(foods):self.d.add(f'Q{index}-{n}',food+' ingredient pack')
                self.d.recipe={**copy.deepcopy(RECIPE),'title':dish,'source_url':'','provenance':'generated',
                    'ingredients':[item(food,'0.4','KG','400 g',food) for food in foods]}
                before=len(self.d.native.requests)
                p=self.d.plan(planning_mode='quick',autonomy='automatic',auto_commit=True)
                self.assertEqual(self.d.searches,0)
                self.assertEqual(len(self.d.native.requests)-before,2) # draft + one identity match
                self.assertEqual(p['recipe']['provenance'],'generated');self.assertEqual(p['sources'],[])
                self.assertEqual(p['recipe']['source_url'],'');self.assertTrue(p['recipe']['review_reasons'])
                self.assertFalse(p['issues'],p['issues']);self.assertEqual(p['status'],'PENDING_REVIEW')
                self.assertIsNone(p['mock_order']);self.assertEqual(Decimal(p['ingredients'][0]['required_quantity']),Decimal('20'))

    def test_quick_missing_staple_does_not_research_another_recipe(self):
        self.d.recipe={**copy.deepcopy(RECIPE),'source_url':'','ingredients':[item('Nonexistent staple','0.5','KG','500 g')]}
        p=self.d.plan(planning_mode='quick')
        self.assertEqual(self.d.searches,0);self.assertEqual(p['status'],'BLOCKED')
        self.assertTrue(p['order_lines']==[]);self.assertEqual(self.d.approve(p).status_code,409)

    def test_draft_cannot_forge_a_published_source(self):
        response=self.d.f.client.post('/recipe-plans',headers=self.d.f.reviewer,
            json={'request':'Bolognese','delivery_date':self.d.f.day,'planning_mode':'quick'})
        self.assertEqual(response.status_code,502)
        self.assertIn('invented source URL',response.json()['detail'])

    def test_ambiguous_draft_remains_blocked_without_recipe_research(self):
        self.d.recipe={**copy.deepcopy(RECIPE),'source_url':'','ingredient_list_complete':False,
                       'missing_ingredients':['Dish meaning needs clarification']}
        p=self.d.plan(planning_mode='quick',request='Something ambiguous')
        self.assertEqual(p['status'],'BLOCKED');self.assertEqual(p['order_lines'],[])
        self.assertEqual(self.d.searches,0);self.assertEqual(self.d.approve(p).status_code,409)

    def test_quick_preferences_and_mandatory_claims_reach_claude(self):
        self.d.recipe={**copy.deepcopy(RECIPE),'source_url':''}
        p=self.d.plan(planning_mode='quick',preferences='No nuts')
        draft=[body for _,body in self.d.native.requests if 'AI-GENERATED DRAFT' in body.get('system','')][0]
        data=json.loads(draft['messages'][0]['content'])
        self.assertEqual(data['preferences'],'No nuts');self.assertIn('mandatory_claims',data)
        self.assertEqual(p['status'],'PENDING_REVIEW')

    def test_native_timeout_is_clamped_to_remaining_budget(self):
        import claude_recipe
        self.d.recipe={**copy.deepcopy(RECIPE),'source_url':''}
        import httpx
        self.d.native.reply_override=lambda request,body:httpx.Response(200,json={'content':[{'type':'text','text':'OK'}],'stop_reason':'end_turn'})
        with patch.object(budget.time,'monotonic',return_value=100):
            with budget.scope(g):
                with patch.object(budget.time,'monotonic',return_value=270):
                    claude_recipe.call(g,{'instructions':'Short fixture response','input':'Test'},claude_recipe.configuration(g))
        request=self.d.native.requests[-1][0]
        self.assertLessEqual(request.extensions['timeout']['read'],10)
        self.assertLessEqual(request.extensions['timeout']['connect'],10)


class FastPlanningTests(unittest.TestCase):
    def setUp(self):
        self.f=recipe_fixtures.RecipeTests();self.f.setUp()
        self.env=patch.dict(os.environ,{'AIMO_RECIPE_CACHE':'0'});self.env.start()
        self.body={'request':'Macaroni and milk','portions':200,'delivery_date':self.f.fixture.day,'planning_mode':'quick'}
    def tearDown(self):self.env.stop();self.f.tearDown()
    def test_quick_and_published_cache_keys_are_separate(self):
        a=r.RecipeRequest(**self.body)
        self.assertNotEqual(recipe_cache.key(g,a),recipe_cache.key(g,a.model_copy(update={'planning_mode':'published'})))
    def test_explicit_recipe_text_takes_priority_over_quick(self):
        self.f.recipe['source_url']=''
        p=self.f.plan(planning_mode='quick',recipe_text='4 servings: 400 g macaroni, 200 ml milk')
        self.assertEqual(p['recipe']['provenance'],'buyer')
        self.assertFalse(any('AI-GENERATED DRAFT' in c.args[1].get('instructions','') for c in r.provider_call.call_args_list))
    def test_empty_catalogue_candidates_do_not_cost_a_match_call(self):
        rows=r.scaled_ingredients(r.SourcedRecipe.model_validate(RECIPE),200)
        with patch.object(r,'json_model') as model:
            result=r.match_candidates(g,rows,{i['id']:[] for i in rows})
        model.assert_not_called();self.assertEqual(len(result),2)
    def test_time_budget_keeps_checked_partial_basket_and_blocks_commit(self):
        ingredients=r.scaled_ingredients(r.SourcedRecipe.model_validate(RECIPE),200)
        candidates=r.collect_candidates(g,ingredients);matches=r.match_candidates(g,ingredients,candidates)
        def upstream(endpoint,payload,key):
            response=self.f.fixture.mock_upstream(endpoint,payload,key)
            if endpoint=='/api/availability':
                for row in response['products']:
                    if row['productId']=='PASTA':row['scheduleLines'][0]['availableAmount']=0
            return response
        g.core.api_post.side_effect=upstream
        assessment=r.quote_recipe(g,ingredients,candidates,matches,date.fromisoformat(self.f.fixture.day))
        checkpoint=(ingredients,candidates,matches,[],[],assessment)
        def interrupted(*args):
            budget.checkpoint(checkpoint)
            raise budget.PlanningTimeout('Synthetic expired budget')
        with patch.object(r,'prepare_recipe_basket',side_effect=interrupted):p=self.f.plan(planning_mode='quick')
        self.assertEqual(p['status'],'BLOCKED');self.assertTrue(p['ingredients'])
        self.assertEqual(len(p['order_lines']),1) # checked milk retained while pasta is missing
        self.assertTrue(any(a['step']=='TIME_BUDGET' for a in p['resolution_attempts']))
        self.assertEqual(self.f.commit(p).status_code,409)
    def test_time_budget_before_matching_returns_recipe_without_invented_offers(self):
        with patch.object(r,'prepare_recipe_basket',side_effect=budget.PlanningTimeout('Synthetic expired budget')):
            p=self.f.plan(planning_mode='quick')
        self.assertEqual(p['status'],'BLOCKED');self.assertEqual(p['order_lines'],[])
        self.assertEqual(Decimal(p['ingredients'][0]['required_quantity']),Decimal('20'))
        self.assertEqual(self.f.commit(p).status_code,409)
    def test_time_budget_without_recipe_returns_clear_504(self):
        with patch.object(r,'find_recipe',side_effect=budget.PlanningTimeout('Recipe planning time budget reached during model call.')):
            response=self.f.client.post('/recipe-plans',headers=self.f.reviewer,json=self.body)
        self.assertEqual(response.status_code,504)
    def test_budget_uses_remaining_time_and_is_cleared_after_failure(self):
        with patch.object(budget.time,'monotonic',return_value=10):
            with budget.scope(g):
                with patch.object(budget.time,'monotonic',return_value=185):
                    self.assertEqual(budget.timeout(300),5)
                with patch.object(budget.time,'monotonic',return_value=191):
                    with self.assertRaises(budget.PlanningTimeout):budget.check()
        self.assertEqual(budget.remaining(),600)
    def test_budget_does_not_wait_past_deadline_for_supplier_lock(self):
        from unittest.mock import Mock
        mutex=Mock();mutex.acquire.return_value=False
        with budget.scope(g),patch.object(budget,'remaining',return_value=3):
            with self.assertRaises(budget.PlanningTimeout):
                with budget.lock(mutex):self.fail('Should not enter unavailable supplier lock')
        mutex.acquire.assert_called_once_with(timeout=3);mutex.release.assert_not_called()
    def test_invalid_budget_configuration_is_rejected(self):
        for value in ['0','nan','inf','bad','601']:
            with self.subTest(value=value),patch.dict(os.environ,{'AIMO_PLANNING_SECONDS':value}):
                with self.assertRaises(RuntimeError):
                    with budget.scope(g):pass
    def start(self,key='test-request-001',body=None,headers=None):
        return self.f.client.post('/recipe-jobs',headers={**(headers or self.f.reviewer),'Idempotency-Key':key},json=body or self.body)
    def test_background_job_finishes_and_duplicate_key_does_not_repeat_work(self):
        first=self.start();self.assertEqual(first.status_code,202,first.text)
        jid=first.json()['id'];calls=r.provider_call.call_count
        ready=self.f.client.get('/recipe-jobs/'+jid,headers=self.f.reviewer).json()
        self.assertEqual(ready['status'],'READY');self.assertTrue(ready['plan_id'])
        again=self.start();self.assertEqual(again.json()['id'],jid)
        self.assertEqual(r.provider_call.call_count,calls)
        p=self.f.client.get('/recipe-plans/'+ready['plan_id'],headers=self.f.reviewer).json()
        self.assertEqual(p['status'],'PENDING_REVIEW');self.assertIsNone(p['mock_order'])
    def test_background_idempotency_conflict_auth_and_validation(self):
        self.start()
        self.assertEqual(self.start(body={**self.body,'portions':201}).status_code,409)
        self.assertEqual(self.f.client.post('/recipe-jobs',json=self.body).status_code,401)
        self.assertEqual(self.f.client.get('/recipe-jobs/J-missing').status_code,401)
        self.assertEqual(self.start(key='new-request-002',body={**self.body,'delivery_date':'2020-01-01'}).status_code,422)
        self.assertEqual(self.start(key='new-request-003',body={**self.body,'autonomy':'automatic'},headers=self.f.agent).status_code,403)
    def test_background_failure_reports_redacted_error_and_can_be_polled(self):
        with patch.object(r,'source_meal',side_effect=RuntimeError('Claude HTTP 529 temporarily overloaded')):
            response=self.start()
        result=self.f.client.get('/recipe-jobs/'+response.json()['id'],headers=self.f.reviewer).json()
        self.assertEqual(result['status'],'FAILED');self.assertIn('529',result['error']);self.assertIsNone(result['plan_id'])
    def test_restarted_job_is_not_left_spinning(self):
        response=self.start();jid=response.json()['id']
        with g.db() as c:c.execute("UPDATE recipe_jobs SET status='PLANNING',worker='old-process' WHERE id=?",(jid,))
        result=self.f.client.get('/recipe-jobs/'+jid,headers=self.f.reviewer).json()
        self.assertEqual(result['status'],'FAILED');self.assertIn('restarted',result['error'])
    def test_job_is_hidden_from_another_buyer(self):
        jid=self.start().json()['id']
        with patch.dict(os.environ,{'AIMO_CUSTOMER':'other-buyer'}):
            self.assertEqual(self.f.client.get('/recipe-jobs/'+jid,headers=self.f.reviewer).status_code,404)

if __name__=='__main__':unittest.main()
