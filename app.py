import os
import json
import openai
import base64
import requests
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
import traceback
import io # Added for image editing
import asyncio
from typing import Dict, List, Any, AsyncGenerator, Optional
from dataclasses import dataclass
from enum import Enum

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure API keys
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY") # For direct OpenAI (e.g., gpt-image-1)
tavily_api_key = os.getenv("TAVILY_API_KEY") # For web search

# Initialize OpenAI client (recommended way) for direct OpenAI calls
openai_client = openai.OpenAI(api_key=openai_api_key) if openai_api_key else None

# Allowed models
OPENROUTER_MODELS = {
    "google/gemini-2.5-pro-preview",
    "google/gemini-2.5-flash-preview-05-20:thinking",
    "perplexity/sonar-reasoning-pro",
    "openai/gpt-4.1",
    "openai/gpt-4.5-preview",
    "openai/codex-mini",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-opus-4",
}
ALLOWED_MODELS = OPENROUTER_MODELS.copy()
ALLOWED_MODELS.add("gpt-image-1")
ALLOWED_MODELS.add("agentic-mode")  # Special mode for agentic workflows

# --- Error Handling ---
def check_api_keys(model_name):
    """Checks if the necessary API key for the selected model is loaded."""
    missing = []
    if model_name == "gpt-image-1":
        if not openai_api_key or not openai_client:
            missing.append("OpenAI (for gpt-image-1)")
    elif model_name in OPENROUTER_MODELS:
        if not openrouter_api_key:
            missing.append("OpenRouter")
    
    return missing

