"""Deterministic recipe measures. Never infer food mass from water density.

Kitchen estimates are opt-in buyer policy, separately identified from exact
unit conversions. The fixed profiles are edible-ingredient planning estimates,
not supplier specifications, allergy evidence or nutrition certifications.
"""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import re

VERSION = "kitchen-v1"
NIST = "https://www.nist.gov/system/files/documents/2025/12/23/2026_NIST_HB133_AppendixE-20251222.pdf"
KING_ARTHUR = "https://www.kingarthurbaking.com/learn/ingredient-weight-chart"
GARLIC = "https://food-nutrition.canada.ca/cnf-fce/serving-portion?id=2394"
USDA = "https://www.ars.usda.gov/ARSUserFiles/80400525/Data/SR/SR28/reports/sr28fg02.pdf"

PROFILES = [
    {"id":"onion-diced", "label":"Fresh chopped/diced onion", "grams":"142", "per":"cup", "source":KING_ARTHUR},
    {"id":"garlic-clove", "label":"Raw garlic clove", "grams":"3", "per":"clove", "source":GARLIC},
    {"id":"garlic-bulb", "label":"Raw garlic bulb/head", "grams":"24", "per":"bulb", "source":GARLIC},
    {"id":"garlic-minced", "label":"Minced fresh garlic", "grams":"14", "per":"tbsp", "source":KING_ARTHUR},
    {"id":"white-sugar", "label":"Granulated white sugar", "grams":"198", "per":"cup", "source":KING_ARTHUR},
    {"id":"table-salt", "label":"Fine table salt (not kosher/flaked salt)", "grams":"18", "per":"tbsp", "source":KING_ARTHUR},
    {"id":"dried-basil", "label":"Dried basil leaves", "grams":"0.7", "per":"tsp", "source":USDA},
    {"id":"dried-oregano", "label":"Dried oregano leaves", "grams":"1", "per":"tsp", "source":USDA},
    {"id":"tomato-paste", "label":"Tomato paste", "grams":"14.5", "per":"tbsp", "source":KING_ARTHUR},
    {"id":"vegetable-oil", "label":"Vegetable oil", "grams":"198", "per":"cup", "source":KING_ARTHUR},
    {"id":"italian-herbs-demo", "label":"Italian dried-herb blend (demo proxy)", "grams":"1", "per":"tsp", "source":None,
     "always_review":True, "limitation":"Demo loose-herb planning assumption, not a verified blend density; whole-basket review required."},
]
PROFILE_MAP = {p["id"]:p for p in PROFILES}
MASS = {"kg":"1", "kilogram":"1", "kilograms":"1", "g":"0.001", "gram":"0.001", "grams":"0.001", "mg":"0.000001",
        "oz":"0.028349523125", "ounce":"0.028349523125", "ounces":"0.028349523125",
        "lb":"0.45359237", "lbs":"0.45359237", "pound":"0.45359237", "pounds":"0.45359237"}
VOLUME = {"l":"1", "litre":"1", "litres":"1", "liter":"1", "liters":"1", "ml":"0.001", "millilitre":"0.001", "millilitres":"0.001", "milliliter":"0.001", "milliliters":"0.001", "dl":"0.1", "cl":"0.01"}
Q = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
UNIT = r"(?:us\s+(?:fl\s*oz|fluid\s+ounces?)|imperial\s+(?:fl\s*oz|fluid\s+ounces?)|fl\s*oz|fluid\s+ounces?|kilograms?|grams?|millilit(?:re|er)s?|lit(?:re|er)s?|pounds?|ounces?|tablespoons?|teaspoons?|garlic\s+cloves?|cloves?|heads?|bulbs?|cups?|tbsp|tsp|lbs?|oz|kg|mg|ml|dl|cl|g|l)"
PACK = r"(?:cans?|tins?|packages?|packs?|bags?|jars?|bottles?)"


