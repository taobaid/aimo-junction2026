"""Small Claude API diagnostic. Prints no secrets and creates no purchase plan."""
import argparse
from datetime import date
import sys
import aimo_api as gateway
import claude_recipe
import recipe_agent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--search',action='store_true',help='Also run a paid recipe search/fetch/extraction test; no supplier calls or saved purchase plan')
    args=parser.parse_args()
    try:
        config=claude_recipe.configuration(gateway)
        if config['provider']!='anthropic':
            print('Set RECIPE_PROVIDER=anthropic in this PowerShell terminal.');return 1
        print('Claude key present:', 'yes (hidden)' if config['key'] else 'no')
        print('Testing one short Claude message. This uses a small amount of API credit.')
        result=claude_recipe.call(gateway,{'instructions':'Return exactly OK. Do not use tools.','input':'Connection test.'},config,max_tokens=32)
        recipe_agent.response_text(result)  # Verify text exists without printing model output.
        print('PASS: Claude returned a valid message. API key/model access worked for this call.')
        print('This short test does not check web-search/fetch access. Use --search for that.')
        if args.search:
            print('Testing recipe search, full-page retrieval and extraction; this can take several minutes.')
            request=recipe_agent.RecipeRequest(request='Find a complete published metric spaghetti bolognese recipe.',portions=4,delivery_date=date.today())
            recipe,sources=recipe_agent.find_recipe(gateway,request)
            if not recipe.ingredient_list_complete or recipe.missing_ingredients:
                print('BLOCKED: Provider responded, but a complete recipe was not retrieved. No order was created.');return 2
            print('PASS: A recipe was searched, retrieved and extracted with',len(recipe.ingredients),'ingredients.')
            print('No Valio API calls, purchase plans or orders were created.')
        return 0
    except RuntimeError as exc:
        print('FAIL:',str(exc));return 1


if __name__=='__main__':sys.exit(main())
