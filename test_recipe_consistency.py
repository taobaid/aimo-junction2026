"""Successful terminal recipe -> same UI recipe, with fresh supplier evidence."""
import copy
from datetime import date,timedelta
from decimal import Decimal
import json
import os
import unittest
from unittest.mock import patch
import aimo_api as g
import recipe_agent as r
import recipe_cache as cache
import test_recipe_agent as fixtures

class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.RecipeTests();self.f.setUp()
        self.env=patch.dict(os.environ,{'AIMO_RECIPE_CACHE':'1'});self.env.start()
        self.request=r.RecipeRequest(request='Macaroni and milk',portions=200,delivery_date=self.f.fixture.day,measurement_mode='kitchen')
    def tearDown(self):self.env.stop();self.f.tearDown()
    def seed(self):return r.source_meal(g,self.request)
    def test_successful_terminal_source_is_reused_by_ui_without_new_search(self):
        recipe,_,prepared=self.seed();self.assertFalse(prepared[-1][2])
        calls=g.core.api_post.call_count
        def reply(gateway,body):
            if 'tools' in body:raise AssertionError('UI must not independently search after the successful local check')
            return self.f.fake_provider(gateway,body)
        with patch.object(r,'provider_call',side_effect=reply):
            p=self.f.plan(request='Macaroni and milk for 200 people',measurement_mode='kitchen')
        self.assertFalse(p['issues']);self.assertEqual(p['recipe']['source_url'],recipe.source_url)
        self.assertEqual(p['recipe']['ingredients'],recipe.model_dump()['ingredients'])
        self.assertTrue(any(a['step']=='RECIPE_REUSED' for a in p['resolution_attempts']))
        self.assertGreater(g.core.api_post.call_count,calls)
        self.assertIsNone(p['mock_order'])
    def test_cached_source_never_reuses_stock_or_an_order_approval(self):
        self.seed();self.f.fixture.stock_amount=0
        def reply(gateway,body):
            if 'tools' in body:raise RuntimeError('No retrieved recipe sources were returned.')
            return self.f.fake_provider(gateway,body)
        with patch.object(r,'provider_call',side_effect=reply):p=self.f.plan(measurement_mode='kitchen')
        self.assertEqual(p['status'],'BLOCKED');self.assertIsNone(p['mock_order'])
        self.assertEqual(self.f.commit(p).status_code,409)
    def test_preference_measurement_buyer_and_model_changes_do_not_share_recipe(self):
        self.seed()
        self.assertIsNone(cache.load(g,self.request.model_copy(update={'preferences':'no dairy'}),r.SourcedRecipe))
        self.assertIsNone(cache.load(g,self.request.model_copy(update={'measurement_mode':'strict'}),r.SourcedRecipe))
        with patch.dict(os.environ,{'AIMO_CUSTOMER':'another-buyer'}):self.assertIsNone(cache.load(g,self.request,r.SourcedRecipe))
        with patch.dict(os.environ,{'RECIPE_MODEL':'another-model'}):self.assertIsNone(cache.load(g,self.request,r.SourcedRecipe))
    def test_refresh_flag_bypasses_recipe_reuse(self):
        self.seed()
        self.assertIsNone(cache.load(g,self.request.model_copy(update={'refresh_recipe':True}),r.SourcedRecipe))
    def test_bad_or_expired_cache_is_not_used(self):
        self.seed();now=g.core.utc_now()
        with patch.object(g.core,'utc_now',return_value=now+timedelta(days=2)):
            self.assertIsNone(cache.load(g,self.request,r.SourcedRecipe))
        with g.db() as c:c.execute("UPDATE successful_recipe_sources SET payload=payload||' '")
        self.assertIsNone(cache.load(g,self.request,r.SourcedRecipe))
    def test_failed_basket_never_seeds_a_successful_recipe(self):
        self.f.fixture.stock_amount=0;self.seed()
        self.assertIsNone(cache.load(g,self.request,r.SourcedRecipe))
    def test_explicit_recipe_text_and_url_do_not_reuse_other_recipes(self):
        self.seed()
        self.assertIsNone(cache.load(g,self.request.model_copy(update={'recipe_text':'My exact ingredients'}),r.SourcedRecipe))
        self.assertIsNone(cache.load(g,self.request.model_copy(update={'recipe_url':'https://example.com/chosen'}),r.SourcedRecipe))
    def test_explicit_spaghetti_weights_with_labels_are_converted_without_guessing(self):
        for raw in ['400 g dried spaghetti','Dried spaghetti: 400 g','400 g spaghetti (dry)']:
            with self.subTest(measure=raw):
                recipe=r.SourcedRecipe.model_validate({**copy.deepcopy(fixtures.RECIPE),'ingredients':[
                    {'name':'Dried spaghetti','quantity':None,'unit':'UNRESOLVED','original_measure':raw,'search_terms':['spaghetti'],'optional':False,'uncertainty':None}]})
                self.assertEqual(r.scaled_ingredients(recipe,200)[0]['required_quantity'],Decimal('20'))
    def test_explicit_per_person_spaghetti_is_scaled_once(self):
        for raw in ['200 g per person','200 g per person × 8']:
            recipe=r.SourcedRecipe.model_validate({**copy.deepcopy(fixtures.RECIPE),'source_servings':'8','ingredients':[
                {'name':'Dried spaghetti','quantity':None,'unit':'UNRESOLVED','original_measure':raw,'search_terms':['spaghetti'],'optional':False,'uncertainty':None}]})
            self.assertEqual(r.scaled_ingredients(recipe,200)[0]['required_quantity'],Decimal('40'))
        recipe.ingredients[0].original_measure='200 g per person × 4'
        self.assertIsNone(r.scaled_ingredients(recipe,200)[0]['required_quantity'])

if __name__=='__main__':unittest.main()
