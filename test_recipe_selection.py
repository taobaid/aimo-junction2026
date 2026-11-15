"""Recipe selection and ingestion regressions; all sources/models are synthetic."""
import copy
from datetime import date
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
import recipe_agent as r
import aimo_api as g
import test_recipe_agent as fixtures

class SelectionTests(unittest.TestCase):
    def request(self,**kw):
        return r.RecipeRequest(request='Select a meal for 200',portions=200,delivery_date=date(2026,11,17),**kw)
    def recipe(self,**kw):return r.SourcedRecipe.model_validate({**copy.deepcopy(fixtures.RECIPE),**kw})
    def test_third_source_can_recover_missing_yield_and_quantities(self):
        a=self.recipe(source_servings=None)
        b=self.recipe(source_url='https://example.com/two',ingredient_list_complete=False)
        c=self.recipe(source_url='https://example.com/three')
        with patch.object(r,'_research_recipe',side_effect=[(a,[]),(b,[]),(c,[])]) as model:
            found,_=r.find_recipe(g,self.request())
        self.assertEqual(found.source_url,c.source_url);self.assertEqual(model.call_count,3)
    def test_valid_best_candidate_survives_failed_later_source(self):
        first=self.recipe(ingredient_list_complete=False)
        with patch.object(r,'_research_recipe',side_effect=[(first,[]),RuntimeError('No retrieved recipe sources were returned.'),RuntimeError('Extraction validation failed')]):
            found,_=r.find_recipe(g,self.request())
        self.assertEqual(found.title,first.title);self.assertFalse(found.ingredient_list_complete)
    def test_schema_failure_can_move_to_another_source(self):
        with patch.object(r,'_research_recipe',side_effect=[RuntimeError('Recipe model output failed SourcedRecipe validation'),(self.recipe(),[])]) as lookup:
            found,_=r.find_recipe(g,self.request())
        self.assertTrue(found.ingredient_list_complete);self.assertEqual(lookup.call_count,2)
    def test_no_automatic_paid_retry_after_timeout(self):
        with patch.object(r,'_research_recipe',side_effect=RuntimeError('Claude request timed out')) as lookup:
            with self.assertRaises(RuntimeError):r.find_recipe(g,self.request())
        self.assertEqual(lookup.call_count,1)
    def test_first_good_recipe_does_not_search_again(self):
        with patch.object(r,'_research_recipe',return_value=(self.recipe(),[])) as lookup:r.find_recipe(g,self.request())
        self.assertEqual(lookup.call_count,1)
    def test_selected_url_is_not_silently_replaced(self):
        lookup={'output':[{'type':'message','content':[{'type':'output_text','text':'Synthetic retrieved recipe facts'}]},{'type':'web_search_call','action':{'sources':[{'url':fixtures.RECIPE['source_url']}]}}]}
        with patch.object(r,'provider_call',return_value=lookup),patch.object(r,'extract_recipe',return_value=self.recipe()):
            with self.assertRaisesRegex(RuntimeError,'selected recipe URL'):r.find_recipe(g,self.request(recipe_url='https://example.com/chosen'))
    def test_local_or_credentialed_urls_are_rejected_before_provider(self):
        for url in ['http://127.0.0.1/','http://localhost/','file:///tmp/a','https://user:pass@example.com/']:
            with self.subTest(url=url),patch.object(r,'provider_call') as model:
                with self.assertRaises(RuntimeError):r.find_recipe(g,self.request(recipe_url=url))
                model.assert_not_called()
    def test_pasted_recipe_needs_no_web_search_and_always_requires_review(self):
        recipe=self.recipe(source_url='')
        with patch.object(r,'json_model',return_value=recipe) as model,patch.object(r,'provider_call') as web:
            found,sources=r.find_recipe(g,self.request(recipe_text='Serves 4: 400 g macaroni; 200 ml milk'))
        self.assertEqual(sources,[]);web.assert_not_called();self.assertTrue(found.review_reasons)
        self.assertEqual(model.call_args.args[3]['research'],'Serves 4: 400 g macaroni; 200 ml milk')
    def test_varied_dishes_scale_without_milk_specific_logic(self):
        for title,ingredient in [('Lohikeitto','Salmon'),('Dal tadka','Red lentils'),('Chicken curry','Chicken'),('Vegetable lasagne','Courgettes'),('Tofu stir fry','Tofu'),('Pancakes','Flour'),('Apple crumble','Apples'),('Riz au lait','Rice')]:
            with self.subTest(title=title):
                recipe=self.recipe(title=title,ingredients=[{'name':ingredient,'quantity':'0.5','unit':'KG','original_measure':'500 g','search_terms':[ingredient],'optional':False,'uncertainty':None}])
                self.assertEqual(r.scaled_ingredients(recipe,200)[0]['required_quantity'],Decimal('25'))
    def test_large_recipe_matching_is_batched_and_keeps_every_ingredient(self):
        ingredient={'id':'x','name':'Test ingredient','required_quantity':Decimal(1),'unit':'KG','optional':False}
        rows=[{**ingredient,'id':str(i)} for i in range(45)]
        candidates={i['id']:[{'id':'candidate','synkkaData':{}}] for i in rows}
        def reply(gateway,model,instructions,data):
            return r.MatchResult(matches=[r.IngredientMatch(ingredient_id=i['ingredient']['id'],product_ids=[],reason='No supplied products',requires_review=True) for i in data])
        with patch.object(r,'json_model',side_effect=reply) as model,patch.object(g,'public_product',return_value={'sku':'candidate'}):result=r.match_candidates(g,rows,candidates)
        self.assertEqual(set(result),set(candidates));self.assertEqual(model.call_count,6)
        self.assertTrue(all(len(c.args[3])<=8 for c in model.call_args_list))
    def test_dietary_request_is_passed_to_extraction(self):
        with patch.object(r,'json_model',return_value=self.recipe()) as model:
            r.extract_recipe(g,self.request(preferences='Vegan and no nuts'),'Source facts',[{'url':fixtures.RECIPE['source_url']}])
        self.assertEqual(model.call_args.args[3]['preferences'],'Vegan and no nuts')

class PastedRecipeFlowTests(unittest.TestCase):
    def test_pasted_recipe_uses_existing_price_and_approval_flow(self):
        f=fixtures.RecipeTests();f.setUp()
        try:
            f.recipe['source_url']=''
            plan=f.plan(recipe_text='Serves 4: 400 g macaroni; 200 ml milk',autonomy='automatic',auto_commit=True)
            self.assertEqual(plan['status'],'PENDING_REVIEW');self.assertIsNone(plan['mock_order'])
            self.assertFalse(plan['issues']);self.assertEqual(f.commit(plan).status_code,200)
        finally:f.tearDown()

if __name__=='__main__':unittest.main()
