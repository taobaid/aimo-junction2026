"""Partial purchasing is an explicit, reviewed scope change for any dish."""
import copy
from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch
import aimo_api as g
import recipe_agent as r
import test_recipe_agent as fixture


def ingredient(name,quantity,unit,raw):
    return {'name':name,'quantity':quantity,'unit':unit,'original_measure':raw,
            'search_terms':[name],'optional':False,'uncertainty':None}

class PartialPurchaseTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.RecipeTests();self.f.setUp()
        self.f.recipe['title']='Lasagna'
        self.f.recipe['ingredients'] += [ingredient('Beef mince','0.3','KG','300 g'),
            ingredient('Canned chopped tomatoes',None,'UNRESOLVED','2 cups'),
            ingredient('Garlic',None,'UNRESOLVED','4 cloves'),
            ingredient('Parmesan cheese','0.05','KG','50 g')]
        g._catalogue_cache.append({'id':'BEEF','salesUnit':'ST','baseUnit':'ST','allowedLotSize':1,
            'units':[{'unitId':'ST','sizeInBaseUnits':1}],
            'synkkaData':{'names':[{'language':'en','value':'Beef mince 1 kg'}],
                'unitConversions':[{'synkkaPackagingType':'BASE_UNIT_OR_EACH','netWeight':{'unit':'KGM','value':1}}]}})
        def upstream(endpoint,payload,key):
            value=self.f.fixture.mock_upstream(endpoint,payload,key)
            if endpoint=='/api/availability':
                for row in value['products']:
                    if row['productId']=='BEEF':row['closingTime']=(self.f.fixture.now-timedelta(days=1)).isoformat()
            return value
        g.core.api_post.side_effect=upstream
    def tearDown(self):self.f.tearDown()
    def parent(self,**kw):return self.f.plan(planning_mode='quick',resolve_exceptions=False,**kw)
    def partial(self,p,headers=None):return self.f.client.post('/recipe-plans/'+p['id']+'/partial',
        headers=headers or self.f.reviewer,json={'fingerprint':p['fingerprint']})
    def test_lasagna_can_buy_available_items_without_claude_or_quantity_guesses(self):
        parent=self.parent(autonomy='automatic',auto_commit=True)
        self.assertEqual(parent['status'],'BLOCKED');self.assertEqual(len(parent['partial_order_options']),4)
        calls=r.provider_call.call_count; supplier_calls=g.core.api_post.call_count
        child=self.partial(parent);self.assertEqual(child.status_code,200,child.text);child=child.json()
        self.assertEqual(r.provider_call.call_count,calls)
        self.assertEqual(g.core.api_post.call_count-supplier_calls,2) # price + availability, no research
        self.assertTrue(child['partial_order']);self.assertFalse(child['issues'])
        self.assertEqual(child['status'],'PENDING_REVIEW');self.assertIsNone(child['mock_order'])
        self.assertEqual(len(child['excluded_ingredients']),4);self.assertEqual(child['parent_plan'],parent['id'])
        self.assertEqual({line['sku'] for line in child['order_lines']},{'PASTA','464201'})
        self.assertEqual(Decimal(child['total_gross_eur']),Decimal('63.10'))
        garlic=next(i for i in child['ingredients'] if i['name']=='Garlic')
        self.assertIsNone(garlic['required_quantity']);self.assertEqual(garlic['status'],'NOT_ORDERED_PENDING_APPROVAL')
        self.assertEqual(self.f.commit(parent).status_code,409)
        receipt=self.f.commit(child);self.assertEqual(receipt.status_code,200,receipt.text)
        order=receipt.json()['mock_order'];self.assertEqual(order['fulfillment_scope'],'SELECTED_ITEMS_ONLY')
        self.assertFalse(order['complete_recipe_basket']);self.assertEqual(len(order['excluded_ingredients']),4)
        self.assertFalse(order['upstream_order_submitted'])
        self.assertEqual(self.f.commit(child).json()['mock_order']['id'],order['id'])
    def test_dish_name_does_not_control_partial_option(self):
        for dish in ['Lasagna','Tacos','Paella','Vegetable curry','Salmon pie','A new dish']:
            with self.subTest(dish=dish):
                self.f.recipe['title']=dish;p=self.parent(request=dish)
                result=self.partial(p);self.assertEqual(result.status_code,200,result.text)
                self.assertTrue(result.json()['partial_order']);self.assertFalse(result.json()['issues'])
    def test_agent_can_propose_but_cannot_confirm_partial_purchase(self):
        p=self.partial(self.parent(),self.f.agent).json()
        self.assertEqual(p['status'],'PENDING_REVIEW')
        self.assertEqual(self.f.commit(p,self.f.agent).status_code,403)
        result=self.f.client.post('/recipe-plans/'+p['id']+'/commit',headers=self.f.agent,json={'fingerprint':p['fingerprint']})
        self.assertEqual(result.status_code,403)
    def test_stale_fingerprint_and_rejected_parent_are_rejected(self):
        p=self.parent();bad={**p,'fingerprint':'0'*64}
        self.assertEqual(self.partial(bad).status_code,409)
        self.f.client.post('/recipe-plans/'+p['id']+'/decline',headers=self.f.reviewer,json={'fingerprint':p['fingerprint']})
        self.assertEqual(self.partial(p).status_code,409)
    def test_no_partial_purchase_with_no_available_products(self):
        self.f.fixture.stock_amount=0;p=self.parent()
        self.assertEqual(p['partial_order_options'],[])
        self.assertEqual(self.partial(p).status_code,409)
    def test_included_product_stock_change_still_blocks_commit(self):
        p=self.partial(self.parent()).json();self.f.fixture.stock_amount=0
        self.assertEqual(self.f.commit(p).status_code,409)
    def test_price_and_buyer_policy_changes_still_block_commit(self):
        p=self.partial(self.parent()).json();self.f.fixture.price_factor=2
        self.assertEqual(self.f.commit(p).status_code,409)
        self.f.fixture.price_factor=1
        with patch.dict('os.environ',{'AIMO_REQUIRED_CLAIMS':'FREE_FROM_GLUTEN'}):
            self.assertEqual(self.f.commit(p).status_code,409)
    def test_partial_choice_freshens_an_expired_parent(self):
        p=self.parent()
        with patch.object(g.core,'utc_now',return_value=self.f.fixture.now+timedelta(minutes=31)):
            result=self.partial(p);self.assertEqual(result.status_code,200,result.text)
            self.assertFalse(result.json()['expired'])
    def test_rebuild_preserves_exclusions_and_partial_receipt_scope(self):
        p=self.partial(self.parent()).json()
        selected=next(i for i in p['ingredients'] if i['status']=='MATCHED')
        result=self.f.client.post('/recipe-plans/'+p['id']+'/rebuild',headers=self.f.reviewer,
            json={'fingerprint':p['fingerprint'],'quantities':[{'ingredient_id':selected['id'],'quantity':selected['required_quantity'],'unit':selected['unit']}]})
        self.assertEqual(result.status_code,201,result.text);new=result.json()
        self.assertTrue(new['partial_order']);self.assertEqual(len(new['excluded_ingredients']),4)
        self.assertEqual(self.f.commit(new).status_code,200)
        self.assertFalse(self.f.commit(new).json()['mock_order']['complete_recipe_basket'])
    def test_complete_basket_has_no_missing_items_to_exclude(self):
        self.f.recipe=copy.deepcopy(fixture.RECIPE);p=self.parent()
        self.assertEqual(p['partial_order_options'],[]);self.assertEqual(self.partial(p).status_code,409)
    def test_failed_combined_sku_is_an_exclusion_option(self):
        saved={'ingredients':[{'id':'I','name':'Shared ingredient','optional':False,'status':'MATCHED','selected_sku':'SKU','reasons':[]}],
               'order_lines':[{'sku':'SKU','readiness':'BLOCKED'}]}
        self.assertEqual(r.partial_options(saved)[0]['ingredient_id'],'I')

if __name__=='__main__':unittest.main()