def clean(text):
    text = text.casefold().replace("–", "-").replace("—", "-")
    for char,value in {"½":"1/2", "¼":"1/4", "¾":"3/4", "⅓":"1/3", "⅔":"2/3", "⅛":"1/8", "⅜":"3/8"}.items():
        text = text.replace(char," " + value)
    text = re.sub(r"(?<=\d)-(?=\d+/\d+)", " ", text)
    text = text.replace("fl. oz.","fl oz").replace("oz.","oz").replace("lb.","lb").replace("lbs.","lbs").replace("tsp.","tsp").replace("tbsp.","tbsp")
    return " ".join(text.split())


def amount(text):
    try:
        parts = text.split()
        total = sum((Fraction(part) for part in parts),Fraction(0))
        value = Decimal(total.numerator) / Decimal(total.denominator)
        return value if value.is_finite() and value > 0 else None
    except (ValueError,ZeroDivisionError,InvalidOperation):
        return None


def parse(text):
    """Parse whole source measures; never consume a prefix of a complex/range measure."""
    text = clean(text)
    text = re.sub(r'\b(cloves?|heads?|bulbs?)\s+(?:of\s+)?garlic$',r'\1',text)
    text = re.sub(r'\bgarlic\s+(?=heads?|bulbs?)','',text)
    text = re.sub(r',\s*(?:finely\s+)?(?:minced|chopped|diced|crushed|peeled)$','',text)
    text = re.sub(r'\b(?:large|medium|small|fresh)\s+(?=(?:garlic\s+)?cloves?\b)','',text)
    # Strip preparation labels without consuming numeric equivalents or ranges.
    prep=r'(?:finely\s+|roughly\s+)?(?:minced|chopped|diced|crushed|peeled)(?:(?:,\s*|\s+and\s+)(?:finely\s+|roughly\s+)?(?:minced|chopped|diced|crushed|peeled))*'
    text=re.sub(rf'(?:,\s*|\s*\(\s*){prep}\s*\)?$','',text).strip()
    text=re.sub(r'\b(cloves?|heads?|bulbs?)\s+(?:of\s+)?(?:fresh\s+)?garlic\b',r'\1',text)
    text=re.sub(r'\b(?:large|medium|small|fresh)\s+(?=(?:garlic\s+)?cloves?\b)','',text)
    named_garlic=re.fullmatch(rf'(?P<n>{Q})\s*(?P<u>tbsp|tsp|tablespoons?|teaspoons?)\s+(?:of\s+)?(?:minced|chopped)\s+(?:fresh\s+)?garlic',text)
    if named_garlic:text=named_garlic['n']+' '+named_garlic['u']
    # A recipe can supply its own metric equivalent: prefer it to an estimate.
    equivalent=re.fullmatch(rf'(?P<count>{Q})\s*(?:garlic\s+)?(?:cloves?|heads?|bulbs?)\s*\(\s*(?P<size>{Q})\s*(?P<u>g|kg|grams?|kilograms?)\s*(?P<each>each)?\s*\)',text)
    if equivalent:
        n=amount(equivalent['count']) if equivalent['each'] else Decimal(1)
        size=amount(equivalent['size'])
        if n is not None and size is not None:return n*size,equivalent['u'],n
    patterns = [
        rf"(?P<n>{Q})\s*{PACK}\s*(?:[x×]|\()\s*(?P<size>{Q})\s*[- ]?\s*(?P<u>{UNIT})\s*(?:each)?\s*\)?",
        rf"(?P<n>{Q})\s*\(\s*(?P<size>{Q})\s*[- ]?\s*(?P<u>{UNIT})\s*(?:each)?\s*\)\s*{PACK}(?:\s+each)?",
        rf"(?P<n>{Q})\s*{PACK}\s+(?P<size>{Q})\s*(?P<u>{UNIT})\s+each",
        rf"(?P<n>{Q})\s*[x×]\s*(?P<size>{Q})\s*(?P<u>{UNIT})(?:\s+each)?",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern,text)
        if match:
            n,size = amount(match['n']),amount(match['size'])
            if n is not None and n == n.to_integral_value() and size is not None:
                return n * size, match['u'], n
            return None
    match = re.fullmatch(rf"(?P<n>{Q})\s*(?P<u>{UNIT})",text)
    if match and amount(match['n']) is not None:
        return amount(match['n']),match['u'],Decimal(1)
    return None


