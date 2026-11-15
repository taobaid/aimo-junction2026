"""Regression tests for the user's cups/cloves/canned-ounces recipe."""
from decimal import Decimal
import copy
import os
import unittest
from unittest.mock import patch
import aimo_api as g
import recipe_agent as r
import recipe_measures as m
import test_recipe_agent as fixture


def ingredient(name,measure):
    return r.SourceIngredient(name=name,original_measure=measure,quantity=None,unit='UNRESOLVED',search_terms=[name],optional=False,uncertainty='No metric quantity in source')


class MeasuresTests(unittest.TestCase):
    def test_net_weight_ounces_and_pack_counts(self):
        for text in ['12 cans x 29 oz each','12 cans × 29 oz each','12 (29-ounce) cans','12 cans 29 ounces each']:
            value=m.resolve(ingredient('Tomato sauce, canned',text))
            self.assertEqual(value['unit'],'KG');self.assertFalse(value['estimated'])
            self.assertEqual(value['quantity'],Decimal('9.865634047500'))
        recipe=r.SourcedRecipe.model_validate({**fixture.RECIPE,'source_servings':'100','ingredients':[ingredient('Tomato sauce','12 cans x 29 oz each').model_dump()]})
        self.assertEqual(r.scaled_ingredients(recipe,200)[0]['required_quantity'],Decimal('19.731268095'))

    def test_weight_and_fluid_ounces_never_interchange(self):
        mass=m.resolve(ingredient('Water','29 oz'));volume=m.resolve(ingredient('Water','29 US fl oz'))
        self.assertEqual(mass['unit'],'KG');self.assertEqual(volume['unit'],'L')
        self.assertIsNone(m.resolve(ingredient('Milk','29 fl oz'),'strict')['quantity'])
        self.assertTrue(m.resolve(ingredient('Milk','29 fl oz'),'kitchen')['estimated'])

    def test_fractional_pounds_and_metric_units(self):
        self.assertEqual(m.resolve(ingredient('Beef','2½ lb'))['quantity'],Decimal('1.133980925'))
        self.assertEqual(m.resolve(ingredient('Beef','2-1/2 pounds'))['quantity'],Decimal('1.133980925'))
        self.assertEqual(m.resolve(ingredient('Pasta','500 g'))['quantity'],Decimal('0.5'))

    def test_known_kitchen_measures_require_buyer_mode(self):
        onion=ingredient('Onion, chopped','2 cups');garlic=ingredient('Garlic cloves, minced','16 cloves')
        self.assertIsNone(m.resolve(onion,'strict')['quantity']);self.assertIsNone(m.resolve(garlic,'strict')['quantity'])
        self.assertEqual(m.resolve(onion,'kitchen')['quantity'],Decimal('0.284'))
        self.assertEqual(m.resolve(garlic,'kitchen')['quantity'],Decimal('0.048'))
        self.assertTrue(m.resolve(onion,'kitchen')['estimated'])

    def test_salt_sugar_and_herbs_have_ingredient_specific_weights(self):
        self.assertEqual(m.resolve(ingredient('Salt','2 tablespoons'),'kitchen')['quantity'],Decimal('0.036'))
        self.assertEqual(m.resolve(ingredient('Sugar','1/2 cup'),'kitchen')['quantity'],Decimal('0.099'))
        self.assertEqual(m.resolve(ingredient('Dried basil','3 teaspoons'),'kitchen')['quantity'],Decimal('0.0021'))
        self.assertEqual(m.resolve(ingredient('Dried oregano','2 tablespoons'),'kitchen')['quantity'],Decimal('0.006'))
        self.assertTrue(m.resolve(ingredient('Italian seasoning','2 tbsp'),'kitchen')['always_review'])

    def test_unknown_or_ambiguous_quantities_are_not_guessed(self):
        for name,text in [('Tomato sauce','12 cans'),('Salt','to taste'),('Onion','1-2 cups'),('Unknown flour','2 cups'),('Fresh basil','3 teaspoons'),('Kosher salt','2 tbsp'),('Garlic powder','16 cloves')]:
            self.assertIsNone(m.resolve(ingredient(name,text),'kitchen')['quantity'],text)

    def test_liquid_volume_remains_volume(self):
        milk=m.resolve(ingredient('Milk','2 cups'),'kitchen')
        self.assertEqual(milk['unit'],'L');self.assertEqual(milk['quantity'],Decimal('0.4731764730'))


class KitchenWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.test=fixture.RecipeTests();self.test.setUp()
        self.test.recipe={**copy.deepcopy(fixture.RECIPE),'source_servings':'100','ingredients':[
            ingredient('Onion, chopped','2 cups').model_dump(),ingredient('Garlic cloves, minced','16 cloves').model_dump(),
            ingredient('Tomato sauce, canned','12 cans x 29 oz each').model_dump(),ingredient('Tomato paste, canned','12 cans x 6 oz each').model_dump(),
            ingredient('Salt','2 tbsp').model_dump(),ingredient('Sugar','1/2 cup').model_dump(),
            ingredient('Italian seasoning','2 tbsp').model_dump(),ingredient('Dried basil','3 tsp').model_dump(),ingredient('Dried oregano','3 tsp').model_dump()]}
        for idx,item in enumerate(self.test.recipe['ingredients']):
            pid='FOOD'+str(idx);item['search_terms']=[pid]
            g._catalogue_cache.append({'id':pid,'salesUnit':'BAG','baseUnit':'BAG','allowedLotSize':0.01,
                'units':[{'unitId':'BAG','sizeInBaseUnits':1}], 'synkkaData':{'names':[{'language':'en','value':pid+' '+item['name']}],
                'classifications':[],'unitConversions':[{'synkkaPackagingType':'BASE_UNIT_OR_EACH','netWeight':{'unit':'KGM','value':1}}]}})

    def tearDown(self):self.test.tearDown()

    def test_all_nine_previous_unknowns_resolve_and_one_basket_can_be_approved(self):
        p=self.test.plan(measurement_mode='kitchen',autonomy='automatic',auto_commit=True)
        self.assertEqual(p['status'],'PENDING_REVIEW')  # unsupported herb-blend proxy always reviewed
        self.assertFalse(p['issues']);self.assertEqual(len(p['order_lines']),9)
        self.assertTrue(all(i['required_quantity'] is not None for i in p['ingredients']))
        self.assertEqual(Decimal(p['ingredients'][0]['required_quantity']),Decimal('0.568'))
        self.assertEqual(Decimal(p['ingredients'][1]['required_quantity']),Decimal('0.096'))
        self.assertEqual(Decimal(p['ingredients'][2]['required_quantity']),Decimal('19.731268095'))
        approved=self.test.commit(p);self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(approved.json()['status'],'COMMITTED_MOCK')
        self.assertEqual(len(approved.json()['mock_order']['quantity_assumptions']),7)

    def test_agent_cannot_grant_itself_estimate_authority(self):
        with patch.dict(os.environ,{'AIMO_RECIPE_MEASUREMENTS':'strict'}):
            response=self.test.client.post('/recipe-plans',headers=self.test.agent,json={'request':'Bolognese','delivery_date':self.test.fixture.day,'measurement_mode':'kitchen'})
        self.assertEqual(response.status_code,403)

    def test_revoked_estimate_authority_blocks_autonomous_commit(self):
        # Use sourced onion estimate only, no demo herb proxy or uncertainty.
        self.test.recipe['ingredients']=self.test.recipe['ingredients'][:1]
        p=self.test.plan(measurement_mode='kitchen',autonomy='automatic')
        self.assertEqual(p['status'],'AUTO_AUTHORISED')
        with patch.dict(os.environ,{'AIMO_RECIPE_MEASUREMENTS':'strict'}):
            response=self.test.client.post('/recipe-plans/'+p['id']+'/commit',headers=self.test.agent,json={'fingerprint':p['fingerprint']})
        self.assertEqual(response.status_code,403)

    def test_informational_notes_do_not_create_a_manual_spending_decision(self):
        self.test.recipe['ingredients']=self.test.recipe['ingredients'][:1]
        self.test.recipe['notes']=['Source yield is 100; no garnish listed.']
        p=self.test.plan(measurement_mode='kitchen',autonomy='automatic',auto_commit=True)
        self.assertEqual(p['status'],'COMMITTED_MOCK')

    def test_substantive_recipe_review_reason_requires_one_approval(self):
        self.test.recipe['ingredients']=self.test.recipe['ingredients'][:1]
        self.test.recipe['review_reasons']=['Preparation requirement needs confirmation.']
        p=self.test.plan(measurement_mode='kitchen',autonomy='automatic',auto_commit=True)
        self.assertEqual(p['status'],'PENDING_REVIEW')

    def test_quantity_unknown_still_searches_catalogue(self):
        recipe=r.SourcedRecipe.model_validate(self.test.recipe)
        rows=r.scaled_ingredients(recipe,200,'strict')
        choices=r.collect_candidates(g,rows)
        self.assertTrue(choices['I-1']);self.assertTrue(choices['I-2'])


if __name__=='__main__':unittest.main()
