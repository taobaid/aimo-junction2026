"""Automatic shortage recovery, explicit Yes/No, and whole-basket checks."""
import copy
from datetime import timedelta
from decimal import Decimal
import json
import os
import unittest
from unittest.mock import patch
import aimo_api as g
import recipe_agent as r
import recipe_recovery as recovery
import test_recipe_agent as fixture


def food(name,qty,unit,measure,term):
    return {'name':name,'quantity':qty,'unit':unit,'original_measure':measure,'search_terms':[term],'optional':False,'uncertainty':None}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.test=fixture.RecipeTests();self.test.setUp()
        self.blocked={'WINE','PAPRIKA','WORCESTER'};self.stock={}
        self.test.recipe={**copy.deepcopy(fixture.RECIPE),'ingredients':[
            food('Macaroni','0.4','KG','400 g','macaroni'),
            food('Red wine','0.1','L','100 ml','red wine'),
            food('Paprika','0.02','KG','20 g','paprika'),
            food('Worcestershire sauce','0.02','L','20 ml','worcestershire'),
            food('Water (pasta cooking)',None,'UNRESOLVED','as needed','water'),
            food('Fresh garlic',None,'UNRESOLVED','1 head','fresh garlic')]}
        self.add('WINE','red wine',unit='L');self.add('PAPRIKA','paprika',unit='KG');self.add('WORCESTER','worcestershire',unit='L')
        self.add('BROTH','ready beef broth',unit='L');self.add('SMOKED','smoked seasoning',unit='KG')
        self.add('SOY','soy sauce',unit='L');self.add('VINEGAR','vinegar',unit='L');self.add('GARLIC','fresh garlic',unit='KG')
        self.alternatives=[
            {'ingredient_id':'I-2','replacements':[{'name':'Ready beef broth','search_terms':['ready beef broth'],'factor':'1'}],'reason':'Replace cooking wine with ready-to-use broth.','caveats':['The sauce will have a different acidity and flavour.']},
            {'ingredient_id':'I-3','replacements':[{'name':'Smoked seasoning','search_terms':['smoked seasoning'],'factor':'1'}],'reason':'Use an available recipe-compatible seasoning.','caveats':['Adds a smoky flavour; proposed recipe change.']},
            {'ingredient_id':'I-4','replacements':[{'name':'Soy sauce','search_terms':['soy sauce'],'factor':'0.5'},{'name':'Vinegar','search_terms':['vinegar'],'factor':'0.1'}],'reason':'Proposed savoury/acid replacement for the unavailable sauce.','caveats':['Soy is introduced; this is not certified allergen-safe.']}]
        self.test.provider.stop()
        self.provider=patch.object(r,'provider_call',side_effect=self.model);self.provider.start()
        g.core.api_post.side_effect=self.upstream

    def tearDown(self):
        self.provider.stop();self.test.tearDown()

    def add(self,pid,name,unit='KG'):
        measure={'netWeight':{'unit':'KGM','value':1}} if unit=='KG' else {'volume':{'unit':'LTR','value':1}}
        g._catalogue_cache.append({'id':pid,'salesUnit':'ST','baseUnit':'ST','allowedLotSize':0.01,'units':[{'unitId':'ST','sizeInBaseUnits':1}],
            'synkkaData':{'names':[{'language':'en','value':name}],'classifications':[], 'unitConversions':[{'synkkaPackagingType':'BASE_UNIT_OR_EACH',**measure}]}})

    def upstream(self,endpoint,payload,key):
        result=self.test.fixture.mock_upstream(endpoint,payload,key)
        if endpoint=='/api/availability':
            for product in result['products']:
                if product['productId'] in self.blocked:product['scheduleLines']=[]
                elif product['productId'] in self.stock:product['scheduleLines'][0]['availableAmount']=self.stock[product['productId']]
        return result

    def model(self,gateway,body):
        if body.get('text',{}).get('format',{}).get('name')=='recoveryplan':return fixture.output({'alternatives':self.alternatives})
        return self.test.fake_provider(gateway,body)

    def plan(self,**kwargs):
        kwargs.setdefault('recovery_mode','substitutes')
        return self.test.plan(measurement_mode='kitchen',autonomy='automatic',auto_commit=True,**kwargs)

    def test_stockouts_and_cooking_water_become_one_yes_no_plan(self):
        p=self.plan();self.assertEqual(p['status'],'PENDING_REVIEW');self.assertFalse(p['issues'])
        self.assertEqual(len([c for c in p['changes'] if c['type']=='SUBSTITUTION']),3)
        self.assertTrue(any(c['type']=='KITCHEN_SUPPLY' for c in p['changes']))
        self.assertEqual(next(i for i in p['ingredients'] if i['name']=='Water (pasta cooking)')['status'],'KITCHEN_SUPPLIED')
        self.assertEqual(Decimal(next(i for i in p['ingredients'] if i['name']=='Fresh garlic')['required_quantity']),Decimal('1.2'))
        self.assertFalse(any(b['sku'] in self.blocked for b in p['order_lines']))
        self.assertIsNone(p['mock_order'])
        yes=self.test.commit(p);self.assertEqual(yes.status_code,200,yes.text)
        receipt=yes.json()['mock_order'];self.assertFalse(receipt['upstream_order_submitted'])
        self.assertEqual(len(receipt['accepted_changes']),4)
        self.assertEqual(self.test.commit(p).json()['mock_order']['id'],receipt['id'])

    def test_no_is_saved_and_prevents_later_yes_on_same_plan(self):
        p=self.plan();path='/recipe-plans/'+p['id']+'/decline';body={'fingerprint':p['fingerprint']}
        self.assertEqual(self.test.client.post(path,headers=self.test.agent,json=body).status_code,403)
        response=self.test.client.post(path,headers=self.test.reviewer,json=body)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['status'],'REJECTED')
        again=self.test.client.post(path,headers=self.test.reviewer,json=body).json()
        self.assertEqual(len([e for e in again['events'] if e['action']=='DECLINED']),1)
        self.assertEqual(self.test.commit(p).status_code,409);self.assertIsNone(again['mock_order'])

    def test_changed_stock_still_blocks_yes(self):
        p=self.plan();self.blocked.add('BROTH')
        self.assertEqual(self.test.commit(p).status_code,409)

    def test_no_suitable_substitute_never_creates_partial_order(self):
        self.blocked.update({'BROTH','SMOKED','SOY','VINEGAR'})
        p=self.plan();self.assertEqual(p['status'],'BLOCKED')
        self.assertIsNone(p['mock_order']);self.assertEqual(self.test.commit(p).status_code,409)

    def test_all_parts_of_a_substitute_blend_are_required(self):
        self.blocked.add('VINEGAR');p=self.plan()
        self.assertEqual(p['status'],'BLOCKED')
        self.assertFalse(any(i.get('substitute_for')=='I-4' for i in p['ingredients']))

    def test_generic_water_rule_excludes_foods_and_bottled_products(self):
        for name in ['Water chestnuts','Orange blossom water','Sparkling water','Bottled water']:
            self.assertFalse(recovery.kitchen_water({'name':name}))
        self.assertTrue(recovery.kitchen_water({'name':'Water (pasta cooking)'}))

    def test_disabling_recovery_retains_original_blockers(self):
        p=self.plan(resolve_exceptions=False);self.assertEqual(p['status'],'BLOCKED');self.assertEqual(p['changes'],[])

    def test_same_ingredient_alternate_offer_is_tried_first(self):
        self.test.recipe['ingredients']=self.test.recipe['ingredients'][:2]
        self.add('WINE2','red wine alternative',unit='L')
        # Initial matcher intentionally chooses only the unavailable first SKU.
        p=self.plan();self.assertFalse(p['issues'])
        self.assertTrue(any(c['type']=='ALTERNATE_OFFER' for c in p['changes']))
        self.assertFalse(any(c['type']=='SUBSTITUTION' for c in p['changes']))

    def test_hard_claims_still_filter_replacement_products(self):
        for product in g._catalogue_cache:
            if product['id'] not in {'BROTH','SOY','VINEGAR','SMOKED'}:
                product['synkkaData']['classifications']=[{'name':'nutritionalClaim','values':[{'id':'FREE_FROM_GLUTEN'}]}]
        with patch.dict(os.environ,{'AIMO_REQUIRED_CLAIMS':'FREE_FROM_GLUTEN'}):
            p=self.plan();self.assertEqual(p['status'],'BLOCKED');self.assertEqual(self.test.commit(p).status_code,409)

    def test_substitute_stock_is_checked_for_the_combined_basket(self):
        self.test.recipe['ingredients']=[food('Ready beef broth','0.1','L','100 ml','ready beef broth'),
            food('Red wine','0.1','L','100 ml','red wine')]
        self.alternatives=self.alternatives[:1]
        self.stock['BROTH']=6  # Each 5 L line fits alone, combined 10 L does not.
        p=self.plan();self.assertEqual(p['status'],'BLOCKED')
        self.assertFalse(any(c['type']=='SUBSTITUTION' for c in p['changes']))

    def test_bolognese_can_be_approved_without_unavailable_wine(self):
        self.test.recipe['title']='Spaghetti bolognese'
        self.test.recipe['ingredients']=self.test.recipe['ingredients'][:2]
        self.alternatives=[]
        p=self.plan(recovery_mode='practical');self.assertEqual(p['status'],'PENDING_REVIEW');self.assertFalse(p['issues'])
        self.assertEqual(p['changes'][0]['type'],'OMISSION')
        self.assertEqual(p['ingredients'][1]['status'],'OMITTED_PENDING_APPROVAL')
        self.assertFalse(any(b['sku']=='WINE' for b in p['order_lines']))
        self.assertIsNone(p['mock_order'])
        yes=self.test.commit(p);self.assertEqual(yes.status_code,200,yes.text)
        self.assertEqual(yes.json()['mock_order']['accepted_changes'][0]['type'],'OMISSION')

    def test_explicit_wine_preference_is_not_omitted(self):
        self.test.recipe['title']='Spaghetti bolognese'
        self.test.recipe['ingredients']=self.test.recipe['ingredients'][:2]
        self.alternatives=[]
        p=self.plan(preferences='Must include red wine')
        self.assertEqual(p['status'],'BLOCKED');self.assertFalse(p['changes'])

    def test_main_ingredients_are_not_omitted(self):
        self.test.recipe['title']='Spaghetti bolognese'
        self.test.recipe['ingredients']=self.test.recipe['ingredients'][:1]
        self.blocked.add('P1');self.alternatives=[]
        # Unknown ingredient quantities still block; they are not silently dropped.
        self.test.recipe['ingredients'][0]['quantity']=None
        self.test.recipe['ingredients'][0]['unit']='UNRESOLVED'
        self.test.recipe['ingredients'][0]['original_measure']='unknown'
        p=self.plan();self.assertEqual(p['status'],'BLOCKED')
        self.assertFalse(any(c['type']=='OMISSION' for c in p['changes']))


if __name__=='__main__':unittest.main()
