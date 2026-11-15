"""Key-free local walkthrough. Sample data only; never contacts Claude or suppliers."""
import argparse
from contextlib import closing
from datetime import timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import secrets
import tempfile


def create_demo(db_path):
    # Deliberately isolate all credentials/settings from any live shell configuration.
    values={'AIMO_AGENT_TOKEN':secrets.token_urlsafe(24),'AIMO_REVIEWER_TOKEN':secrets.token_urlsafe(24),
            'AIMO_API_KEY':'offline-sample-only','ANTHROPIC_API_KEY':'offline-sample-only',
            'RECIPE_PROVIDER':'anthropic','RECIPE_MODEL':'offline-sample-recipes',
            'AIMO_DB':str(db_path),'AIMO_CUSTOMER':'demo-buyer','AIMO_APPROVAL_LIMIT':'1200',
            'AIMO_REVIEWER_NAME':'Demo reviewer','AIMO_RECIPE_MEASUREMENTS':'kitchen',
            'AIMO_RECIPE_AUTONOMY':'automatic','AIMO_REQUIRED_CLAIMS':'','AIMO_REQUIRED_ORIGIN':'',
            'AIMO_RECIPE_CACHE':'0','VAPI_WEBHOOK_SECRET':'','VAPI_PUBLIC_KEY':'','VAPI_ASSISTANT_ID':''}
    os.environ.update(values)
    import aimo_api as g
    import recipe_agent as r
    catalogue=[];prices={};stocks={}
    def product(sku,name,size,unit,net,gross,stock=999999,claims=()):
        measure={'volume':{'unit':'LTR','value':size}} if unit=='L' else {'netWeight':{'unit':'KGM','value':size}}
        catalogue.append({'id':sku,'salesUnit':'ST','baseUnit':'ST','allowedLotSize':1,
            'units':[{'unitId':'ST','sizeInBaseUnits':1}],'countryOfOrigin':'fi',
            'synkkaData':{'names':[{'language':'en','value':name}],
                'classifications':[{'name':'nutritionalClaim','values':[{'id':c} for c in claims]}],
                'unitConversions':[{'synkkaPackagingType':'BASE_UNIT_OR_EACH',**measure}]}})
        prices[sku]=(str(net),str(gross));stocks[sku]=stock
    product('464201','Sample lactose-free semi-skimmed milk 1 l',1,'L','1.56','1.77',claims=['FREE_FROM_LACTOSE'])
    for args in [('D-PASTA','Spaghetti dry 1 kg',1,'KG','2.5','2.84'),
        ('D-BEEF-A','Beef mince 1 kg',1,'KG','7','7.95',0),
        ('D-BEEF-B','Beef mince lean 1 kg',1,'KG','8','9.08'),
        ('D-TOMATO','Chopped tomatoes 2.5 kg',2.5,'KG','4','4.54'),
        ('D-ONION','Onion diced 1 kg',1,'KG','2','2.27'),
        ('D-GARLIC','Garlic peeled 0.5 kg',.5,'KG','3','3.41'),
        ('D-OIL','Olive oil 1 l',1,'L','8','9.08'),
        ('D-WINE','Red wine cooking 1 l',1,'L','5','5.68',0),
        ('D-SALT','Salt 1 kg',1,'KG','1','1.14'),
        ('D-RICE','Rice dry 1 kg',1,'KG','2','2.27'),
        ('D-CHICKPEA','Chickpeas cooked 2.5 kg',2.5,'KG','4','4.54'),
        ('D-CURRY','Curry powder 0.5 kg',.5,'KG','4','4.54'),
        ('D-SALMON','Salmon fillet 1 kg',1,'KG','15','17.03'),
        ('D-POTATO','Potato peeled 2.5 kg',2.5,'KG','3','3.41'),
        ('D-CREAM','Cooking cream 1 l',1,'L','4','4.54'),
        ('D-DILL','Dill 0.1 kg',.1,'KG','2','2.27')]:product(*args)
    g._catalogue_cache=catalogue
    g.app.state.offline_demo=True
    today=g.core.utc_now();delivery=(today+timedelta(days=3)).date().isoformat()
    def ingredient(name,qty,unit,term=None):
        return {'name':name,'quantity':str(qty),'unit':unit,
            'original_measure':str(Decimal(str(qty))*1000)+(' g' if unit=='KG' else ' ml'),
            'search_terms':[term or name],'optional':False,'uncertainty':None}
    common=[ingredient('Onion',.15,'KG'),ingredient('Olive oil',.03,'L'),ingredient('Salt',.008,'KG')]
    menus={
        'Spaghetti bolognese':[ingredient('Spaghetti',.4,'KG'),ingredient('Beef mince',.3,'KG'),
            ingredient('Chopped tomatoes',.4,'KG'),ingredient('Garlic',.006,'KG'),ingredient('Red wine',.1,'L')]+common,
        'Chickpea curry':[ingredient('Chickpeas',.5,'KG'),ingredient('Rice',.3,'KG'),
            ingredient('Chopped tomatoes',.4,'KG'),ingredient('Curry powder',.012,'KG')]+common,
        'Lohikeitto':[ingredient('Salmon',.4,'KG'),ingredient('Potato',.6,'KG'),ingredient('Cooking cream',.2,'L'),
            ingredient('Dill',.01,'KG'),ingredient('Onion',.1,'KG'),ingredient('Salt',.008,'KG')]}
    aliases={'spaghetti bolognese':'Spaghetti bolognese','bolognese':'Spaghetti bolognese',
             'chickpea curry':'Chickpea curry','vegetable curry':'Chickpea curry',
             'lohikeitto':'Lohikeitto','salmon soup':'Lohikeitto'}
    def model(gateway,body):
        if body.get('tools'):raise RuntimeError('Recipe offline demo supports sample recipes only. Select Quick plan. Live research needs live mode.')
        name=body.get('text',{}).get('format',{}).get('name')
        data=json.loads(body.get('input','{}'))
        if name=='sourcedrecipe':
            if 'AI-GENERATED DRAFT' not in body.get('instructions',''):
                raise RuntimeError('Recipe text extraction is unavailable in the offline demo. Use a sample dish or start live mode.')
            text=data.get('meal_request','').casefold()
            title=next((title for alias,title in aliases.items() if alias in text),None)
            if not title:raise RuntimeError('Recipe offline demo supports Spaghetti bolognese, Chickpea curry and Lohikeitto. Live mode handles new dishes with Claude.')
            if data.get('preferences','').strip():raise RuntimeError('Recipe offline demo does not interpret preferences. Clear preferences for this walkthrough, or use live mode.')
            value={'title':title,'source_url':'','source_title':'Offline sample recipe','provenance':'generated',
                'source_servings':'4','ingredients':menus[title],'ingredient_list_complete':True,
                'missing_ingredients':[],'review_reasons':['Offline sample recipe. No Claude call or real source lookup occurred.'],
                'notes':['Fixed demonstration quantities and synthetic product data. Review only.']}
        elif name=='matchresult':
            value={'matches':[{'ingredient_id':row['ingredient']['id'],
                'product_ids':[p['sku'] for p in row['catalogue_candidates']][:12],
                'reason':'Fixed offline sample identity match.','requires_review':False} for row in data]}
        elif name=='recoveryplan':value={'alternatives':[]}
        else:raise RuntimeError('Recipe model operation unavailable in the offline sample.')
        return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]}
    def supplier(endpoint,payload,key):
        now=g.core.utc_now();rows=[]
        for sku in payload['products']:
            if sku not in prices:continue
            if endpoint=='/api/price':
                net,gross=prices[sku]
                rows.append({'productId':sku,'error':False,'quantity':1,'catalogPrice':{'value':net,'valueWithTax':gross,
                    'currency':'EUR','validFrom':now.date().isoformat(),'validTo':(now+timedelta(days=30)).date().isoformat()}})
            elif endpoint=='/api/availability':
                rows.append({'productId':sku,'salesBlock':False,'logisticModel':'Terminal',
                    'closingTime':(now+timedelta(days=1)).isoformat(),
                    'scheduleLines':[{'salesBlock':False,'salesUnit':'ST','availableDate':payload['requestedDate'],'availableAmount':stocks[sku]}]})
            else:raise RuntimeError('Offline demo blocks this upstream operation.')
        return {'products':rows,**({'timeNow':now.isoformat()} if endpoint=='/api/availability' else {})}
    r.provider_call=model;g.core.api_post=supplier
    # Seed real gateway routes so the UI has a complete review and receipt journey.
    import httpx,asyncio
    async def seed():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=g.app),base_url='http://demo.local',
              headers={'Authorization':'Bearer '+values['AIMO_REVIEWER_TOKEN']}) as client:
            for qty in ('1000','10'):
                offer=await client.post('/offers',json={'plain_milk':True,'quantity':qty,'unit':'L','delivery_date':delivery})
                offer.raise_for_status()
                proposal=await client.post('/proposals',json={'offer_id':offer.json()['id'],'sku':'464201'})
                proposal.raise_for_status()
                if qty=='10':
                    receipt=await client.post('/orders',json={'proposal_id':proposal.json()['id']});receipt.raise_for_status()
            recipe=await client.post('/recipe-plans',json={'request':'Spaghetti bolognese','portions':200,
                'delivery_date':delivery,'planning_mode':'quick','measurement_mode':'kitchen'})
            recipe.raise_for_status()
    asyncio.run(seed())
    return g,values,delivery


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='trusted-trade-demo-') as folder:
        g,values,delivery=create_demo(Path(folder)/'demo.sqlite3')
        print('\nOFFLINE SAMPLE DEMO — no Claude or supplier calls. Resets on restart.',flush=True)
        print('Open http://127.0.0.1:'+str(args.port),flush=True)
        print('Paste this reviewer token into the login form: '+values['AIMO_REVIEWER_TOKEN'],flush=True)
        print('AIMO_AGENT_TOKEN='+values['AIMO_AGENT_TOKEN'],flush=True)
        print('Suggested delivery date: '+delivery,flush=True)
        print('Try: Spaghetti bolognese, Chickpea curry, or Lohikeitto. Preferences: leave blank.',flush=True)
        import uvicorn
        uvicorn.run(g.app,host='127.0.0.1',port=args.port,workers=1)

if __name__=='__main__':main()