def profile_for(name, unit):
    name = clean(name)
    # State-specific profiles must never be used for powders, sauces or fresh herbs.
    words = set(re.findall(r"[a-z]+",name))
    if 'garlic' in words and not words & {'powder','salt','paste','sauce','oil','granulated'}:
        if unit == 'clove':return PROFILE_MAP['garlic-clove']
        if unit == 'bulb':return PROFILE_MAP['garlic-bulb']
        if 'minced' in words or 'chopped' in words:return PROFILE_MAP['garlic-minced']
    if ('onion' in words or 'onions' in words) and not words & {'dried','powder','flakes','fried','soup','salt','juice','sliced'}:
        return PROFILE_MAP['onion-diced']
    if 'sugar' in words and not words & {'brown','icing','powdered','caster','coconut','substitute','free','sweetener'}:return PROFILE_MAP['white-sugar']
    if 'salt' in words and not words & {'kosher','flaked','flakes','coarse','garlic','onion','seasoned'}:return PROFILE_MAP['table-salt']
    if 'basil' in words and 'dried' in words and 'ground' not in words:return PROFILE_MAP['dried-basil']
    if 'oregano' in words and 'dried' in words and 'ground' not in words:return PROFILE_MAP['dried-oregano']
    if 'italian' in words and ('seasoning' in words or 'herbs' in words) and not words & {'sauce','paste','fresh','oil'}:return PROFILE_MAP['italian-herbs-demo']
    if {'tomato','paste'}.issubset(words):return PROFILE_MAP['tomato-paste']
    if {'vegetable','oil'}.issubset(words):return PROFILE_MAP['vegetable-oil']
    return None


def named_metric_measure(ingredient):
    """Accept an explicit metric weight/volume with ingredient-name decoration.

    No prefix-only parsing: ranges, pack counts, per-person text and extra numbers
    are rejected here. Per-serving quantities have a separate checked rule.
    """
    raw=clean(ingredient.original_measure)
    metric=r'(?:kg|g|mg|ml|cl|dl|l|kilograms?|grams?|millilit(?:re|er)s?|lit(?:re|er)s?)'
    patterns=[rf'(?P<measure>{Q}\s*{metric})\s+(?P<label>.+)',rf'(?P<label>.+?)\s*[:,]\s*(?P<measure>{Q}\s*{metric})']
    allowed=set(re.findall(r'[a-z]+',clean(ingredient.name)))|{'dry','dried','uncooked','fresh','chopped','minced','peeled','grated','finely','roughly','weight'}
    for pattern in patterns:
        match=re.fullmatch(pattern,raw)
        if not match:continue
        label=match['label'];words=set(re.findall(r'[a-z]+',label))
        if words and words<=allowed and not re.search(r'[0-9/×+\-]',label):
            return parse(match['measure'])
    return None


def per_serving_measure(ingredient,base,mode):
    raw=clean(ingredient.original_measure)
    match=re.fullmatch(rf'(?P<measure>{Q}\s*{UNIT})\s*(?:per\s+|/\s*)(?:person|portion|serving|adult)(?:\s*[x×]\s*(?P<count>{Q}))?',raw)
    if not match or base is None or base<=0:return None
    if match['count'] and amount(match['count'])!=base:return None
    probe=ingredient.model_copy(update={'original_measure':match['measure'],'quantity':None,'unit':'UNRESOLVED'})
    evidence=resolve(probe,mode)
    if evidence['quantity'] is None:return None
    return {**evidence,'quantity':evidence['quantity']*base,'rule':'explicit-per-serving',
        'description':'Source explicitly gives '+ingredient.original_measure+'. Converted to the original recipe yield before scaling; not a second portion multiplier.'}


