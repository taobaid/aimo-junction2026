"""Native Claude Messages adapter for the recipe pipeline. No credentials in outputs.

Search is separate from JSON extraction because web citations and strict JSON
formatting are incompatible. No shell, code execution or purchase tools are exposed.
"""
from urllib.parse import urlsplit
import math
import httpx
import planning_budget


def configuration(g):
    provider = g.setting("RECIPE_PROVIDER").lower()
    if not provider:
        provider = "anthropic" if g.setting("ANTHROPIC_API_KEY") else "openai"
    if provider == "claude":
        provider = "anthropic"
    if provider not in ("anthropic", "openai"):
        raise RuntimeError("Recipe AI is not configured: RECIPE_PROVIDER must be anthropic or openai.")
    if provider == "anthropic":
        return {"provider": provider, "key": g.setting("ANTHROPIC_API_KEY"),
                "model": g.setting("RECIPE_MODEL") or g.setting("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
                "base": g.setting("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")}
    return {"provider": provider, "key": g.setting("LLM_API_KEY"),
            "model": g.setting("RECIPE_MODEL") or g.setting("LLM_MODEL"),
            "base": (g.setting("RECIPE_BASE_URL") or g.setting("LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")}


def compatible_schema(node):
    """Claude wire schema subset; Pydantic still validates the full schema locally."""
    if isinstance(node,list):return [compatible_schema(item) for item in node]
    if not isinstance(node,dict):return node
    unsupported={'maxItems','uniqueItems','contains','minContains','maxContains',
                 'minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf',
                 'minLength','maxLength'}
    result={};constraints=[]
    for key,value in node.items():
        if key in unsupported or key=='minItems' and value not in (0,1):
            constraints.append(key+'='+str(value));continue
        if key in {'properties','$defs','definitions','patternProperties'} and isinstance(value,dict):
            result[key]={name:compatible_schema(child) for name,child in value.items()}
        else:result[key]=compatible_schema(value)
    if constraints:
        result['description']=(result.get('description','')+' Local validation requires '+', '.join(constraints)+'.').strip()
    return result


def call(g, body, config, *, max_tokens=8192):
    if not config["key"]:
        raise RuntimeError("Claude recipe AI is not configured. Set ANTHROPIC_API_KEY in the SERVER PowerShell terminal, then restart. Use a Claude Console API key from the workspace with your credits; the Valio key is separate.")
    headers = {"x-api-key": config["key"], "anthropic-version": "2023-06-01"}
    if g.setting("ANTHROPIC_WORKSPACE_ID"):
        headers["anthropic-workspace-id"] = g.setting("ANTHROPIC_WORKSPACE_ID")
    try:
        read_seconds = float(g.setting("ANTHROPIC_READ_TIMEOUT", "300"))
        if not math.isfinite(read_seconds) or not 30 <= read_seconds <= 600:
            raise ValueError
    except ValueError:
        raise RuntimeError("Claude timeout is not configured correctly: ANTHROPIC_READ_TIMEOUT must be 30–600 seconds.") from None
    stage = "recipe web research" if body.get("tools") else "recipe extraction" if "ingredients" in body.get("text", {}).get("format", {}).get("schema", {}).get("properties", {}) else "catalogue matching" if body.get("text") else "API connection test"
    payload = {"model": config["model"], "max_tokens": max_tokens,
               "system": body.get("instructions", ""),
               "messages": [{"role": "user", "content": body.get("input", "")} ]}
    search = bool(body.get("tools"))
    if search:
        payload["system"] += " You MUST use web_search for this request. Do not answer from memory. Cite each source used for recipe quantities and serving yield."
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3},
            {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 2, "max_content_tokens": 12000, "citations": {"enabled": True}}]
        payload["system"] += " Open the chosen recipe using web_fetch and retrieve its full ingredient list and serving yield. Search snippets are not a complete recipe. If access fails, choose a different published recipe."
    elif body.get("text", {}).get("format"):
        payload["output_config"] = {"format": {"type": "json_schema", "schema": compatible_schema(body["text"]["format"]["schema"])}}
    read_seconds=planning_budget.timeout(read_seconds)
    blocks = []
    search_count = 0
    fetch_count = 0
    try:
        with httpx.Client(timeout=httpx.Timeout(read_seconds, connect=20, write=30, pool=20), follow_redirects=False) as client:
            for turn in range(3):
                planning_budget.check(stage)
                client.timeout=httpx.Timeout(planning_budget.timeout(read_seconds),connect=min(20,planning_budget.timeout(20)),write=min(30,planning_budget.timeout(30)),pool=min(20,planning_budget.timeout(20)))
                response = client.post(config["base"] + "/messages", headers=headers, json=payload)
                if response.status_code >= 400:
                    help_text = {400: "Check model support, workspace selection and web-search access.",
                        401: "Check ANTHROPIC_API_KEY; use a Claude Console API key, not a Claude chat login.",
                        402: "Check your Anthropic API credit balance.",
                        403: "Check API key permissions, workspace and model/web-search access.",
                        404: "Check ANTHROPIC_MODEL and the API endpoint.",
                        429: "Rate limit or credit limit reached. Wait for the provider's retry interval before trying again.",
                        529: "Claude is temporarily overloaded. Try again later."}.get(response.status_code, "Try again later or check the Claude Console.")
                    raise RuntimeError(f"Claude recipe provider HTTP {response.status_code} during {stage}. {help_text} No recipe/order was invented.")
                try:
                    result = response.json()
                except ValueError:
                    mime = response.headers.get("content-type", "").split(";")[0].lower()
                    safe_mime = mime if mime in {"application/json", "text/html", "text/plain", "text/event-stream"} else "unknown content type"
                    raise RuntimeError(f"Claude returned non-JSON data during {stage} (HTTP {response.status_code}, {safe_mime}). A proxy, captive portal or provider gateway may have returned a page instead of the API response. Run python claude_check.py. No raw response or credentials were logged.") from None
                if not isinstance(result, dict):
                    raise RuntimeError(f"Claude returned an unexpected JSON shape during {stage}; expected a message object. Run python claude_check.py.")
                content = result.get("content")
                if not isinstance(content, list):
                    raise RuntimeError("Claude returned an invalid message body. No recipe was accepted.")
                blocks.extend(content)
                search_count += sum(b.get("type") == "server_tool_use" and b.get("name") == "web_search" for b in content)
                fetch_count += sum(b.get("type") == "server_tool_use" and b.get("name") == "web_fetch" for b in content)
                if search_count > 3:
                    raise RuntimeError("Claude exceeded the three-search recipe budget. Narrow the meal request and retry.")
                if fetch_count > 2:
                    raise RuntimeError("Claude exceeded the two-page recipe fetch budget. Retry with an accessible complete recipe source.")
                reason = result.get("stop_reason")
                if reason == "pause_turn" and search and turn < 2 and search_count < 3 and fetch_count < 2:
                    # Preserve encrypted search results and tool IDs exactly.
                    payload["messages"].append({"role": "assistant", "content": content})
                    payload["tools"][0]["max_uses"] = 3 - search_count
                    payload["tools"][1]["max_uses"] = max(1, 2 - fetch_count)
                    continue
                if reason != "end_turn":
                    raise RuntimeError("Claude recipe response was incomplete or refused (" + str(reason) + "). No partial recipe was accepted.")
                return normalize(blocks, search)
    except httpx.ReadTimeout:
        planning_budget.check(stage)
        raise RuntimeError(f"Claude read timeout during {stage}: no complete response within {read_seconds:g} seconds. This does not establish an API-key problem. Run python claude_check.py; for slow searches set ANTHROPIC_READ_TIMEOUT=600 and restart. The request was not automatically repeated.") from None
    except httpx.ConnectTimeout:
        raise RuntimeError(f"Claude connection timeout during {stage}: the server could not connect within 20 seconds. Check internet, DNS, firewall or proxy access to api.anthropic.com. Run python claude_check.py.") from None
    except httpx.TimeoutException:
        raise RuntimeError(f"Claude request timed out during {stage} before completion. Run python claude_check.py to separate API access from recipe-search latency. The request was not automatically repeated.") from None
    except httpx.ConnectError:
        raise RuntimeError(f"Claude connection failed during {stage} (ConnectError). Check DNS, TLS certificates, firewall and proxy settings for api.anthropic.com. Run python claude_check.py. Certificate verification remains enabled.") from None
    except httpx.RequestError as exc:
        kind = type(exc).__name__
        raise RuntimeError(f"Claude transport failed during {stage} ({kind}). The connection may have closed before the response finished. Run python claude_check.py. The request was not automatically repeated.") from None
    raise RuntimeError("Claude recipe search did not finish within the bounded request window.")


