from urllib.parse import quote

from agent.tools.sandbox_web_search_tool import SandboxWebSearchTool


def _tool() -> SandboxWebSearchTool:
    return SandboxWebSearchTool(project_id="test-project", thread_manager=None)


def test_normalize_duckduckgo_redirect_filters_encoded_yjs_ad_link():
    tool = _tool()
    encoded_target = quote(
        "https://duckduckgo.com/y.js?ad_domain=mcafee.com&ad_provider=bingv7aa",
        safe="",
    )
    raw_url = f"//duckduckgo.com/l/?uddg={encoded_target}&rut=abc"

    assert tool._normalize_duckduckgo_url(raw_url) == ""


def test_normalize_duckduckgo_redirect_filters_encoded_bing_aclick():
    tool = _tool()
    encoded_target = quote(
        "https://www.bing.com/aclick?ld=test-click&foo=bar",
        safe="",
    )
    raw_url = f"//duckduckgo.com/l/?uddg={encoded_target}&rut=abc"

    assert tool._normalize_duckduckgo_url(raw_url) == ""


def test_extract_duckduckgo_results_skips_ads_and_keeps_real_results():
    tool = _tool()
    encoded_ad = quote(
        "https://duckduckgo.com/y.js?ad_domain=mcafee.com&ad_provider=bingv7aa",
        safe="",
    )
    encoded_real = quote("https://example.com/real-article", safe="")
    html = (
        f'<a class="result__a" href="//duckduckgo.com/l/?uddg={encoded_ad}&rut=1">Ad</a>'
        f'<a class="result__a" href="//duckduckgo.com/l/?uddg={encoded_real}&rut=2">Real</a>'
    )

    results = tool._extract_duckduckgo_results(html, max_results=10)

    assert len(results) == 1
    assert results[0]["title"] == "Real"
    assert results[0]["url"] == "https://example.com/real-article"


def test_extract_bing_results_skips_aclick_ads():
    tool = _tool()
    html = (
        '<li class="b_algo"><h2><a href="https://www.bing.com/aclick?ld=ad">Ad</a></h2></li>'
        '<li class="b_algo"><h2><a href="https://openai.com/news/">OpenAI News</a></h2></li>'
    )

    results = tool._extract_bing_results(html, max_results=5)

    assert len(results) == 1
    assert results[0]["title"] == "OpenAI News"
    assert results[0]["url"] == "https://openai.com/news/"