def resolve(ingredient, mode='strict'):
    """Return source-yield amount/unit/evidence, prior to portion scaling."""
    raw = ingredient.original_measure
    parsed = parse(raw) or named_metric_measure(ingredient)
    if parsed:
        number,unit,pack_count = parsed
        if unit in MASS:
            return {"quantity":number*Decimal(MASS[unit]), "unit":"KG", "estimated":False, "rule":"mass-unit", "source":NIST,
                    "description":f"{raw} converted from source weight; oz means weight, never fluid ounces.","always_review":False}
        if unit in VOLUME:
            return {"quantity":number*Decimal(VOLUME[unit]), "unit":"L", "estimated":False,"rule":"metric-volume", "source":NIST,
                    "description":f"{raw} converted from metric volume.","always_review":False}
        if unit.startswith('us ') or unit.startswith('imperial '):
            factor = Decimal('0.0284130625') if unit.startswith('imperial ') else Decimal('0.0295735295625')
            return {"quantity":number*factor,"unit":"L","estimated":False,"rule":"explicit-fluid-ounce","source":NIST,
                    "description":f"{raw}: explicitly named fluid-ounce system; no mass/density conversion.","always_review":False}
        if mode == 'kitchen':
            simple = {'cups':'cup','tablespoon':'tbsp','tablespoons':'tbsp','teaspoon':'tsp','teaspoons':'tsp','cloves':'clove','garlic clove':'clove','garlic cloves':'clove','head':'bulb','heads':'bulb','bulbs':'bulb'}.get(unit,unit)
            profile = profile_for(ingredient.name+' '+raw,simple)
            if profile and (simple in {'clove','bulb'} and profile['per']==simple or simple in {'cup','tbsp','tsp'} and profile['per'] not in {'clove','bulb'}):
                tsp = {'cup':Decimal(48),'tbsp':Decimal(3),'tsp':Decimal(1),'clove':Decimal(1),'bulb':Decimal(1)}
                value = number * Decimal(profile['grams']) * tsp[simple] / tsp[profile['per']] / Decimal(1000)
                return {"quantity":value,"unit":"KG","estimated":True,"rule":profile['id'],"source":profile['source'],
                        "description":f"Planning estimate: {profile['label']}, {profile['grams']} g/{profile['per']}. US household proportions (1 cup = 16 tbsp = 48 tsp); edible quantity, no peeling/yield allowance.",
                        "always_review":profile.get('always_review',False),"limitation":profile.get('limitation'),"profile_version":VERSION}
            # Convert cooking volume to litres only for liquids, never chopped solids.
            words = set(re.findall(r'[a-z]+',clean(ingredient.name)))
            liquid = bool(words & {'water','milk','stock','broth','oil','vinegar'}) and not words & {'powder','dried','granules','cube','cubes','paste'}
            if liquid and simple in {'cup','tbsp','tsp','fl oz','fluid ounce','fluid ounces'}:
                factors = {'cup':'0.2365882365','tbsp':'0.01478676478125','tsp':'0.00492892159375','fl oz':'0.0295735295625','fluid ounce':'0.0295735295625','fluid ounces':'0.0295735295625'}
                return {"quantity":number*Decimal(factors[simple]),"unit":"L","estimated":True,"rule":"us-household-volume","source":NIST,
                        "description":"Buyer-allowed US household volume assumption; volume remains volume, no density inferred.","always_review":False,"profile_version":VERSION}
        return {"quantity":None,"unit":"UNRESOLVED","estimated":False,"rule":"unsupported-measure","source":None,
                "description":"No permitted conversion for this ingredient/measure. Try a metric recipe or allow the listed kitchen estimates.","always_review":True}
    if re.search(r'\b(cups?|cloves?|tbsp|tsp|tablespoons?|teaspoons?|cans?|tins?|to taste|pinch|dash|as needed|ounces?|oz|pounds?|lbs?)\b',clean(raw)):
        return {"quantity":None,"unit":"UNRESOLVED","estimated":False,"rule":"ambiguous-measure","source":None,
                "description":"Source measure is ambiguous or lacks a pack size; no guessed quantity was used.","always_review":True}
    value = amount(str(ingredient.quantity)) if ingredient.quantity is not None else None
    return {"quantity":value if ingredient.unit in {'KG','L'} else None,"unit":ingredient.unit,
            "estimated":False,"rule":"extracted-metric","source":None,"description":"Metric quantity extracted from the recipe; no kitchen estimate applied.","always_review":False}


def public_profiles():
    return {"version":VERSION,"profiles":PROFILES,"scope":"Opt-in planning estimates; preparation, spoon/cup packing and actual product density vary. No allergen or nutrition certification."}
