import httpx
from dotenv import load_dotenv
from agentpress.tool import ToolResult
from utils.config import config
from sandbox.tool_base import SandboxToolsBase
from agentpress.adk_thread_manager import ADKThreadManager
import json
import os
import datetime
import asyncio
import logging
import re
import html as html_lib
from urllib.parse import parse_qs, unquote, urlparse

# Tavily is optional in local/dev environments.
try:
    from tavily import AsyncTavilyClient
except ImportError:
    AsyncTavilyClient = None

# TODO: add subpages, etc... in filters as sometimes its necessary 

class SandboxWebSearchTool(SandboxToolsBase):
    """Tool for performing web searches using Tavily API and web scraping using Firecrawl."""

    def __init__(self, project_id: str, thread_manager: ADKThreadManager):
        super().__init__(project_id, thread_manager)
        # 加载当前的环境变量，覆盖默认的环境变量
        load_dotenv(override=True)
    
        self.tavily_api_key = config.TAVILY_API_KEY
        self.firecrawl_api_key = config.FIRECRAWL_API_KEY
        self.firecrawl_url = config.FIRECRAWL_URL
        self.tavily_client = None
        self.tavily_unavailable_reason = None

        if AsyncTavilyClient is None:
            self.tavily_unavailable_reason = "tavily-python is not installed"
        elif not self.tavily_api_key:
            self.tavily_unavailable_reason = "TAVILY_API_KEY not found in configuration"
        else:
            # 获取 Tavily 的异步搜索客户端
            self.tavily_client = AsyncTavilyClient(api_key=self.tavily_api_key)

    async def web_search(
        self, 
        query: str,
        num_results: int = 20
    ) -> ToolResult:
        """
        Search the web for up-to-date information on a specific topic using the Tavily API.
        
        This tool allows you to gather real-time information from the internet to answer user queries, 
        research topics, validate facts, and find recent developments. Results include titles, URLs, 
        and publication dates. Use this tool for discovering relevant web pages before potentially 
        crawling them for complete content.
        
        Usage Examples:
            {
                "name": "web_search",
                "parameters": {
                    "query": "what is AlexManus and what are they building?",
                    "num_results": 20
                }
            }
            
            # Another search example
            {
                "name": "web_search",
                "parameters": {
                    "query": "latest AI research on transformer models",
                    "num_results": 20
                }
            }
        
        Args:
            query: The search query to find relevant web pages. Be specific and include key terms 
                  to improve search accuracy. For best results, use natural language questions or 
                  keyword combinations that precisely describe what you're looking for.
            num_results: The number of search results to return. Increase for more comprehensive 
                        research or decrease for focused, high-relevance results. Default is 20.
        
        Returns:
            ToolResult: Success with JSON string of search results, or failure with error message.
        """
        try:
            # 确保有一个有效的查询
            if not query or not isinstance(query, str):
                return self.fail_response("A valid search query is required.")

            if self.tavily_client is None:
                return await self._fallback_web_search(
                    query=query,
                    num_results=num_results,
                    fallback_reason=self.tavily_unavailable_reason or "Tavily client is unavailable.",
                )

            # 使用 Tavily 执行搜索
            search_response = await self.tavily_client.search(
                query=query,
                max_results=num_results,
                include_images=True,
                include_answer="advanced",
                search_depth="advanced",
            )
            
            # 检查是否实际有结果或答案
            results = search_response.get('results', [])
            answer = search_response.get('answer', '')
            
            # 返回完整的 Tavily 响应
            # 这包括查询、答案、结果、图像等
            
            # 考虑搜索成功，如果结果或答案存在
            if len(results) > 0 or (answer and answer.strip()):
                return ToolResult(
                    success=True,
                    output=json.dumps(search_response, ensure_ascii=False)
                )
            else:
                logging.warning(f"No Tavily results for query: '{query}', falling back to DuckDuckGo.")
                return await self._fallback_web_search(
                    query=query,
                    num_results=num_results,
                    fallback_reason="Tavily returned no results",
                )
        
        except Exception as e:
            error_message = str(e)
            logging.error(f"Error performing Tavily web search for '{query}': {error_message}")
            return await self._fallback_web_search(
                query=query,
                num_results=num_results,
                fallback_reason=f"Tavily error: {error_message[:200]}",
            )

    async def _fallback_web_search(
        self,
        query: str,
        num_results: int,
        fallback_reason: str,
    ) -> ToolResult:
        """Fallback search provider when Tavily is unavailable or fails."""
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/145.0.0.0 Safari/537.36"
                        )
                    },
                )
            response.raise_for_status()

            results = self._extract_duckduckgo_results(response.text, max_results=num_results)
            fallback_provider = "duckduckgo_html"

            if not results:
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    bing_response = await client.get(
                        "https://www.bing.com/search",
                        params={"q": query},
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/145.0.0.0 Safari/537.36"
                            )
                        },
                    )
                bing_response.raise_for_status()
                results = self._extract_bing_results(bing_response.text, max_results=num_results)
                if results:
                    fallback_provider = "bing_html"

            if not results:
                return self.fail_response(
                    f"Web search returned no results (fallback provider). Reason: {fallback_reason}"
                )

            payload = {
                "query": query,
                "answer": "",
                "results": results,
                "images": [],
                "fallback_provider": fallback_provider,
                "fallback_reason": fallback_reason,
            }
            return ToolResult(success=True, output=json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            fallback_error = str(e)
            logging.error(f"Fallback web search failed for '{query}': {fallback_error}")
            return self.fail_response(
                f"Error performing web search (Tavily and fallback failed): {fallback_error[:200]}"
            )

    def _extract_duckduckgo_results(self, html_content: str, max_results: int) -> list[dict]:
        """Extract title/url pairs from DuckDuckGo HTML results page."""
        pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        extracted: list[dict] = []

        for match in pattern.finditer(html_content):
            raw_url = html_lib.unescape(match.group(1))
            title_html = match.group(2)
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            if not title:
                continue

            url = self._normalize_duckduckgo_url(raw_url)
            if not url:
                continue

            extracted.append(
                {
                    "title": title,
                    "url": url,
                    "content": "",
                    "published_date": None,
                }
            )

            if len(extracted) >= max_results:
                break

        return extracted

    def _normalize_duckduckgo_url(self, raw_url: str) -> str:
        """Decode DuckDuckGo redirect URL to the original destination URL."""
        candidate = raw_url.strip()
        if not candidate:
            return ""

        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        elif candidate.startswith("/"):
            candidate = f"https://duckduckgo.com{candidate}"

        parsed = urlparse(candidate)
        parsed_netloc = parsed.netloc.lower()
        parsed_path = parsed.path.lower()
        parsed_query = parsed.query.lower()

        # DuckDuckGo sponsor hops and Bing ad click trackers are not useful sources.
        if self._is_blocked_search_url(
            parsed_netloc=parsed_netloc,
            parsed_path=parsed_path,
            parsed_query=parsed_query,
        ):
            return ""

        if parsed_netloc.endswith("duckduckgo.com") and parsed_path == "/l/":
            query_params = parse_qs(parsed.query)
            uddg = query_params.get("uddg", [""])[0]
            if not uddg:
                return candidate
            decoded = unquote(uddg)
            if not decoded or decoded == candidate:
                return candidate
            return self._normalize_duckduckgo_url(decoded)

        return candidate

    def _is_blocked_search_url(
        self,
        *,
        parsed_netloc: str,
        parsed_path: str,
        parsed_query: str,
    ) -> bool:
        return (
            (parsed_netloc.endswith("duckduckgo.com") and parsed_path.startswith("/y.js"))
            or (parsed_netloc.endswith("bing.com") and parsed_path.startswith("/aclick"))
            or ("ad_provider=" in parsed_query)
            or ("ad_domain=" in parsed_query)
        )

    def _extract_bing_results(self, html_content: str, max_results: int) -> list[dict]:
        """Extract title/url pairs from Bing HTML result page."""
        pattern = re.compile(
            r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>.*?<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        extracted: list[dict] = []

        for match in pattern.finditer(html_content):
            raw_url = html_lib.unescape(match.group(1))
            title_html = match.group(2)
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            if not title:
                continue

            parsed = urlparse(raw_url)
            parsed_netloc = parsed.netloc.lower()
            parsed_path = parsed.path.lower()
            parsed_query = parsed.query.lower()
            if self._is_blocked_search_url(
                parsed_netloc=parsed_netloc,
                parsed_path=parsed_path,
                parsed_query=parsed_query,
            ):
                continue

            extracted.append(
                {
                    "title": title,
                    "url": raw_url.strip(),
                    "content": "",
                    "published_date": None,
                }
            )
            if len(extracted) >= max_results:
                break

        return extracted

    async def scrape_webpage(
        self,
        urls: str
    ) -> ToolResult:
        """
        Extract full text content from multiple webpages in a single operation.
        
        IMPORTANT: You should ALWAYS collect multiple relevant URLs from web-search results and 
        scrape them all in a single call for efficiency. This tool saves time by processing 
        multiple pages simultaneously rather than one at a time. The extracted text includes 
        the main content of each page without HTML markup.
        
        ALWAYS collect multiple relevant URLs from search results and scrape them all at once
        rather than making separate calls for each URL. This is much more efficient.
        
        Usage Example:
            {
                "name": "scrape_webpage",
                "parameters": {
                    "urls": "https://github.com/Alexkeji"
                }
            }
        
        Args:
            urls: Multiple URLs to scrape, separated by commas. You should ALWAYS include several 
                 URLs when possible for efficiency. 
                 Example: 'https://example.com/page1,https://example.com/page2,https://example.com/page3'
        
        Returns:
            ToolResult: Success with message about scraped content and file paths, or failure with error message.
        """

        # 使用 Firecrawl API 进行网页内容爬取（提取 Markdown 格式）
        try:            
            # 确保 sandbox 已初始化
            await self._ensure_sandbox()

            if not self.firecrawl_api_key:
                return self.fail_response("FIRECRAWL_API_KEY not found in configuration")
            
            # 解析URL参数
            if not urls:
                logging.warning("Scrape attempt with empty URLs")
                return self.fail_response("Valid URLs are required.")
            
            # 切分URL字符串为列表
            url_list = [url.strip() for url in urls.split(',') if url.strip()]
            
            if not url_list:
                logging.warning("No valid URLs found in the input")
                return self.fail_response("No valid URLs provided.")
                
            if len(url_list) == 1:
                logging.warning("Only a single URL provided - for efficiency you should scrape multiple URLs at once")
            
            logging.info(f"Processing {len(url_list)} URLs: {url_list}")
            
            # 并发处理每个URL并收集结果
            tasks = [self._scrape_single_url(url) for url in url_list]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果，处理异常
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logging.error(f"Error processing URL {url_list[i]}: {str(result)}")
                    processed_results.append({
                        "url": url_list[i],
                        "success": False,
                        "error": str(result)
                    })
                else:
                    processed_results.append(result)
            
            results = processed_results

            
            # 总结结果
            successful = sum(1 for r in results if r.get("success", False))
            failed = len(results) - successful
            
            # 创建成功/失败消息
            if successful == len(results):
                message = f"Successfully scraped all {len(results)} URLs. Results saved to:"
                for r in results:
                    if r.get("file_path"):
                        message += f"\n- {r.get('file_path')}"
            elif successful > 0:
                message = f"Scraped {successful} URLs successfully and {failed} failed. Results saved to:"
                for r in results:
                    if r.get("success", False) and r.get("file_path"):
                        message += f"\n- {r.get('file_path')}"
                message += "\n\nFailed URLs:"
                for r in results:
                    if not r.get("success", False):
                        message += f"\n- {r.get('url')}: {r.get('error', 'Unknown error')}"
            else:
                error_details = "; ".join([f"{r.get('url')}: {r.get('error', 'Unknown error')}" for r in results])
                return self.fail_response(f"Failed to scrape all {len(results)} URLs. Errors: {error_details}")
            
            return ToolResult(
                success=True,
                output=message
            )
        
        except Exception as e:
            error_message = str(e)
            logging.error(f"Error in scrape_webpage: {error_message}")
            return self.fail_response(f"Error processing scrape request: {error_message[:200]}")
    
    async def _scrape_single_url(self, url: str) -> dict:
        """
        Helper function to scrape a single URL and return the result information.
        """
        
        # # Add protocol if missing
        # if not (url.startswith('http://') or url.startswith('https://')):
        #     url = 'https://' + url
        #     logging.info(f"Added https:// protocol to URL: {url}")
            
        logging.info(f"Scraping single URL: {url}")
        
        try:
            # ---------- Firecrawl scrape endpoint ----------
            logging.info(f"Sending request to Firecrawl for URL: {url}")
            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {self.firecrawl_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "url": url,
                    "formats": ["markdown"]
                }
                
                # Use longer timeout and retry logic for more reliability
                max_retries = 3
                timeout_seconds = 30
                retry_count = 0
                
                while retry_count < max_retries:
                    try:
                        logging.info(f"Sending request to Firecrawl (attempt {retry_count + 1}/{max_retries})")
                        response = await client.post(
                            f"{self.firecrawl_url}/v1/scrape",
                            json=payload,
                            headers=headers,
                            timeout=timeout_seconds,
                        )
                        response.raise_for_status()
                        data = response.json()
                        logging.info(f"Successfully received response from Firecrawl for {url}")
                        break
                    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError) as timeout_err:
                        retry_count += 1
                        logging.warning(f"Request timed out (attempt {retry_count}/{max_retries}): {str(timeout_err)}")
                        if retry_count >= max_retries:
                            raise Exception(f"Request timed out after {max_retries} attempts with {timeout_seconds}s timeout")
                        # Exponential backoff
                        logging.info(f"Waiting {2 ** retry_count}s before retry")
                        await asyncio.sleep(2 ** retry_count)
                    except Exception as e:
                        # Don't retry on non-timeout errors
                        logging.error(f"Error during scraping: {str(e)}")
                        raise e

            # Format the response
            title = data.get("data", {}).get("metadata", {}).get("title", "")
            markdown_content = data.get("data", {}).get("markdown", "")
            logging.info(f"Extracted content from {url}: title='{title}', content length={len(markdown_content)}")
            
            formatted_result = {
                "title": title,
                "url": url,
                "text": markdown_content
            }
            
            # Add metadata if available
            if "metadata" in data.get("data", {}):
                formatted_result["metadata"] = data["data"]["metadata"]
                logging.info(f"Added metadata: {data['data']['metadata'].keys()}")
            
            # Create a simple filename from the URL domain and date
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Extract domain from URL for the filename
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace("www.", "")
            
            # Clean up domain for filename
            domain = "".join([c if c.isalnum() else "_" for c in domain])
            safe_filename = f"{timestamp}_{domain}.json"
            
            logging.info(f"Generated filename: {safe_filename}")
            
            # Save results to a file in the /workspace/scrape directory
            scrape_dir = f"{self.workspace_path}/scrape"
            await self.sandbox.fs.create_folder(scrape_dir, "755")
            
            results_file_path = f"{scrape_dir}/{safe_filename}"
            json_content = json.dumps(formatted_result, ensure_ascii=False, indent=2)
            logging.info(f"Saving content to file: {results_file_path}, size: {len(json_content)} bytes")
            
            await self.sandbox.fs.upload_file(
                json_content.encode(),
                results_file_path,
            )
            
            return {
                "url": url,
                "success": True,
                "title": title,
                "file_path": results_file_path,
                "content_length": len(markdown_content)
            }
        
        except Exception as e:
            error_message = str(e)
            logging.error(f"Error scraping URL '{url}': {error_message}")
            
            # Create an error result
            return {
                "url": url,
                "success": False,
                "error": error_message
            }