def normalize(blocks, search):
    sources = {}
    fetched = {}
    for block in blocks:
        if block.get("type") == "web_search_tool_result":
            content = block.get("content")
            if isinstance(content, dict):
                code = content.get("error_code", "unknown_search_error")
                # Do not expose arbitrary remote text or fall back to model memory.
                known = {"too_many_requests", "invalid_tool_input", "max_uses_exceeded", "query_too_long", "request_too_large", "unavailable"}
                raise RuntimeError("Claude web search failed: " + (code if code in known else "search_error") + ". No source-free recipe was accepted.")
            for item in content or []:
                if item.get("type") == "web_search_result" and urlsplit(item.get("url", "")).scheme in ("https", "http"):
                    sources[item["url"]] = item.get("title") or item["url"]
        elif block.get("type") == "web_fetch_tool_result":
            item = block.get("content") or {}
            if isinstance(item, dict) and item.get("type") == "web_fetch_result" and urlsplit(item.get("url", "")).scheme in ("http", "https"):
                fetched[item["url"]] = item.get("content", {}).get("title") or item["url"]
    if search:
        # Recipe extraction may only choose a page actually opened, not a snippet.
        sources = fetched
    parts = []
    for block in blocks:
        if block.get("type") == "text":
            annotations = [{"type": "url_citation", "url": c["url"], "title": c.get("title") or c["url"]}
                           for c in block.get("citations", []) if c.get("url") in sources]
            parts.append({"type": "output_text", "text": block.get("text", ""), "annotations": annotations})
    if not parts:
        raise RuntimeError("Claude returned no recipe text. No recipe was accepted.")
    output = []
    if search and sources and any(b.get("type") == "server_tool_use" and b.get("name") == "web_search" for b in blocks):
        output.append({"type": "web_search_call", "action": {"sources": [{"url": u, "title": t} for u,t in sources.items()]}})
    output.append({"type": "message", "content": parts})
    return {"status": "completed", "output": output}
