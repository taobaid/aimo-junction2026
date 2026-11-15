"""Native Claude HTTP contract through source, conversion, stock and mock approval."""
import copy
from datetime import timedelta
from decimal import Decimal
import json
import unittest
import httpx
import aimo_api as g
import recipe_agent as r
import recipe_measures as measures
import test_claude_recipe as native
import test_recipe_agent as fixture


def item(name,qty,unit,measure,term=None):
    return {'name':name,'quantity':qty,'unit':unit,'original_measure':measure,'search_terms':[term or name],'optional':False,'uncertainty':None}

class DishOrderingTests(unittest.TestCase):
    def setUp(self):
        self.native=native.ClaudeTests();self.native.setUp();self.f=self.native.fixture
        self.cutoff={'BEEF-A'};self.stock={'TOM-A':20,'TOM-B':20};self.searches=0;self.second=None
        self.recipe={**copy.deepcopy(fixture.RECIPE),'title':'Spaghetti Bolognese','ingredients':[
            item('Spaghetti','0.4','KG','400 g','macaroni'),item('Beef mince','0.3','KG','300 g','beef mince'),
            item('Fresh garlic',None,'UNRESOLVED','4 cloves of fresh garlic, peeled and finely chopped','garlic'),
            item('Chopped tomatoes','0.3','KG','300 g','tomato'),item('Tomatoes for sauce','0.3','KG','300 g','tomato'),
            item('Red wine','0.1','L','100 ml','red wine')]}
        for pid,name in [('BEEF-A','A beef mince'),('BEEF-B','B beef mince'),('GARLIC','Fresh garlic'),('TOM-A','A tomato'),('TOM-B','B tomato')]:self.add(pid,name)
        self.native.reply_override=self.reply;g.core.api_post.side_effect=self.upstream
    def tearDown(self):self.native.tearDown()
    def add(self,pid,name):
        g._catalogue_cache.append({'id':pid,'salesUnit':'ST','baseUnit':'ST','allowedLotSize':0.01,'units':[{'unitId':'ST','sizeInBaseUnits':1}],
            'synkkaData':{'names':[{'language':'en','value':name}],'classifications':[],
            'unitConversions':[{'synkkaPackagingType':'BASE_UNIT_OR_EACH','netWeight':{'unit':'KGM','value':1}}]}})
    def upstream(self,endpoint,payload,key):
        data=self.f.mock_upstream(endpoint,payload,key)
        if endpoint=='/api/availability':
            for p in data['products']:
                if p['productId'] in self.cutoff:p['closingTime']=(self.f.now-timedelta(days=1)).isoformat()
                if p['productId'] in self.stock:p['scheduleLines'][0]['availableAmount']=self.stock[p['productId']]
        return data
    def reply(self,request,body):
        if body.get('tools'):
            self.searches+=1
            if self.second and self.searches>1:self.recipe=copy.deepcopy(self.second)
            blocks=native.search_blocks()
            for b in blocks:
                if b.get('type')=='web_fetch_tool_result':b['content']['url']=self.recipe['source_url']
                if b.get('type')=='text':b['text']='Synthetic complete source facts: '+json.dumps(self.recipe)
        else:
            schema=body['output_config']['format']['schema']
            def check(n):
                if isinstance(n,dict):
                    self.assertNotIn('maxItems',n)
                    for v in n.values():check(v)
                elif isinstance(n,list):
                    for v in n:check(v)
            check(schema)
            if 'ingredients' in schema['properties']:value=self.recipe
            elif 'alternatives' in schema['properties']:value={'alternatives':[]}
            else:
                supplied=json.loads(body['messages'][0]['content']);matches=[]
                for row in supplied:
                    choices=[p['sku'] for p in row['catalogue_candidates']]
                    if row['ingredient']['name']=='Tomatoes for sauce':choices=[x for x in choices if x=='TOM-A']
                    matches.append({'ingredient_id':row['ingredient']['id'],'product_ids':choices[:12],'reason':'Synthetic compatible ingredient identity','requires_review':False})
                value={'matches':matches}
            blocks=[{'type':'text','text':json.dumps(value)}]
        return httpx.Response(200,json={'content':blocks,'stop_reason':'end_turn'})
    def plan(self,**kwargs):
        response=self.f.client.post('/recipe-plans',headers=self.f.reviewer,json={'request':self.recipe['title']+' for 200 people','portions':200,'delivery_date':self.f.day,'measurement_mode':'kitchen',**kwargs})
        self.assertEqual(response.status_code,201,response.text);return response.json()
    def approve(self,p):return self.f.client.post('/recipe-plans/'+p['id']+'/approve-and-commit',headers=self.f.reviewer,json={'fingerprint':p['fingerprint']})
    def test_bolognese_complete_native_claude_pipeline_handles_screenshot_blockers(self):
        p=self.plan();self.assertFalse(p['issues'],p['issues']);self.assertEqual(p['status'],'PENDING_REVIEW')
        self.assertEqual(Decimal(next(i for i in p['ingredients'] if i['name']=='Fresh garlic')['required_quantity']),Decimal('0.6'))
        skus={b['sku'] for b in p['order_lines']}
        self.assertNotIn('BEEF-A',skus);self.assertIn('BEEF-B',skus)
        self.assertTrue({'TOM-A','TOM-B'}.issubset(skus))
        self.assertTrue(any(c['type']=='OMISSION' for c in p['changes']))
        response=self.approve(p);self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['mock_order']['upstream_order_submitted'])
    def test_fresh_stock_failure_still_stops_confirmation(self):
        p=self.plan();self.stock['BEEF-B']=0
        self.assertEqual(self.approve(p).status_code,409)
    def test_unavailable_first_recipe_selects_complete_same_dish_variant(self):
        self.second=copy.deepcopy(self.recipe);self.second['source_url']='https://example.com/alternate-bolognese'
        self.recipe['ingredients'].append(item('Anchovy sauce','0.01','L','10 ml'))
        p=self.plan(autonomy='automatic',auto_commit=True)
        self.assertFalse(p['issues'],p['issues']);self.assertEqual(p['recipe']['source_url'],self.second['source_url'])
        self.assertEqual(p['status'],'PENDING_REVIEW');self.assertIsNone(p['mock_order'])
        self.assertTrue(any(c['type']=='RECIPE_SELECTION' for c in p['changes']))
        self.assertEqual(self.approve(p).status_code,200)
    def test_no_stock_anywhere_remains_honestly_blocked(self):
        self.cutoff.add('BEEF-B');p=self.plan();self.assertEqual(p['status'],'BLOCKED');self.assertIsNone(p['mock_order'])
        self.assertEqual(self.approve(p).status_code,409)
    def test_general_dishes_use_same_native_api_pipeline(self):
        for title,food in [('Lohikeitto','Salmon'),('Dal tadka','Red lentils'),('Vegetable curry','Chickpeas'),('Tofu stir fry','Tofu'),('Apple crumble','Apples')]:
            with self.subTest(dish=title):
                self.add(food.upper().replace(' ','-'),food)
                self.recipe={**copy.deepcopy(fixture.RECIPE),'title':title,'ingredients':[item(food,'0.5','KG','500 g')]}
                p=self.plan();self.assertFalse(p['issues'],p['issues']);self.assertEqual(Decimal(p['ingredients'][0]['required_quantity']),Decimal('25'))
                self.assertEqual(self.approve(p).status_code,200)
    def test_garlic_preparation_phrases_resolve_only_with_kitchen_authority(self):
        for raw in ['4 cloves of garlic, minced','4 cloves of fresh garlic, peeled and finely chopped','4 cloves garlic (crushed)','4 garlic cloves, peeled, minced']:
            with self.subTest(measure=raw):
                i=r.SourceIngredient.model_validate(item('Fresh garlic',None,'UNRESOLVED',raw))
                self.assertEqual(measures.resolve(i,'kitchen')['quantity'],Decimal('0.012'))
                self.assertIsNone(measures.resolve(i,'strict')['quantity'])

if __name__=='__main__':unittest.main()