# --- Enhanced Web Search Function ---
def search_web_tavily(query, max_results=10):
    """Performs enhanced web search using Tavily API with improved source diversity and quality filtering."""
    if not tavily_api_key:
        return {"error": "Tavily API key not configured"}
    
    try:
        url = "https://api.tavily.com/search"
        
        # Enhanced search strategy based on query type
        query_lower = query.lower()
        search_depth = "advanced"
        topic = "general"
        time_range = None
        days = None
        
        # Adjust search parameters based on query characteristics
        if any(word in query_lower for word in ['news', 'latest', 'recent', 'today', 'current', 'breaking']):
            topic = "news"
            time_range = "week"
            search_depth = "advanced"
        elif any(word in query_lower for word in ['tutorial', 'guide', 'how to', 'learn', 'course']):
            time_range = "year"  # Broader timeframe for educational content
            search_depth = "basic"
        elif any(word in query_lower for word in ['review', 'comparison', 'vs', 'versus', 'best']):
            time_range = "month"  # Medium timeframe for reviews
            search_depth = "advanced"
        
        # Prepare payload according to Tavily API documentation
        payload = {
            "query": query,
            "topic": topic,
            "search_depth": search_depth,
            "chunks_per_source": 3 if search_depth == "advanced" else None,
            "max_results": min(max_results, 20),  # API limit is 20
            "time_range": time_range,
            "include_answer": True,
            "include_raw_content": False,
            "include_images": False,
            "include_image_descriptions": False,
            "include_domains": [],
            "exclude_domains": ["pinterest.com", "instagram.com", "facebook.com", "twitter.com"]
        }
        
        # Add days parameter only for news topic
        if topic == "news":
            payload["days"] = 7
        
        # Remove None values from payload
        payload = {k: v for k, v in payload.items() if v is not None}
        
        # Proper headers according to API documentation
        headers = {
            "Authorization": f"Bearer {tavily_api_key}",
            "Content-Type": "application/json"
        }
        
        print(f"Performing web search with strategy: topic={topic}, depth={search_depth}, time_range={time_range}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Enhanced result processing and quality filtering
        if "results" in data and data["results"]:
            original_count = len(data["results"])
            print(f"Tavily returned {original_count} sources for query: {query}")
            
            # Filter and enhance results
            filtered_results = []
            seen_domains = set()
            
            for result in data["results"]:
                # Extract domain for diversity checking
                try:
                    domain = result.get("url", "").split("/")[2].replace("www.", "").lower()
                except:
                    domain = "unknown"
                
                # Quality filters
                title = result.get("title", "").strip()
                content = result.get("content", "").strip()
                url = result.get("url", "")
                score = result.get("score", 0)  # Tavily provides relevance score
                
                # Skip low-quality results
                if (len(title) < 10 or len(content) < 50 or 
                    not url or "404" in title.lower() or "error" in title.lower()):
                    continue
                
                # Promote domain diversity (max 2 results per domain)
                domain_count = sum(1 for r in filtered_results if r.get("domain") == domain)
                if domain_count >= 2:
                    continue
                
                # Add domain info and enhanced quality score
                result["domain"] = domain
                # Combine Tavily's relevance score with content length and quality indicators
                quality_bonus = 50 if any(word in title.lower() for word in ['official', 'guide', 'tutorial']) else 0
                result["quality_score"] = int((score * 1000) + len(content) + quality_bonus)
                
                filtered_results.append(result)
            
            # Sort by quality score (Tavily score + our enhancements)
            filtered_results.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
            
            # Update data with filtered results
            data["results"] = filtered_results[:max_results]
            
            print(f"Filtered to {len(data['results'])} high-quality sources from {len(set(r['domain'] for r in data['results']))} different domains")
            
            # If we have very few results, try fallback strategies
            if len(data["results"]) < 3:
                print(f"Only got {len(data['results'])} sources, trying fallback strategies...")
                
                # Strategy 1: Broader time window
                if time_range and time_range != "year":
                    broader_payload = payload.copy()
                    broader_payload["time_range"] = "year"
                    broader_payload["search_depth"] = "basic"
                    broader_payload["exclude_domains"] = []  # Remove domain restrictions
                    
                    try:
                        broader_response = requests.post(url, json=broader_payload, headers=headers, timeout=30)
                        broader_response.raise_for_status()
                        broader_data = broader_response.json()
                        
                        if "results" in broader_data and len(broader_data["results"]) > len(data["results"]):
                            print(f"Broader search returned {len(broader_data['results'])} sources")
                            data = broader_data
                    except Exception as e:
                        print(f"Broader search failed: {e}")
                
                # Strategy 2: Remove time restrictions entirely
                if len(data["results"]) < 2:
                    unrestricted_payload = payload.copy()
                    unrestricted_payload.pop("time_range", None)
                    unrestricted_payload.pop("days", None)
                    unrestricted_payload["search_depth"] = "basic"
                    unrestricted_payload["exclude_domains"] = []
                    
                    try:
                        unrestricted_response = requests.post(url, json=unrestricted_payload, headers=headers, timeout=30)
                        unrestricted_response.raise_for_status()
                        unrestricted_data = unrestricted_response.json()
                        
                        if "results" in unrestricted_data and len(unrestricted_data["results"]) > len(data["results"]):
                            print(f"Unrestricted search returned {len(unrestricted_data['results'])} sources")
                            data = unrestricted_data
                    except Exception as e:
                        print(f"Unrestricted search failed: {e}")
        
        # Add search metadata
        data["search_metadata"] = {
            "query": query,
            "topic": topic,
            "search_depth": search_depth,
            "time_range": time_range,
            "total_sources": len(data.get("results", [])),
            "unique_domains": len(set(r.get("domain", "unknown") for r in data.get("results", []))),
            "response_time": data.get("response_time", "N/A")
        }
        
        return data
        
    except requests.exceptions.Timeout:
        print(f"Tavily API timeout for query: {query}")
        return {"error": "Web search timed out. Please try again."}
    except requests.exceptions.RequestException as e:
        print(f"Tavily API request error: {e}")
        # Handle specific HTTP status codes
        if hasattr(e, 'response') and e.response is not None:
            status_code = e.response.status_code
            if status_code == 401:
                return {"error": "Web search authentication failed. Please check API configuration."}
            elif status_code == 429:
                return {"error": "Web search rate limit exceeded. Please try again in a moment."}
            elif status_code == 432:
                return {"error": "Web search quota exceeded. Please try again later."}
            elif status_code == 433:
                return {"error": "Web search request too large. Please try a shorter query."}
            else:
                return {"error": f"Web search failed with status {status_code}. Please try again."}
        return {"error": f"Web search failed: {str(e)}"}
    except Exception as e:
        print(f"Tavily API error: {e}")
        return {"error": f"Web search error: {str(e)}"}

# --- Streaming Generator for OpenRouter ---
def stream_openrouter(query, model_name_with_suffix, reasoning_config=None, uploaded_file_data=None, file_type=None, web_search_enabled=False):
    """Generator for responses from OpenRouter with enhanced web search integration."""
    if not openrouter_api_key:
        yield f"data: {json.dumps({'error': 'OpenRouter API key not configured.'})}\n\n"
        return

    # Enhanced system prompt for better responses with web search
    web_search_note = ""
    if web_search_enabled:
        web_search_note = (
            "\n\n**CRITICAL WEB SEARCH INSTRUCTIONS**: "
            "The user has enabled web search for the most recent and relevant results. You will receive current, real-time web search results from Tavily's advanced search engine with topic-based filtering and relevance scoring. "
            "When using information from these sources:\n"
            "1. **EMBED clickable source links** directly in your response using markdown format: [descriptive text](URL)\n"
            "2. **Make link text natural and descriptive** - integrate seamlessly into sentence flow\n"
            "3. **PRIORITIZE HIGH-QUALITY SOURCES** - sources are ranked by Tavily's relevance score combined with quality indicators\n"
            "4. **Reference multiple sources** when possible to provide comprehensive coverage\n"
            "5. **PRIORITIZE RECENT INFORMATION** - search is optimized for recency based on query type (news, general, etc.)\n"
            "6. **Include diverse perspectives** - sources are filtered for domain diversity and quality\n"
            "7. **ONLY USE PROVIDED SOURCES** - do not reference sources that are not explicitly provided in the search results\n"
            "8. **Clearly distinguish** between information from search results vs. your knowledge\n"
            "9. **Use the Quick Answer** as a starting point but expand with detailed analysis from individual sources\n"
            "10. **Cite sources naturally** - Example: 'According to [recent TechCrunch analysis](https://techcrunch.com/...)' or '[industry experts report](https://example.com)'\n"
            "11. **Leverage search metadata** - consider the search topic, time filter, and domain diversity when crafting your response\n"
            "12. **Quality indicators** - higher quality sources (with better relevance scores) should be given more weight in your analysis"
        )
    
    enhanced_openrouter_system_prompt = (
        "You are Comet, an advanced AI assistant that provides comprehensive, well-structured, and insightful responses. "
        "Your responses should be:\n\n"
        "1. **Clear and Organized**: Use proper headings, bullet points, and numbered lists to structure information logically.\n"
        "2. **Comprehensive yet Concise**: Provide thorough answers without unnecessary verbosity.\n"
        "3. **Actionable**: Include specific steps, examples, or recommendations when applicable.\n"
        "4. **Accurate and Reliable**: Base responses on factual information and clearly indicate any uncertainties.\n"
        "5. **Engaging**: Use a friendly, professional tone that makes complex topics accessible.\n\n"
        "Formatting Guidelines:\n"
        "- Use markdown formatting for better readability\n"
        "- Include code blocks with syntax highlighting when showing code\n"
        "- Use tables for comparing options or presenting structured data\n"
        "- Add relevant emojis sparingly to enhance readability (e.g., ✅ for pros, ❌ for cons, 💡 for tips)\n"
        "- Break down complex topics into digestible sections\n\n"
        "When answering questions:\n"
        "- Start with a brief summary or direct answer\n"
        "- Provide detailed explanation with examples\n"
        "- Include relevant tips, best practices, or warnings\n"
        "- End with a summary or next steps when appropriate\n\n"

        "Always strive to exceed user expectations with thoughtful, well-crafted responses."
        + web_search_note
    )
    
    # Perform web search if enabled
    web_search_results = None
    web_search_sources = []
    if web_search_enabled:
        print(f"Performing web search for query: {query}")
        web_search_results = search_web_tavily(query, max_results=10)  # Increased back to 10 for more sources
        if "error" in web_search_results:
            # Graceful degradation - continue without web search
            print(f"Web search failed: {web_search_results['error']}")
            web_search_enabled = False
            web_search_results = None
        else:
            # Send web search results as a separate event for frontend handling
            if web_search_results and "results" in web_search_results:
                search_data = {
                    "web_search_results": {
                        "answer": web_search_results.get("answer", ""),
                        "results": []
                    }
                }
                
                for i, result in enumerate(web_search_results["results"][:10], 1):  # Process up to 10 sources
                    source_data = {
                        "title": result.get("title", "No title"),
                        "url": result.get("url", ""),
                        "content": result.get("content", "")[:250] + "..." if len(result.get("content", "")) > 250 else result.get("content", "")
                    }
                    search_data["web_search_results"]["results"].append(source_data)
                    web_search_sources.append(f"Source {i}: {source_data['title']} - {source_data['url']}")
                
                # Send web search results to frontend
                print(f"Sending {len(search_data['web_search_results']['results'])} sources to frontend")
                yield f"data: {json.dumps(search_data)}\n\n"
    

    
    # Prepare the enhanced query with optimized web search integration
    enhanced_query = query
    context_additions = []
    
    # Add web search context if available
    if web_search_enabled and web_search_results and "results" in web_search_results:
        search_context = "\n\n**CURRENT WEB SEARCH RESULTS** (Embed source links in your response):\n"
        
        # Add Tavily's answer if available
        if "answer" in web_search_results and web_search_results["answer"]:
            search_context += f"**Quick Answer:** {web_search_results['answer']}\n\n"
        
        # Add numbered search results for easy reference
        search_context += "**Sources:**\n"
        ai_sources_count = len(web_search_results["results"][:10])
        print(f"Sending {ai_sources_count} sources to AI context")
        for i, result in enumerate(web_search_results["results"][:10], 1):  # Process up to 10 sources
            title = result.get("title", "No title")
            url = result.get("url", "")
            content = result.get("content", "")[:200] + "..." if len(result.get("content", "")) > 200 else result.get("content", "")
            domain = result.get("domain", "unknown")
            quality_score = result.get("quality_score", 0)
            quality_level = "HIGH" if quality_score > 200 else "MEDIUM" if quality_score > 100 else "STANDARD"
            
            search_context += f"{i}. **{title}** [{quality_level} QUALITY]\n"
            search_context += f"   Domain: {domain}\n"
            search_context += f"   URL: {url}\n"
            search_context += f"   Content: {content}\n\n"
        
        # Add search metadata for AI context
        metadata = web_search_results.get("search_metadata", {})
        search_context += f"**SEARCH METADATA:**\n"
        search_context += f"- Search Strategy: {metadata.get('search_depth', 'advanced')} search\n"
        search_context += f"- Time Filter: {metadata.get('time_range', 'all time')} time range\n"
        search_context += f"- Source Diversity: {metadata.get('unique_domains', 'N/A')} unique domains\n"
        search_context += f"- Total Quality Sources: {ai_sources_count}\n\n"
        
        # Create a list of valid URLs for the AI to reference
        valid_urls = [result.get("url", "") for result in web_search_results["results"][:10]]
        search_context += f"**CRITICAL CONSTRAINT**: You have access to EXACTLY {len(web_search_results['results'][:10])} sources listed above. DO NOT reference any sources beyond these {len(web_search_results['results'][:10])} sources. ONLY use URLs from this exact list: {valid_urls}. Instead of using [Source X] citations, embed clickable source links directly in your response using markdown format: [descriptive text](URL). Make the link text descriptive and natural within the sentence flow. These are the most recent results available, prioritize this information over older knowledge. DO NOT use any URLs not in the provided list. Pay attention to quality levels - prioritize HIGH and MEDIUM quality sources over STANDARD quality sources when possible.\n"
        context_additions.append(search_context)
    

    
    # Combine all context additions
    if context_additions:
        enhanced_query = f"{query}{''.join(context_additions)}"
    
    user_content_parts = [{"type": "text", "text": enhanced_query}]
    
    # Add context-aware prompting based on query type
    query_lower = query.lower()
    context_hint = ""
    
    if any(word in query_lower for word in ['code', 'program', 'function', 'script', 'debug', 'error']):
        context_hint = "\n\nNote: This appears to be a coding-related question. Please provide code examples with syntax highlighting and clear explanations."
    elif any(word in query_lower for word in ['explain', 'what is', 'how does', 'why', 'define']):
        context_hint = "\n\nNote: This appears to be an explanatory question. Please provide a comprehensive yet accessible explanation with examples."
    elif any(word in query_lower for word in ['compare', 'difference', 'versus', 'vs', 'better']):
        context_hint = "\n\nNote: This appears to be a comparison question. Consider using a table or structured format to clearly show differences."
    elif any(word in query_lower for word in ['list', 'steps', 'how to', 'guide', 'tutorial']):
        context_hint = "\n\nNote: This appears to be a procedural question. Please provide clear, numbered steps or bullet points."
    elif any(word in query_lower for word in ['analyze', 'review', 'evaluate', 'assess']):
        context_hint = "\n\nNote: This appears to be an analytical question. Please provide a thorough analysis with pros, cons, and recommendations."
    elif web_search_enabled:
        context_hint = "\n\nNote: Web search is enabled. Prioritize recent information from search results and cite sources appropriately."
    
    # Append context hint to the query if applicable
    if context_hint:
        user_content_parts[0]["text"] += context_hint

    if uploaded_file_data and file_type:
        if file_type == "image":
            # Validate against supported image types for general multimodal input
            is_valid_image_type = False
            supported_image_prefixes = [
                "data:image/png;base64,",
                "data:image/jpeg;base64,",
                "data:image/jpg;base64,", # Common alternative for jpeg
                "data:image/webp;base64,",
                "data:image/gif;base64,"  # Non-animated GIF
            ]
            for prefix in supported_image_prefixes:
                if uploaded_file_data.startswith(prefix):
                    is_valid_image_type = True
                    break
            
            if not is_valid_image_type:
                yield f"data: {json.dumps({'error': 'Invalid image data format. Expected PNG, JPEG, WEBP, or GIF data URL.'})}\n\n"
                return

            user_content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": uploaded_file_data,
                    "detail": "high"
                }
            })
            print(f"Image data included for OpenRouter. Type: {file_type}, Detail: high, Data starts with: {uploaded_file_data[:50]}...")
        elif file_type == "pdf":
            if not uploaded_file_data.startswith("data:application/pdf"):
                # Basic check
                yield f"data: {json.dumps({'error': 'Invalid PDF data format. Expected data URL.'})}\n\n"
                return
            user_content_parts.append({
                "type": "file",
                "file": {
                    "filename": "uploaded_document.pdf", # Generic filename for now
                    "file_data": uploaded_file_data
                }
            })
            print(f"PDF data included for OpenRouter. Type: {file_type}, Data starts with: {uploaded_file_data[:50]}...")
        else:
            yield f"data: {json.dumps({'error': 'Unsupported file_type for multimodal input.'})}\n\n"
            return
        
    messages = [
        {"role": "system", "content": enhanced_openrouter_system_prompt},
        {"role": "user", "content": user_content_parts}
    ]

    try:
        site_url = os.getenv("APP_SITE_URL", "http://localhost:8080")
        site_title = os.getenv("APP_SITE_TITLE", "Comet AI Search")

        openrouter_client_instance = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_api_key,
            default_headers={ 
                "HTTP-Referer": site_url,
                "X-Title": site_title
            }
        )
    except Exception as e:
        print(f"Failed to initialize OpenRouter client: {e}")
        yield f"data: {json.dumps({'error': 'Failed to initialize OpenRouter client.'})}\n\n"
        return

    actual_model_name_for_sdk = model_name_with_suffix
    max_tokens_val = 30000 # Default value for most models

    # Adjust max_tokens based on model specifics
    if actual_model_name_for_sdk == "perplexity/sonar-reasoning-pro": # 128,000 total context
        max_tokens_val = 128000 - 4096 # Reserve 4096 for prompt (Perplexity specific)
    elif actual_model_name_for_sdk == "openai/gpt-4.1": # 1,047,576 token context window
        max_tokens_val = 1047576 - 4096  # Reserve 4096 tokens for prompt
    elif actual_model_name_for_sdk == "openai/gpt-4o-search-preview": # Stated 16,384 generation capacity
        max_tokens_val = 16384
    elif actual_model_name_for_sdk == "openai/gpt-4.5-preview": # 128,000 token context window
        max_tokens_val = 128000 - 4096  # Reserve 4096 tokens for prompt
    elif actual_model_name_for_sdk == "openai/o4-mini-high": # Was 100,000. Total context 200k. Reducing to leave more room for prompt.
        max_tokens_val = 95000
    elif actual_model_name_for_sdk == "deepseek/deepseek-r1:free":
        max_tokens_val = 163800 # Reduced slightly to accommodate prompt tokens
    elif actual_model_name_for_sdk == "google/gemini-2.5-flash-preview:thinking":
        max_tokens_val = 65535
    elif actual_model_name_for_sdk == "openai/o3-mini-high":
        max_tokens_val = 100000
    elif actual_model_name_for_sdk == "anthropic/claude-opus-4": # 200,000 token context window
        max_tokens_val = 200000 - 4096  # Reserve 4096 tokens for prompt
    elif actual_model_name_for_sdk == "anthropic/claude-sonnet-4": # 200,000 token context window
        max_tokens_val = 200000 - 4096  # Reserve 4096 tokens for prompt
    elif actual_model_name_for_sdk == "google/gemini-2.5-flash-preview-05-20:thinking": # 1,048,576 token context window
        max_tokens_val = 1048576 - 4096  # Reserve 4096 tokens for prompt
    elif actual_model_name_for_sdk == "google/gemini-2.5-pro-preview": # 1,048,576 token context window
        max_tokens_val = 1048576 - 4096  # Reserve 4096 tokens for prompt
    elif actual_model_name_for_sdk == "openai/codex-mini": # 200,000 token context window
        max_tokens_val = 200000 - 4096  # Reserve 4096 tokens for prompt
    # For other models, max_tokens_val remains the default of 30000

    # Always enable reasoning for models that support it (e.g., :thinking or reasoning_config)
    reasoning_config_to_pass = None
    if model_name_with_suffix.endswith(':thinking') or 'thinking' in model_name_with_suffix or 'reasoning' in model_name_with_suffix:
        reasoning_config_to_pass = {"effort": "high", "exclude": False}

    sdk_params = {
        "model": actual_model_name_for_sdk,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens_val,
    }
    
    # Dynamic parameter adjustment based on query type
    if any(word in query_lower for word in ['creative', 'story', 'imagine', 'brainstorm', 'ideas']):
        top_p_value = 0.95
        temperature_value = 0.9  # More creative
    elif any(word in query_lower for word in ['code', 'technical', 'precise', 'exact', 'calculate']):
        top_p_value = 0.9
        temperature_value = 0.3  # More precise
    elif any(word in query_lower for word in ['analyze', 'explain', 'summarize', 'review']):
        top_p_value = 0.92
        temperature_value = 0.5  # Balanced
    else:
        top_p_value = 0.95
        temperature_value = 0.7  # Default balanced creativity

    # Models that don't support top_p parameter
    MODELS_WITHOUT_TOP_P = {
        "openai/codex-mini",
        # Add more models here if they don't support top_p
    }

    # Only include top_p for models that support it
    if actual_model_name_for_sdk not in MODELS_WITHOUT_TOP_P:
        sdk_params["top_p"] = top_p_value

    # Only include temperature for models that support it
    MODELS_WITH_TEMPERATURE = {
        "perplexity/sonar-reasoning-pro",
        "openai/gpt-4.1",
        "openai/gpt-4.5-preview",
        "anthropic/claude-sonnet-4",
        "anthropic/claude-opus-4",
        "openai/o4-mini-high",
        "openai/o3-mini-high",
        # Add more as needed
    }
    if actual_model_name_for_sdk in MODELS_WITH_TEMPERATURE:
        sdk_params["temperature"] = temperature_value

    extra_body_params = {}
    # If reasoning_config is passed (e.g. for :thinking models with exclude: True)
    if reasoning_config_to_pass:
        extra_body_params["reasoning"] = reasoning_config_to_pass

    # Explicitly use pdf-text parser for o4-mini-high with PDFs
    if actual_model_name_for_sdk == "openai/o4-mini-high" and file_type == "pdf":
        print(f"Using explicit pdf-text parser for {actual_model_name_for_sdk} with PDF.")
        if "plugins" not in extra_body_params: # Ensure plugins is initialized
            extra_body_params["plugins"] = []
        
        # Check if file-parser is already added to avoid duplicates if we extend this logic
        parser_exists = False
        for plugin in extra_body_params["plugins"]:
            if plugin.get("id") == "file-parser":
                parser_exists = True
                if "pdf" not in plugin: # Should not happen if id is file-parser
                    plugin["pdf"] = {}
                plugin["pdf"]["engine"] = "pdf-text" # Ensure it's set to pdf-text
                break
        if not parser_exists:
            extra_body_params["plugins"].append({
                "id": "file-parser",
                "pdf": {
                    "engine": "pdf-text" # Free and good for text-based PDFs
                }
            })
    # Also use pdf-text parser for gpt-4.1 with PDFs
    elif actual_model_name_for_sdk == "openai/gpt-4.1" and file_type == "pdf":
        print(f"Using explicit pdf-text parser for {actual_model_name_for_sdk} with PDF.")
        if "plugins" not in extra_body_params:
            extra_body_params["plugins"] = []
        
        parser_exists = False
        for plugin in extra_body_params["plugins"]:
            if plugin.get("id") == "file-parser":
                parser_exists = True
                if "pdf" not in plugin:
                    plugin["pdf"] = {}
                plugin["pdf"]["engine"] = "pdf-text"
                break
        if not parser_exists:
            extra_body_params["plugins"].append({
                "id": "file-parser",
                "pdf": {
                    "engine": "pdf-text"
                }
            })

    try:
        print(f"Calling OpenRouter for {actual_model_name_for_sdk}. Reasoning: {reasoning_config_to_pass}. Extra Body: {extra_body_params}")
        
        # Debug: Log the enhanced query content being sent to AI
        if web_search_enabled and web_search_results:
            print(f"Enhanced query includes web search context with {len(web_search_results.get('results', []))} sources")
            print(f"Enhanced query length: {len(user_content_parts[0]['text'])} characters")
        else:
            print(f"No web search context - query length: {len(user_content_parts[0]['text'])} characters")
        
        stream = openrouter_client_instance.chat.completions.create(**sdk_params, extra_body=extra_body_params)
        buffer = ""
        in_chart_config_block = False
        chart_config_str = ""
        content_received_from_openrouter = False # Flag to track content

        for chunk in stream:
            # Reduced debug output - only log errors and important events
            delta = chunk.choices[0].delta
            
            # Check for reasoning/thinking content
            if hasattr(delta, 'reasoning') and delta.reasoning is not None:
                yield f"data: {json.dumps({'reasoning': delta.reasoning})}\n\n"
            
            # Check for thinking content (alternative field name)
            if hasattr(delta, 'thinking') and delta.thinking is not None:
                yield f"data: {json.dumps({'reasoning': delta.thinking})}\n\n"
            
            # Check if reasoning is in the message metadata
            if hasattr(chunk.choices[0], 'message') and hasattr(chunk.choices[0].message, 'metadata'):
                metadata = chunk.choices[0].message.metadata
                if metadata and 'reasoning' in metadata:
                    yield f"data: {json.dumps({'reasoning': metadata['reasoning']})}\n\n"
            
            if delta.content is not None:
                content_received_from_openrouter = True # Mark that content was received
                buffer += delta.content
                start_marker = "[[CHARTJS_CONFIG_START]]"
                end_marker = "[[CHARTJS_CONFIG_END]]"

                if not in_chart_config_block and start_marker in buffer:
                    pre_block_content = buffer.split(start_marker, 1)[0]
                    if pre_block_content:
                        yield f"data: {json.dumps({'chunk': pre_block_content})}\n\n"
                    buffer = buffer.split(start_marker, 1)[1]
                    in_chart_config_block = True
                
                if in_chart_config_block:
                    if end_marker in buffer:
                        block_content, post_block_content = buffer.split(end_marker, 1)
                        chart_config_str += block_content
                        try:
                            chart_json = json.loads(chart_config_str)
                            yield f"data: {json.dumps({'chart_config': chart_json})}\n\n"
                        except json.JSONDecodeError as e:
                            print(f"Error decoding chart_js config from OpenRouter: {e} - data: {chart_config_str}")
                            data_to_yield = {'chunk': start_marker + chart_config_str + end_marker}
                            yield f"data: {json.dumps(data_to_yield)}\n\n"
                        
                        buffer = post_block_content
                        in_chart_config_block = False
                        chart_config_str = ""
                    else:
                        chart_config_str += buffer
                        buffer = ""
                
                if not in_chart_config_block and buffer:
                    if "\n" in buffer or len(buffer) > 80:
                        yield f"data: {json.dumps({'chunk': buffer})}\n\n"
                        buffer = ""

        if buffer: 
            if in_chart_config_block: # Means block was not properly terminated
                 data_to_yield = {'chunk': start_marker + chart_config_str + buffer} # yield as text
                 yield f"data: {json.dumps(data_to_yield)}\n\n"
            else:
                 yield f"data: {json.dumps({'chunk': buffer})}\n\n"

        if not content_received_from_openrouter:
            print(f"Warning: OpenRouter stream for {actual_model_name_for_sdk} finished without yielding any content chunks.")

        yield f"data: {json.dumps({'end_of_stream': True})}\n\n"
    except openai.APIError as e:
        print(f"OpenRouter API error (streaming for {model_name_with_suffix}): {e.status_code if hasattr(e, 'status_code') else 'N/A'} - {e}")
        error_payload = {
            'message': str(e), # Default message
            'code': e.status_code if hasattr(e, 'status_code') else None
        }
        try:
            # According to OpenRouter docs, error details are in e.body or e.json()
            # The openai-python library often puts the parsed JSON error in e.body directly for APIError
            if hasattr(e, 'body') and isinstance(e.body, dict) and 'error' in e.body:
                # If e.body has the structured error (e.g., {'error': {'code': ..., 'message': ...}})
                error_detail = e.body['error']
                if isinstance(error_detail, dict):
                    error_payload['message'] = error_detail.get('message', error_payload['message'])
                    error_payload['code'] = error_detail.get('code', error_payload['code'])
                    if 'metadata' in error_detail:
                        error_payload['metadata'] = error_detail['metadata']
                elif isinstance(error_detail, str): # Sometimes it might just be a string message
                     error_payload['message'] = error_detail
            elif hasattr(e, 'message') and e.message: # Fallback to e.message if e.body is not as expected
                error_payload['message'] = e.message
            
            # If the error is from a non-200 HTTP response and body might be raw JSON string
            # This case might be less common with the openai client library but good to consider.
            elif hasattr(e, 'response') and hasattr(e.response, 'text'):
                try:
                    response_json = json.loads(e.response.text)
                    if 'error' in response_json and isinstance(response_json['error'], dict):
                        error_detail = response_json['error']
                        error_payload['message'] = error_detail.get('message', error_payload['message'])
                        error_payload['code'] = error_detail.get('code', error_payload['code'])
                        if 'metadata' in error_detail:
                            error_payload['metadata'] = error_detail['metadata']
                except json.JSONDecodeError:
                    print("Could not parse e.response.text as JSON for detailed error.")

        except Exception as parsing_exc:
            print(f"Exception while parsing APIError details: {parsing_exc}")
            # Stick with the basic error_payload if parsing fails

        yield f"data: {json.dumps({'error': error_payload})}\n\n"
    except Exception as e:
        print(f"Error during OpenRouter stream for {model_name_with_suffix}: {e}")
        traceback.print_exc()
        yield f"data: {json.dumps({'error': 'An unexpected error occurred during the OpenRouter stream.'})}\n\n"

