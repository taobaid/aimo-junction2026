"""Live Claude + catalogue + mock-stock check. Creates no order or saved proposal."""
import argparse
from datetime import date
import json
import sys
import aimo_api as gateway
import recipe_agent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dish',default='Spaghetti bolognese')
    p.add_argument('--date',required=True,type=date.fromisoformat)
    p.add_argument('--portions',default=200,type=int)
    p.add_argument('--preferences',default='')
    p.add_argument('--published',action='store_true',help='Research a published recipe instead of the faster AI draft')
    p.add_argument('--fresh',action='store_true',help='Find a new recipe instead of reusing a successful one')
    p.add_argument('--strict',action='store_true',help='Disable the documented kitchen estimates')
    p.add_argument('--run',action='store_true',help='Make paid Claude calls and mock price/availability calls')
    args=p.parse_args()
    if not args.run:
        print('Add --run to test this dish with your configured Claude API and mock supplier APIs. This uses API credit; no order/proposal will be created.')
        return 0
    try:
        if args.date<gateway.core.utc_now().date():p.error('Choose a current/future delivery date.')
        if not gateway.setting('AIMO_API_KEY'):p.error('Set AIMO_API_KEY in this terminal.')
        import claude_recipe
        if claude_recipe.configuration(gateway)['provider']!='anthropic':p.error('Set RECIPE_PROVIDER=anthropic and ANTHROPIC_API_KEY for this Claude check.')
        request=recipe_agent.RecipeRequest(request=args.dish,portions=args.portions,delivery_date=args.date,preferences=args.preferences,planning_mode='published' if args.published else 'quick',refresh_recipe=args.fresh,measurement_mode='strict' if args.strict else 'kitchen')
        print('Finding a recipe, converting amounts, matching products and checking stock. This may take several minutes.',flush=True)
        recipe,sources,prepared=recipe_agent.source_meal(gateway,request)
        rows,lines,issues,net,gross=prepared[-1]
        complete=recipe.ingredient_list_complete and not recipe.missing_ingredients
        ready=complete and not issues and bool(lines)
        report={'dish':recipe.title,'source':recipe.source_url,'provenance':recipe.provenance,'original_servings':recipe.source_servings,
            'portions':request.portions,'delivery_date':str(args.date),'ready_for_review':ready,
            'recipe_reused':any(a['step']=='RECIPE_REUSED' for a in prepared[4]),'measurement_mode':request.measurement_mode,'recipe_complete':complete,'missing_ingredients':recipe.missing_ingredients,
            'subtotal_including_tax':str(gross) if gross is not None else None,'changes':prepared[3],
            'ingredients':[{'name':i['name'],'required':str(i['required_quantity']) if i['required_quantity'] is not None else None,'unit':i['unit'],'status':i['status'],'selected_product':i.get('selected_name'),'reasons':i['reasons']} for i in rows],
            'issues':issues,'proposal_created':False,'order_created':False}
        print(json.dumps(report,ensure_ascii=False,indent=2,default=str))
        return 0 if ready else 2
    except (RuntimeError,ValueError) as exc:
        print('Dish check failed:',str(exc));return 1

if __name__=='__main__':sys.exit(main())
