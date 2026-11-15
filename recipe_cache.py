"""Share successful source recipes across UI, voice and local diagnostics.

Only source facts are cached. Product matches, stock, quotes, approvals and order
receipts are NEVER reused. A cache hit still runs the full sourcing workflow.
"""
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import re
import unicodedata
import claude_recipe
import recipe_measures

VERSION='recipe-source-v2'


def enabled(g,request):
    return g.setting('AIMO_RECIPE_CACHE','1')!='0' and not request.recipe_text.strip() and not request.recipe_url


def canonical_dish(text):
    text=unicodedata.normalize('NFKC',text).casefold().strip()
    text=re.sub(r'\s+for\s+\d+(?:\s+(?:people|persons|portions|servings|guests))?[.!?]*$','',text)
    return ' '.join(text.split()).rstrip('.!?')


def key(g,request):
    config=claude_recipe.configuration(g)
    data={'version':VERSION,'buyer':g.buyer(),'dish':canonical_dish(request.request),
          'planning_mode':request.planning_mode,'portions':request.portions,'preferences':' '.join(request.preferences.casefold().split()),
          'measurement_mode':request.measurement_mode,'recovery_mode':request.recovery_mode,'measure_profiles':recipe_measures.VERSION,
          'required_claims':g.setting('AIMO_REQUIRED_CLAIMS'),'required_origin':g.setting('AIMO_REQUIRED_ORIGIN'),
          'provider':config['provider'],'model':config['model'],'endpoint':config['base']}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def connection(g):
    c=g.db()
    c.execute('''CREATE TABLE IF NOT EXISTS successful_recipe_sources
        (cache_key TEXT PRIMARY KEY, expires_at TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL)''')
    c.commit();return c


def load(g,request,model):
    if not enabled(g,request) or request.refresh_recipe:return None
    with closing(connection(g)) as c:
        row=c.execute('SELECT * FROM successful_recipe_sources WHERE cache_key=?',(key(g,request),)).fetchone()
    if not row:return None
    try:
        if datetime.fromisoformat(row['expires_at'])<=g.core.utc_now() or g.core.snapshot_digest(row['payload'])!=row['digest']:return None
        payload=json.loads(row['payload']);recipe=model.model_validate(payload['recipe'])
        if not recipe.ingredient_list_complete or recipe.missing_ingredients:return None
        return recipe,payload['sources']
    except (ValueError,TypeError,KeyError):return None


def save(g,request,recipe,sources,assessment):
    if not enabled(g,request) or assessment[2] or assessment[4] is None or not assessment[1]:return
    if not recipe.ingredient_list_complete or recipe.missing_ingredients:return
    payload=json.dumps({'recipe':recipe.model_dump(),'sources':sources},sort_keys=True,ensure_ascii=False)
    now=g.core.utc_now()
    with g._write_lock,closing(connection(g)) as c:
        c.execute('DELETE FROM successful_recipe_sources WHERE expires_at<=?',(now.isoformat(),))
        c.execute('INSERT OR REPLACE INTO successful_recipe_sources VALUES(?,?,?,?)',
            (key(g,request),(now+timedelta(hours=24)).isoformat(),payload,g.core.snapshot_digest(payload)))
        c.commit()