# --- Routes --- 
@app.route('/')
def index():
    """Renders the main search page."""
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    """Handles the search query, routing to OpenRouter or direct OpenAI for images."""
    print("--- Request received at /search endpoint ---")
    query = request.json.get('query')
    selected_model = request.json.get('model')
    uploaded_file_data = request.json.get('uploaded_file_data')
    file_type = request.json.get('file_type') # e.g., 'image', 'pdf'
    web_search_enabled = request.json.get('web_search_enabled', False)

    # Default query to "edit image" if not provided but an image is for editing
    if not query and selected_model == "gpt-image-1" and uploaded_file_data and file_type == 'image':
        query = "Perform edits based on the prompt, or a general enhancement if no specific edit prompt."

    if not query: # Now check query after potential default
        return jsonify({'error': 'No query provided'}), 400
    
    default_model_for_error = "google/gemini-2.5-pro-preview"  # Fixed: Use valid model
    if selected_model == "gpt-image-1":
        default_model_for_error = "gpt-image-1"

    if not selected_model or selected_model not in ALLOWED_MODELS:
        print(f"Warning: Invalid or missing model '{selected_model}'. Defaulting to {default_model_for_error}.")
        selected_model = default_model_for_error
    
    missing_keys = check_api_keys(selected_model)
    if missing_keys:
        key_str = " and ".join(missing_keys)
        print(f"Error: Missing API Key(s) {key_str} for model {selected_model}")
        return jsonify({'error': f'Missing API key(s) in .env file for model {selected_model}: {key_str}'}), 500

    print(f"Received query: {query}, Model: {selected_model}")

    if selected_model == "gpt-image-1":
        if uploaded_file_data and file_type == 'image':
            print(f"Routing to OpenAI Image Edit. Query: '{query}'")
            return edit_image(query, uploaded_file_data)
        else:
            print(f"Routing to OpenAI Image Generation. Query: '{query}'")
            return generate_image(query)
    elif selected_model == "agentic-mode":
        print(f"Routing to Enhanced Agentic Mode with SDK-style streaming. Query: '{query}'")
        
        # Create agent with enhanced instructions
        agent = CometAgent(
            name="Comet Research Agent",
            instructions=(
                "You are Comet, an advanced AI agent built with OpenAI's agentic primitives. You intelligently accomplish tasks "
                "by reasoning, planning, and using tools to interact with the world.\n\n"
                
                "🧠 **CORE INTELLIGENCE & REASONING:**\n"
                "- Think step-by-step and plan your approach before taking action\n"
                "- Break down complex tasks into manageable sub-tasks\n"
                "- Reason about which tools are most appropriate for each task\n"
                "- Learn from tool results and adapt your strategy accordingly\n\n"
                
                "🛠️ **AVAILABLE TOOLS & CAPABILITIES:**\n"
                "🕒 **get_current_time**: Get current date and time for temporal context\n"
                "🧮 **calculate_math**: Perform mathematical calculations and analysis\n"
                "🔍 **search_web_tool**: Enhanced web search with intelligent type detection\n"
                "📝 **create_note**: Create and save structured notes or summaries\n"
                "🔬 **research_topic**: Comprehensive multi-step research workflow\n\n"
                
                "📋 **AGENTIC WORKFLOW & ORCHESTRATION:**\n"
                "1. **ANALYZE** the user's request and identify the core objective\n"
                "2. **PLAN** your approach - determine which tools and sequence to use\n"
                "3. **EXECUTE** tools systematically, building on previous results\n"
                "4. **MONITOR** tool outputs and adapt strategy if needed\n"
                "5. **SYNTHESIZE** findings into a comprehensive, actionable response\n\n"
                
                "Remember: You are an intelligent agent capable of autonomous reasoning and tool use. "
                "Think critically, plan strategically, and execute systematically to provide the best possible assistance."
            ),
            model="google/gemini-2.5-pro-preview"
        )
        
        # Use async generator to convert to sync streaming
        async def async_generator():
            async for event in CometRunner.run_streamed(agent, query):
                yield event
        
        def sync_generator():
            """Convert async generator to sync for Flask streaming"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async_gen = async_generator()
                while True:
                    try:
                        event = loop.run_until_complete(async_gen.__anext__())
                        
                        # Convert StreamEvent to Flask streaming format
                        if event.type == StreamEventType.RAW_RESPONSE_EVENT:
                            if "error" in event.data:
                                yield f"data: {json.dumps({'error': event.data['error']})}\n\n"
                            else:
                                yield f"data: {json.dumps({'chunk': str(event.data)})}\n\n"
                        
                        elif event.type == StreamEventType.RUN_ITEM_STREAM_EVENT:
                            if event.data.get("item_type") in ["planning", "progress", "adaptation"]:
                                yield f"data: {json.dumps({'reasoning': event.data['content']})}\n\n"
                        
                        elif event.type == StreamEventType.TOOL_CALL_EVENT:
                            tool_name = event.data["tool_name"]
                            yield f"data: {json.dumps({'reasoning': f'🛠️ Calling {tool_name}...'})}\n\n"
                        
                        elif event.type == StreamEventType.TOOL_OUTPUT_EVENT:
                            tool_name = event.data["tool_name"]
                            yield f"data: {json.dumps({'reasoning': f'✅ {tool_name} completed'})}\n\n"
                        
                        elif event.type == StreamEventType.MESSAGE_OUTPUT_EVENT:
                            # Stream the final message content
                            content = event.data["content"]
                            sentences = content.split('. ')
                            current_chunk = ""
                            
                            for sentence in sentences:
                                current_chunk += sentence + ". "
                                if len(current_chunk) > 80 or sentence.endswith('\n'):
                                    yield f"data: {json.dumps({'chunk': current_chunk})}\n\n"
                                    current_chunk = ""
                            
                            # Send remaining content
                            if current_chunk:
                                yield f"data: {json.dumps({'chunk': current_chunk})}\n\n"
                            
                            yield f"data: {json.dumps({'end_of_stream': True})}\n\n"
                            break
                        
                        elif event.type == StreamEventType.AGENT_UPDATED_STREAM_EVENT:
                            agent_name = event.data["agent_name"]
                            yield f"data: {json.dumps({'reasoning': f'🤖 Agent {agent_name} initialized'})}\n\n"
                    
                    except StopAsyncIteration:
                        break
            finally:
                loop.close()
        
        return Response(sync_generator(), mimetype='text/event-stream')
    elif selected_model in OPENROUTER_MODELS:
        print_query = query[:100] + "..." if query and len(query) > 100 else query
        print_file_data = ""
        if uploaded_file_data:
            print_file_data = f", FileType: {file_type}, FileData (starts with): {uploaded_file_data[:50]}..."
        
        print(f"Routing to OpenRouter. Query: '{print_query}'{print_file_data}, Model: {selected_model}")

        generator = stream_openrouter(
            query, 
            selected_model, 
            reasoning_config=None,
            uploaded_file_data=uploaded_file_data,
            file_type=file_type,
            web_search_enabled=web_search_enabled
        )
        return Response(generator, mimetype='text/event-stream')
    else:
        print(f"Error: Model '{selected_model}' is in ALLOWED_MODELS but not recognized for routing logic.")
        return jsonify({'error': f"Model '{selected_model}' is not configured correctly for use."}), 500

# --- Image Generation Function ---
def generate_image(query):
    """Generates an image using OpenAI and returns base64 data or error."""
    print("--- Entering generate_image function ---")
    if not openai_client: 
         print("ERROR: generate_image - Direct OpenAI client not initialized.")
         return jsonify({'error': 'OpenAI client not initialized. Check direct OpenAI API key.'}), 500

    print(f"Generating image with prompt: {query[:100]}...")
    try:
        result = openai_client.images.generate(
            model="gpt-image-1",
            prompt=query,
            size="1024x1024",
            n=1
        )
        
        if result.data and result.data[0].b64_json:
            image_base64 = result.data[0].b64_json
            print("SUCCESS: generate_image - Image generated, returning JSON (b64_json expected).")
            return jsonify({'image_base64': image_base64})
        else:
            print("ERROR: generate_image - No b64_json data received from OpenAI.")
            return jsonify({'error': 'No b64_json data received from OpenAI API.'}), 500

    except openai.APIError as e:
        print(f"ERROR: generate_image - OpenAI APIError caught: {e}")
        err_msg = "An API error occurred."
        status_code = 500
        if hasattr(e, 'status_code') and e.status_code:
            status_code = e.status_code

        # Try to get a more specific message
        try:
            if hasattr(e, 'body') and isinstance(e.body, dict) and 'error' in e.body:
                error_detail = e.body['error']
                if isinstance(error_detail, dict) and 'message' in error_detail and error_detail['message']:
                    err_msg = error_detail['message']
                elif isinstance(error_detail, str):
                    err_msg = error_detail
            elif hasattr(e, 'message') and e.message:
                err_msg = e.message
        except Exception as parsing_exc:
            print(f"Exception while parsing APIError details for generate_image: {parsing_exc}")
        
        # Ensure err_msg is a string before checking substrings
        if not isinstance(err_msg, str):
            err_msg = str(err_msg) # Convert to string if it's None or other type

        if "model_not_found" in err_msg or "does not support" in err_msg or "incorrect API key" in err_msg or "authentication" in err_msg:
            err_msg = f"The image generation model ('gpt-image-1' or its backend like 'dall-e-2') might be unavailable, not supported by your key, or an authentication issue occurred: {err_msg}"
        elif "Invalid image" in err_msg or "must be a PNG" in err_msg or "square" in err_msg or "size" in err_msg:
            err_msg = f"Image validation failed. Ensure it's a square PNG under 4MB: {err_msg}"
        
        return jsonify({'error': f'OpenAI API error during image generation: {err_msg}'}), status_code
    except Exception as e:
        print(f"ERROR: generate_image - Unexpected Exception caught: {e}")
        traceback.print_exc()
        # Ensure a JSON response even for unexpected errors
        return jsonify({'error': 'An internal server error occurred during image generation. Please check server logs.'}), 500

# --- Image Editing Function ---
def edit_image(prompt, image_data_url):
    """Edits an image using OpenAI and returns base64 data or error."""
    print(f"--- Entering edit_image function. Prompt: {prompt[:100]}... ---")
    if not openai_client:
        print("ERROR: edit_image - Direct OpenAI client not initialized.")
        return jsonify({'error': 'OpenAI client not initialized. Check direct OpenAI API key.'}), 500

    try:
        # Decode the base64 image data URL
        # Format: "data:image/png;base64,iVBORw0KGgo..."
        # For images.edit, OpenAI API requires a valid PNG file.
        if not image_data_url.startswith("data:image/png;base64,"):
            print("ERROR: edit_image - Invalid image data URL format. Must be a PNG base64 data URL for editing.")
            return jsonify({'error': 'Invalid image format for editing. Please upload a PNG image.'}), 400
        
        header, encoded_data = image_data_url.split(',', 1)
        image_bytes = base64.b64decode(encoded_data)
        
        # Use io.BytesIO to treat the bytes as a file
        image_file_like = io.BytesIO(image_bytes)
        image_file_like.name = "uploaded_image.png" # API might need a filename

        print(f"Editing image with gpt-image-1. Prompt: {prompt[:100]}..., Image size: {len(image_bytes)} bytes")
        
        result = openai_client.images.edit(
            image=image_file_like,
            # mask= can be added here if we implement mask uploads
            prompt=prompt,
            model="gpt-image-1", # Explicitly use gpt-image-1
            n=1,
            size="1024x1024" # Ensure this size is supported by gpt-image-1 for edits or if it needs to match original
        )

        if result.data and result.data[0].b64_json:
            edited_image_base64 = result.data[0].b64_json
            print("SUCCESS: edit_image - Image edited, returning JSON (b64_json expected).")
            # The response is b64_json, so it's already base64 encoded.
            return jsonify({'image_base64': edited_image_base64, 'is_edit': True}) 
        elif result.data and result.data[0].url:
            # Sometimes the API might return a URL instead, though b64_json is preferred for this flow
            print(f"WARNING: edit_image - Image edited, but received URL: {result.data[0].url}. This app expects b64_json for direct display.")
            # For simplicity, we'll ask the user to try again or indicate we can't load from URL directly in this flow.
            # Ideally, we'd fetch the URL and convert to base64, but that adds complexity and another request.
            return jsonify({'error': 'Image edited, but received a URL. Please try again or contact support if this persists. This version expects base64 data.'}), 500
        else:
            print("ERROR: edit_image - No b64_json or URL data received from OpenAI edit API.")
            return jsonify({'error': 'No image data received from OpenAI API after edit.'}), 500

    except openai.APIError as e:
        print(f"ERROR: edit_image - OpenAI APIError caught: {e}")
        err_msg = "An API error occurred."
        status_code = 500
        if hasattr(e, 'status_code') and e.status_code:
            status_code = e.status_code

        # Try to get a more specific message
        try:
            if hasattr(e, 'body') and isinstance(e.body, dict) and 'error' in e.body:
                error_detail = e.body['error']
                if isinstance(error_detail, dict) and 'message' in error_detail and error_detail['message']:
                    err_msg = error_detail['message']
                elif isinstance(error_detail, str):
                    err_msg = error_detail
            elif hasattr(e, 'message') and e.message:
                err_msg = e.message
        except Exception as parsing_exc:
            print(f"Exception while parsing APIError details for edit_image: {parsing_exc}")
        
        # Ensure err_msg is a string before checking substrings
        if not isinstance(err_msg, str):
            err_msg = str(err_msg) # Convert to string if it's None or other type

        if "model_not_found" in err_msg or "does not support" in err_msg or "incorrect API key" in err_msg or "authentication" in err_msg:
            err_msg = f"The image editing model ('dall-e-2') might be unavailable, not supported by your key, or an authentication issue occurred: {err_msg}"
        elif "Invalid image" in err_msg or "must be a PNG" in err_msg or "square" in err_msg or "size" in err_msg:
            err_msg = f"Image validation failed. Ensure it's a square PNG under 4MB: {err_msg}"
        
        return jsonify({'error': f'OpenAI API error during image edit: {err_msg}'}), status_code
    except Exception as e:
        print(f"ERROR: edit_image - Unexpected Exception caught: {e}")
        traceback.print_exc()
        # Ensure a JSON response even for unexpected errors
        return jsonify({'error': 'An internal server error occurred during image editing. Please check server logs.'}), 500

# --- Agentic Tools Definition ---
def get_current_time():
    """Get the current date and time."""
    from datetime import datetime
    return {"current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

def calculate_math(expression):
    """Safely evaluate a mathematical expression."""
    import re
    # Only allow safe mathematical operations
    if re.match(r'^[0-9+\-*/().\s]+$', expression):
        try:
            result = eval(expression)
            return {"result": result, "expression": expression}
        except Exception as e:
            return {"error": f"Math calculation failed: {str(e)}"}
    else:
        return {"error": "Invalid mathematical expression. Only numbers and basic operators allowed."}

def search_web_tool(query, max_results=8, search_type="auto"):
    """
    Enhanced web search using Tavily API - tool wrapper with intelligent search strategies.
    
    Args:
        query: Search query
        max_results: Maximum number of results to return (default 8 for agentic mode)
        search_type: Type of search - "auto", "news", "general", "deep"
    """
    # Intelligent search type detection if auto
    if search_type == "auto":
        query_lower = query.lower()
        if any(word in query_lower for word in ['news', 'latest', 'recent', 'today', 'current', 'breaking', 'update']):
            search_type = "news"
        elif any(word in query_lower for word in ['tutorial', 'guide', 'how to', 'learn', 'course', 'documentation']):
            search_type = "general"
        elif any(word in query_lower for word in ['research', 'analysis', 'detailed', 'comprehensive', 'study']):
            search_type = "deep"
        else:
            search_type = "general"
    
    print(f"Agentic web search: '{query}' (type: {search_type})")
    
    # Adjust search parameters based on type
    if search_type == "news":
        result = search_web_tavily(query, max_results=max_results)
    elif search_type == "deep":
        result = search_web_tavily(query, max_results=min(max_results * 2, 15))  # Get more results for deep search
    else:
        result = search_web_tavily(query, max_results=max_results)
    
    if "error" in result:
        return {"error": result["error"], "search_type": search_type}
    
    # Enhanced result processing for agentic mode
    simplified_results = []
    total_content_length = 0
    
    # Process more results for agentic mode but with better filtering
    results_to_process = result.get("results", [])[:max_results]
    
    for i, item in enumerate(results_to_process):
        title = item.get("title", "").strip()
        url = item.get("url", "")
        content = item.get("content", "").strip()
        domain = item.get("domain", "unknown")
        quality_score = item.get("quality_score", 0)
        
        # For agentic mode, provide more content but still manageable
        if search_type == "deep":
            content_preview = content[:400] + "..." if len(content) > 400 else content
        else:
            content_preview = content[:250] + "..." if len(content) > 250 else content
        
        # Quality indicator for the AI
        quality_level = "HIGH" if quality_score > 200 else "MEDIUM" if quality_score > 100 else "STANDARD"
        
        simplified_results.append({
            "rank": i + 1,
            "title": title,
            "url": url,
            "content": content_preview,
            "domain": domain,
            "quality": quality_level,
            "relevance_score": quality_score
        })
        
        total_content_length += len(content_preview)
    
    # Enhanced metadata for agentic decision making
    search_metadata = result.get("search_metadata", {})
    
    return {
        "success": True,
        "query": query,
        "search_type": search_type,
        "quick_answer": result.get("answer", ""),
        "sources": simplified_results,
        "total_found": len(result.get("results", [])),
        "returned_count": len(simplified_results),
        "content_length": total_content_length,
        "search_strategy": {
            "topic": search_metadata.get("topic", "general"),
            "depth": search_metadata.get("search_depth", "advanced"),
            "time_range": search_metadata.get("time_range", "all time"),
            "unique_domains": search_metadata.get("unique_domains", 0)
        },
        "quality_distribution": {
            "high": len([s for s in simplified_results if s["quality"] == "HIGH"]),
            "medium": len([s for s in simplified_results if s["quality"] == "MEDIUM"]),
            "standard": len([s for s in simplified_results if s["quality"] == "STANDARD"])
        }
    }

def create_note(content, filename=None):
    """Create a simple text note file."""
    import os
    import tempfile
    from datetime import datetime
    
    # Create a safe filename
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"note_{timestamp}.txt"
    
    # Sanitize filename
    filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    if not filename.endswith('.txt'):
        filename += '.txt'
    
    try:
        # Create in a temporary directory for safety
        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return {
            "success": True,
            "filename": filename,
            "filepath": filepath,
            "message": f"Note created successfully as {filename}"
        }
    except Exception as e:
        return {"error": f"Failed to create note: {str(e)}"}

def research_topic(topic, research_depth="comprehensive"):
    """
    Perform comprehensive research on a topic using multiple search strategies.
    
    Args:
        topic: The topic to research
        research_depth: "quick", "standard", or "comprehensive"
    """
    print(f"Starting comprehensive research on: {topic} (depth: {research_depth})")
    
    research_results = {
        "topic": topic,
        "research_depth": research_depth,
        "searches_performed": [],
        "all_sources": [],
        "key_findings": [],
        "summary": ""
    }
    
    try:
        # Step 1: General overview search
        overview_query = f"{topic} overview explanation"
        overview_result = search_web_tool(overview_query, max_results=5, search_type="general")
        
        if overview_result.get("success"):
            research_results["searches_performed"].append({
                "type": "overview",
                "query": overview_query,
                "results_count": overview_result.get("returned_count", 0)
            })
            research_results["all_sources"].extend(overview_result.get("sources", []))
            if overview_result.get("quick_answer"):
                research_results["key_findings"].append(f"Overview: {overview_result['quick_answer']}")
        
        # Step 2: Recent news/updates if comprehensive
        if research_depth in ["standard", "comprehensive"]:
            news_query = f"{topic} latest news updates 2024"
            news_result = search_web_tool(news_query, max_results=4, search_type="news")
            
            if news_result.get("success"):
                research_results["searches_performed"].append({
                    "type": "news",
                    "query": news_query,
                    "results_count": news_result.get("returned_count", 0)
                })
                research_results["all_sources"].extend(news_result.get("sources", []))
                if news_result.get("quick_answer"):
                    research_results["key_findings"].append(f"Recent Updates: {news_result['quick_answer']}")
        
        # Step 3: Deep analysis if comprehensive
        if research_depth == "comprehensive":
            analysis_query = f"{topic} detailed analysis research study"
            analysis_result = search_web_tool(analysis_query, max_results=6, search_type="deep")
            
            if analysis_result.get("success"):
                research_results["searches_performed"].append({
                    "type": "analysis",
                    "query": analysis_query,
                    "results_count": analysis_result.get("returned_count", 0)
                })
                research_results["all_sources"].extend(analysis_result.get("sources", []))
                if analysis_result.get("quick_answer"):
                    research_results["key_findings"].append(f"Detailed Analysis: {analysis_result['quick_answer']}")
        
        # Generate summary
        total_sources = len(research_results["all_sources"])
        high_quality_sources = len([s for s in research_results["all_sources"] if s.get("quality") == "HIGH"])
        
        research_results["summary"] = f"Completed {research_depth} research on '{topic}' using {len(research_results['searches_performed'])} search strategies. Found {total_sources} total sources ({high_quality_sources} high-quality). Key areas covered: {', '.join([s['type'] for s in research_results['searches_performed']])}"
        
        return research_results
        
    except Exception as e:
        return {
            "error": f"Research failed: {str(e)}",
            "topic": topic,
            "partial_results": research_results
        }

# Tool definitions for OpenRouter function calling
AGENTIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "calculate_math",
            "description": "Perform mathematical calculations safely. Supports basic arithmetic operations (+, -, *, /, parentheses)",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate (e.g., '2 + 3 * 4', '(10 + 5) / 3')"
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web_tool", 
            "description": "Search the web for current information using Tavily API. Automatically detects search type (news, general, deep) based on query. Returns comprehensive results with quality indicators.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find information on the web"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 8, max: 15)",
                        "minimum": 1,
                        "maximum": 15
                    },
                    "search_type": {
                        "type": "string",
                        "description": "Type of search: 'auto' (default - automatically detects), 'news' (recent news), 'general' (broad search), 'deep' (comprehensive research)",
                        "enum": ["auto", "news", "general", "deep"]
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "Create a simple text note file. Useful for saving information, creating summaries, or organizing thoughts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The content to write to the note file"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional filename for the note (will be sanitized). If not provided, a timestamp-based name will be used."
                    }
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "research_topic",
            "description": "Perform comprehensive multi-step research on a topic using various search strategies (overview, news, analysis). Best for complex topics requiring thorough investigation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic to research comprehensively"
                    },
                    "research_depth": {
                        "type": "string",
                        "description": "Depth of research: 'quick' (overview only), 'standard' (overview + news), 'comprehensive' (overview + news + analysis)",
                        "enum": ["quick", "standard", "comprehensive"]
                    }
                },
                "required": ["topic"]
            }
        }
    }
]

# Tool mapping for execution
TOOL_MAPPING = {
    "get_current_time": get_current_time,
    "calculate_math": calculate_math,
    "search_web_tool": search_web_tool,
    "create_note": create_note,
    "research_topic": research_topic
}

def log_agent_performance(task_plan, total_tools_used, iteration_count, success=True):
    """
    Log agent performance metrics for monitoring and evaluation.
    In a production system, this would integrate with OpenAI's tracing and evaluation tools.
    """
    try:
        from datetime import datetime
        import json
        
        performance_data = {
            "timestamp": datetime.now().isoformat(),
            "objective": task_plan.get("objective", "")[:200],  # Truncate for logging
            "success": success,
            "iterations_used": iteration_count,
            "max_iterations": 5,  # Current limit
            "efficiency": iteration_count / 5,  # Simple efficiency metric
            "tools_used": list(set(total_tools_used)),
            "tool_usage_count": len(total_tools_used),
            "unique_tools_count": len(set(total_tools_used)),
            "steps_completed": len(task_plan.get("steps_completed", [])),
            "final_step": task_plan.get("current_step", "unknown"),
            "research_operations": len([s for s in task_plan.get("steps_completed", []) 
                                      if 'search' in s.get('tool', '') or 'research' in s.get('tool', '')]),
        }
        
        # In production, this would send to OpenAI's tracing system
        print(f"Agent Performance Log: {json.dumps(performance_data, indent=2)}")
        
        return performance_data
        
    except Exception as e:
        print(f"Error logging agent performance: {e}")
        return None

# --- Agentic Loop Function ---
def run_agentic_loop(query, model_name, max_iterations=5):
    """
    Run a simple agentic loop following OpenRouter's best practices.
    Returns a generator for streaming responses.
    """
    if not openrouter_api_key:
        yield f"data: {json.dumps({'error': 'OpenRouter API key not configured for agentic mode.'})}\n\n"
        return

    # Enhanced system prompt for agentic behavior following OpenAI best practices
    agentic_system_prompt = (
        "You are Comet, an advanced AI agent built with OpenAI's agentic primitives. You intelligently accomplish tasks "
        "by reasoning, planning, and using tools to interact with the world.\n\n"
        
        "🧠 **CORE INTELLIGENCE & REASONING:**\n"
        "- Think step-by-step and plan your approach before taking action\n"
        "- Break down complex tasks into manageable sub-tasks\n"
        "- Reason about which tools are most appropriate for each task\n"
        "- Learn from tool results and adapt your strategy accordingly\n\n"
        
        "🛠️ **AVAILABLE TOOLS & CAPABILITIES:**\n"
        "🕒 **get_current_time**: Get current date and time for temporal context\n"
        "🧮 **calculate_math**: Perform mathematical calculations and analysis\n"
        "🔍 **search_web_tool**: Enhanced web search with intelligent type detection\n"
        "   - Auto-detects search type (news, general, deep research)\n"
        "   - Returns quality-ranked results with metadata\n"
        "   - Configurable depth and result count\n"
        "📝 **create_note**: Create and save structured notes or summaries\n"
        "🔬 **research_topic**: Comprehensive multi-step research workflow\n"
        "   - Combines overview, news, and analysis searches\n"
        "   - Aggregates findings from multiple sources\n"
        "   - Provides quality distribution and research summary\n\n"
        
        "📋 **AGENTIC WORKFLOW & ORCHESTRATION:**\n"
        "1. **ANALYZE** the user's request and identify the core objective\n"
        "2. **PLAN** your approach - determine which tools and sequence to use\n"
        "3. **EXECUTE** tools systematically, building on previous results\n"
        "4. **MONITOR** tool outputs and adapt strategy if needed\n"
        "5. **SYNTHESIZE** findings into a comprehensive, actionable response\n\n"
        
        "🎯 **TOOL SELECTION STRATEGY:**\n"
        "- **Simple factual queries**: Use search_web_tool with auto-detection\n"
        "- **Current events/breaking news**: Use search_web_tool with type='news'\n"
        "- **Complex research topics**: Use research_topic for multi-angle analysis\n"
        "- **Technical tutorials/guides**: Use search_web_tool with type='general'\n"
        "- **Academic/detailed analysis**: Use search_web_tool with type='deep'\n"
        "- **Calculations/quantitative analysis**: Use calculate_math\n"
        "- **Information organization**: Use create_note to structure findings\n\n"
        
        "🔍 **QUALITY & GUARDRAILS:**\n"
        "- Prioritize HIGH quality sources in your analysis\n"
        "- Cross-reference information from multiple sources when possible\n"
        "- Clearly distinguish between verified facts and speculation\n"
        "- Acknowledge limitations and uncertainties in your knowledge\n"
        "- Provide source citations and quality indicators\n\n"
        
        "💬 **RESPONSE GUIDELINES:**\n"
        "- Be conversational yet professional\n"
        "- Provide comprehensive answers with clear structure\n"
        "- Include actionable insights and recommendations\n"
        "- Explain your reasoning process when helpful\n"
        "- Adapt your communication style to the user's needs\n\n"
        
        "Remember: You are an intelligent agent capable of autonomous reasoning and tool use. "
        "Think critically, plan strategically, and execute systematically to provide the best possible assistance."
    )

    messages = [
        {"role": "system", "content": agentic_system_prompt},
        {"role": "user", "content": query}
    ]

    try:
        openrouter_client_instance = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_api_key,
            default_headers={
                "HTTP-Referer": os.getenv("APP_SITE_URL", "http://localhost:8080"),
                "X-Title": os.getenv("APP_SITE_TITLE", "Comet AI Search")
            }
        )

        def call_llm(msgs):
            """Call LLM with tools - following OpenRouter documentation pattern"""
            resp = openrouter_client_instance.chat.completions.create(
                model=model_name,
                tools=AGENTIC_TOOLS,
                messages=msgs
            )
            msgs.append(resp.choices[0].message.dict())
            return resp

        def get_tool_response(response):
            """Process tool calls - following OpenRouter documentation pattern"""
            tool_call = response.choices[0].message.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            print(f"Executing tool: {tool_name} with args: {tool_args}")
            
            # Look up the correct tool locally, and call it with the provided arguments
            # Other tools can be added without changing the agentic loop
            if tool_name in TOOL_MAPPING:
                try:
                    tool_result = TOOL_MAPPING[tool_name](**tool_args)
                    print(f"Tool result: {tool_result}")
                except Exception as e:
                    tool_result = {"error": f"Tool execution failed: {str(e)}"}
            else:
                tool_result = {"error": f"Unknown tool: {tool_name}"}
            
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(tool_result),
            }

        # Enhanced agentic loop with planning and monitoring
        iteration = 0
        total_tools_used = []
        task_plan = {"objective": query, "steps_completed": [], "current_step": "analysis"}
        
        # Initial planning phase
        yield f"data: {json.dumps({'reasoning': '🧠 Analyzing request and planning approach...'})}\n\n"
        
        while iteration < max_iterations:
            iteration += 1
            print(f"Agentic loop iteration {iteration} - Current step: {task_plan['current_step']}")
            
            resp = call_llm(messages)
            
            if resp.choices[0].message.tool_calls is not None:
                # Process all tool calls in this response
                tool_calls_used = []
                for tool_call in resp.choices[0].message.tool_calls:
                    tool_response = get_tool_response_single(resp, tool_call)
                    messages.append(tool_response)
                    tool_name = tool_call.function.name
                    tool_calls_used.append(tool_name)
                    total_tools_used.append(tool_name)
                    
                    # Update task plan
                    task_plan["steps_completed"].append({
                        "iteration": iteration,
                        "tool": tool_name,
                        "args": json.loads(tool_call.function.arguments)
                    })
                
                # Provide enhanced progress updates with orchestration context
                if "search_web_tool" in tool_calls_used:
                    task_plan["current_step"] = "information_gathering"
                    yield f"data: {json.dumps({'reasoning': f'🔍 Gathering information from the web... (Step {iteration})'})}\n\n"
                elif "research_topic" in tool_calls_used:
                    task_plan["current_step"] = "comprehensive_research"
                    yield f"data: {json.dumps({'reasoning': f'🔬 Conducting multi-step research analysis... (Step {iteration})'})}\n\n"
                elif "calculate_math" in tool_calls_used:
                    task_plan["current_step"] = "quantitative_analysis"
                    yield f"data: {json.dumps({'reasoning': f'🧮 Performing calculations and analysis... (Step {iteration})'})}\n\n"
                elif "create_note" in tool_calls_used:
                    task_plan["current_step"] = "knowledge_organization"
                    yield f"data: {json.dumps({'reasoning': f'📝 Organizing and structuring findings... (Step {iteration})'})}\n\n"
                else:
                    task_plan["current_step"] = "tool_execution"
                    yield f"data: {json.dumps({'reasoning': f'🛠️ Executing tools: {", ".join(tool_calls_used)} (Step {iteration})'})}\n\n"
                
                # Monitoring: Check if we're making progress
                if iteration > 2 and len(set(total_tools_used[-3:])) == 1:
                    # If using the same tool repeatedly, add guidance
                    yield f"data: {json.dumps({'reasoning': '🔄 Adapting strategy based on previous results...'})}\n\n"
                    
            else:
                # No more tool calls, provide final synthesis
                task_plan["current_step"] = "synthesis"
                print(f"Agentic workflow completed after {iteration} iterations")
                print(f"Task plan: {task_plan}")
                print(f"Tools used: {total_tools_used}")
                
                # Log performance for monitoring and evaluation
                log_agent_performance(task_plan, total_tools_used, iteration, success=True)
                
                final_content = resp.choices[0].message.content
                
                # Stream the final response with orchestration summary
                if final_content:
                    # Add enhanced summary with workflow insights
                    if total_tools_used:
                        unique_tools = list(set(total_tools_used))
                        workflow_summary = (
                            f"\n\n---\n"
                            f"**🤖 Agent Workflow Summary:**\n"
                            f"- **Objective**: {task_plan['objective'][:100]}{'...' if len(task_plan['objective']) > 100 else ''}\n"
                            f"- **Steps Completed**: {len(task_plan['steps_completed'])}\n"
                            f"- **Tools Utilized**: {', '.join(unique_tools)}\n"
                            f"- **Research Quality**: {len([s for s in task_plan['steps_completed'] if 'search' in s['tool'] or 'research' in s['tool']])} information gathering operations\n"
                            f"- **Status**: ✅ Task completed successfully"
                        )
                        final_content += workflow_summary
                    
                    # Stream with better chunking for readability
                    sentences = final_content.split('. ')
                    current_chunk = ""
                    
                    for sentence in sentences:
                        current_chunk += sentence + ". "
                        if len(current_chunk) > 80 or sentence.endswith('\n'):
                            yield f"data: {json.dumps({'chunk': current_chunk})}\n\n"
                            current_chunk = ""
                    
                    # Send remaining content
                    if current_chunk:
                        yield f"data: {json.dumps({'chunk': current_chunk})}\n\n"
                
                yield f"data: {json.dumps({'end_of_stream': True})}\n\n"
                return

        # If we hit max iterations, provide intelligent fallback
        # Log performance for incomplete workflow
        log_agent_performance(task_plan, total_tools_used, max_iterations, success=False)
        
        fallback_message = (
            f"I've reached the maximum number of iterations ({max_iterations}) while working on your request. "
            f"However, I was able to complete {len(task_plan['steps_completed'])} steps using these tools: {', '.join(set(total_tools_used))}. "
            f"Current progress: {task_plan['current_step']}. "
            f"The information gathered so far should still be valuable for addressing your query."
        )
        yield f"data: {json.dumps({'chunk': fallback_message})}\n\n"
        yield f"data: {json.dumps({'end_of_stream': True})}\n\n"

    except Exception as e:
        print(f"Error in agentic loop: {e}")
        yield f"data: {json.dumps({'error': f'Agentic loop error: {str(e)}'})}\n\n"

def get_tool_response_single(response, tool_call):
    """Process a single tool call - helper function"""
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments)
    
    print(f"Executing tool: {tool_name} with args: {tool_args}")
    
    # Look up the correct tool locally, and call it with the provided arguments
    if tool_name in TOOL_MAPPING:
        try:
            tool_result = TOOL_MAPPING[tool_name](**tool_args)
            print(f"Tool result: {tool_result}")
        except Exception as e:
            tool_result = {"error": f"Tool execution failed: {str(e)}"}
    else:
        tool_result = {"error": f"Unknown tool: {tool_name}"}
    
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_name,
        "content": json.dumps(tool_result),
    }

# --- Main Execution --- 
if __name__ == '__main__':
    if not openrouter_api_key:
         print("\n*** WARNING: OpenRouter API key not found in .env. OpenRouter models will not work. ***\n")
    else:
        print("OpenRouter API key found.")

    if not openai_api_key:
         print("*** WARNING: Direct OpenAI API key (OPENAI_API_KEY) not found in .env. gpt-image-1 model will not work. ***")
    else:
        print("Direct OpenAI API key (OPENAI_API_KEY) found.")
    


    if openrouter_api_key or openai_api_key:
        print("Application starting...\n")
    else:
        print("\n*** CRITICAL WARNING: NO API keys (OpenRouter or direct OpenAI) found in .env. Application will likely not function. ***\n")
        
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), threaded=True) 

@app.route('/debug')
def debug_info():
    """Debug endpoint to check function availability and environment."""
    import sys
    import os
    
    debug_data = {
        "python_version": sys.version,
        "python_path": sys.path[:3],  # First 3 entries
        "current_working_directory": os.getcwd(),
        "environment_variables": {
            "OPENROUTER_API_KEY": "✅ Set" if openrouter_api_key else "❌ Missing",
            "OPENAI_API_KEY": "✅ Set" if openai_api_key else "❌ Missing", 
            "TAVILY_API_KEY": "✅ Set" if tavily_api_key else "❌ Missing"
        },
        "function_availability": {
            "get_current_time": "✅ Available" if 'get_current_time' in globals() else "❌ Missing",
            "calculate_math": "✅ Available" if 'calculate_math' in globals() else "❌ Missing",
            "search_web_tool": "✅ Available" if 'search_web_tool' in globals() else "❌ Missing",
            "create_note": "✅ Available" if 'create_note' in globals() else "❌ Missing",
            "research_topic": "✅ Available" if 'research_topic' in globals() else "❌ Missing"
        },
        "tool_mapping_status": {
            "TOOL_MAPPING_exists": "✅ Available" if 'TOOL_MAPPING' in globals() else "❌ Missing",
            "TOOL_MAPPING_keys": list(TOOL_MAPPING.keys()) if 'TOOL_MAPPING' in globals() else []
        },
        "agentic_tools_status": {
            "AGENTIC_TOOLS_exists": "✅ Available" if 'AGENTIC_TOOLS' in globals() else "❌ Missing",
            "AGENTIC_TOOLS_count": len(AGENTIC_TOOLS) if 'AGENTIC_TOOLS' in globals() else 0
        }
    }
    
    return jsonify(debug_data)

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Test that all critical functions are available
        test_results = {
            "status": "healthy",
            "timestamp": get_current_time()["current_time"],
            "api_keys_configured": bool(openrouter_api_key and openai_api_key and tavily_api_key),
            "tools_available": len(TOOL_MAPPING),
            "agentic_tools_configured": len(AGENTIC_TOOLS)
        }
        return jsonify(test_results)
    except Exception as e:
        return jsonify({
            "status": "unhealthy", 
            "error": str(e),
            "timestamp": "unknown"
        }), 500

