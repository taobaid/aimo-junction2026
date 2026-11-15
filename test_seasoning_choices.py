"""Practical exception choices, including already saved blocked baskets."""
import copy
import json
import unittest
from unittest.mock import patch
import aimo_api as g
import recipe_agent as r
import test_recipe_agent as fixture

class SeasoningChoiceTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.RecipeTests();self.f.setUp()
        self.f.recipe={**copy.deepcopy(fixture.RECIPE),'title':'Spaghetti bolognese','ingredients':[
            copy.deepcopy(fixture.RECIPE['ingredients'][0]),
            {'name':'Worcestershire sauce','quantity':'0.02','unit':'L','original_measure':'20 ml','search_terms':['Worcestershire'],'optional':False,'uncertainty':None}]}
    def tearDown(self):self.f.tearDown()
    def plan(self,**kwargs):return self.f.plan(request='Spaghetti bolognese for 200 people',**kwargs)
    def change(self,p,path,body=None):return self.f.client.post('/recipe-plans/'+p['id']+'/'+path,headers=self.f.reviewer,json=body or {'fingerprint':p['fingerprint']})
    def test_missing_worcestershire_immediately_becomes_yes_no(self):
        p=self.plan();self.assertFalse(p['issues']);self.assertEqual(p['status'],'PENDING_REVIEW')
        self.assertTrue(any(c['type']=='OMISSION' and c['original']=='Worcestershire sauce' for c in p['changes']))
        self.assertFalse(any(call.args[1].get('text',{}).get('format',{}).get('name')=='recoveryplan' for call in r.provider_call.call_args_list))
        self.assertEqual(len([call for call in r.provider_call.call_args_list if 'tools' in call.args[1]]),1)
        result=self.f.commit(p);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(result.json()['mock_order']['lines']),1)
    def test_saved_blocked_plan_can_continue_without_research_or_model_calls(self):
        p=self.plan(recovery_mode='substitutes');self.assertEqual(p['status'],'BLOCKED')
        self.assertEqual(p['omission_options'][0]['name'],'Worcestershire sauce')
        calls=r.provider_call.call_count
        result=self.change(p,'omit-seasonings');self.assertEqual(result.status_code,200,result.text)
        new=result.json();self.assertFalse(new['issues']);self.assertEqual(new['status'],'PENDING_REVIEW')
        self.assertNotEqual(new['id'],p['id']);self.assertEqual(r.provider_call.call_count,calls)
        self.assertEqual(new['recipe']['source_url'],p['recipe']['source_url'])
        self.assertIsNone(new['mock_order']);self.assertEqual(self.f.commit(new).status_code,200)
    def test_main_ingredients_cannot_be_waived(self):
        self.f.recipe['ingredients'][1]['name']='Tomato sauce'
        self.f.recipe['ingredients'][1]['search_terms']=['tomato sauce']
        p=self.plan();self.assertEqual(p['status'],'BLOCKED');self.assertFalse(p['omission_options'])
        self.assertEqual(self.change(p,'omit-seasonings').status_code,409)
    def test_explicit_required_seasoning_is_not_omitted(self):
        p=self.plan(preferences='Must include Worcestershire sauce')
        self.assertEqual(p['status'],'BLOCKED');self.assertFalse(p['omission_options'])
        self.assertEqual(self.change(p,'omit-seasonings').status_code,409)
    def test_fresh_stock_failure_still_blocks_omission_basket(self):
        p=self.plan(recovery_mode='substitutes');self.f.fixture.stock_amount=0
        result=self.change(p,'omit-seasonings');self.assertEqual(result.status_code,200,result.text)
        new=result.json();self.assertEqual(new['status'],'BLOCKED');self.assertIsNone(new['mock_order'])
        self.assertEqual(self.f.commit(new).status_code,409)
    def test_substitutes_use_saved_recipe_and_keep_whole_basket_checks(self):
        p=self.plan()
        g._catalogue_cache.append({'id':'SOY','salesUnit':'ST','baseUnit':'ST','allowedLotSize':1,'units':[{'unitId':'ST','sizeInBaseUnits':1}],
            'synkkaData':{'names':[{'language':'en','value':'Soy sauce'}],'classifications':[],
            'unitConversions':[{'synkkaPackagingType':'BASE_UNIT_OR_EACH','volume':{'unit':'LTR','value':1}}]}})
        def reply(gateway,body):
            if 'tools' in body:raise AssertionError('Do not research the whole recipe again')
            if body.get('text',{}).get('format',{}).get('name')=='recoveryplan':
                return fixture.output({'alternatives':[{'ingredient_id':'I-2','replacements':[{'name':'Soy sauce','search_terms':['Soy sauce'],'factor':'1'}],'reason':'Proposed savoury seasoning replacement','caveats':['Introduces soy; review dietary suitability.']}]})
            return self.f.fake_provider(gateway,body)
        with patch.object(r,'provider_call',side_effect=reply):result=self.change(p,'substitutes')
        self.assertEqual(result.status_code,200,result.text);new=result.json()
        self.assertFalse(new['issues']);self.assertTrue(any(c['type']=='SUBSTITUTION' for c in new['changes']))
        self.assertFalse(any(c['type']=='OMISSION' for c in new['changes']))
        self.assertEqual(self.f.commit(new).status_code,200)
    def test_recipe_fingerprint_and_decline_are_respected(self):
        p=self.plan(recovery_mode='substitutes')
        self.assertEqual(self.change(p,'omit-seasonings',{'fingerprint':'0'*64}).status_code,409)
        self.assertEqual(self.change(p,'decline').status_code,200)
        self.assertEqual(self.change(p,'omit-seasonings').status_code,409)
    def test_missing_seasoning_measure_does_not_trigger_more_recipe_searches(self):
        self.f.recipe['ingredients'][1].update(quantity=None,unit='UNRESOLVED',original_measure='to taste')
        p=self.plan();self.assertFalse(p['issues'])
        self.assertEqual(len([call for call in r.provider_call.call_args_list if 'tools' in call.args[1]]),1)

if __name__=='__main__':unittest.main()
