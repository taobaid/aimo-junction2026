"""External agent entry point for one complete recipe basket."""
import argparse
import json
import os
import sys
import httpx
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request',help='E.g. spaghetti bolognese for 200 people')
    parser.add_argument('--portions',type=int,default=200)
    parser.add_argument('--date',required=True)
    parser.add_argument('--published',action='store_true',help='Research a published recipe instead of the faster AI draft')
    parser.add_argument('--preferences',default='')
    parser.add_argument('--recipe-url',default='',help='Use this exact public recipe URL')
    parser.add_argument('--recipe-file',help='UTF-8 text file containing the full recipe and original serving yield')
    parser.add_argument('--kitchen-estimates',action='store_true',help='Use buyer-enabled ingredient estimate profiles')
    parser.add_argument('--automatic',action='store_true',help='Requires buyer-enabled server autonomy; mock commit only within whole-basket authority')
    args=parser.parse_args()
    token=os.environ.get('AIMO_AGENT_TOKEN','').strip()
    if not token:parser.error('Set the actual AIMO_AGENT_TOKEN printed by the running gateway.')
    try:
        recipe_text=Path(args.recipe_file).read_text(encoding='utf-8-sig') if args.recipe_file else ''
        if len(recipe_text)>20000:parser.error('Recipe file must be at most 20000 characters.')
        gateway_url=os.environ.get('AIMO_GATEWAY_URL','http://127.0.0.1:8000')
        with httpx.Client(base_url=gateway_url,timeout=1800,trust_env=urlsplit(gateway_url).hostname not in {'localhost','127.0.0.1','::1'},
                          headers={'Authorization':'Bearer '+token}) as client:
            response=client.post('/recipe-plans',json={'request':args.request,'portions':args.portions,
                'delivery_date':args.date,'planning_mode':'published' if args.published else 'quick','preferences':args.preferences,'recipe_url':args.recipe_url,'recipe_text':recipe_text,'autonomy':'automatic' if args.automatic else 'review',
                'auto_commit':args.automatic,'measurement_mode':'kitchen' if args.kitchen_estimates else 'strict'})
        if not response.is_success:
            print('Gateway HTTP',response.status_code,response.text);return 1
        p=response.json()
        print(p['id'],'|',p['recipe']['title'],'|',p['status'])
        print('Recipe source:',p['recipe']['source_url'])
        for row in p['ingredients']:
            print(row['name'],':',row['required_quantity'] or 'Unknown',row['unit'],'→',row['selected_name'] or row['status'])
        print('Combined subtotal including tax:',p['total_gross_eur'] or 'INCOMPLETE','EUR')
        for issue in p['issues']:print('BLOCKED:',issue)
        if p['mock_order']:print('Mock receipt:',p['mock_order']['id'],'— no supplier order sent.')
        else:print('Review the whole meal under Plan a meal → Recent meal plans in the dashboard.')
        return 0
    except (OSError,UnicodeError) as exc:
        print('Could not read recipe file:',type(exc).__name__);return 1
    except httpx.RequestError as exc:
        print('Gateway connection failed:',type(exc).__name__);return 1


if __name__=='__main__':sys.exit(main())
