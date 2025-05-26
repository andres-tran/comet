import os
import json
import openai
import base64
import requests
import logging
import time
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
import traceback
import io # Added for image editing

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Security headers middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    if os.getenv('VERCEL_ENV') == 'production':
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Add CSP for production
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com /_vercel/; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://api.openrouter.ai https://api.openai.com https://api.tavily.com; "
            "worker-src 'self';"
        )
    return response

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    return render_template('index.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error occurred'}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle all other exceptions"""
    logger.error(f"Unhandled exception: {e}")
    if os.getenv('VERCEL_ENV') != 'production':
        # In development, show the actual error
        return jsonify({'error': str(e)}), 500
    else:
        # In production, show a generic error
        return jsonify({'error': 'An unexpected error occurred'}), 500

# Configure logging for production
if os.getenv('VERCEL_ENV') == 'production':
    logging.basicConfig(level=logging.WARNING)
else:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

# Configure API keys with validation
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY") # For direct OpenAI (e.g., gpt-image-1)
tavily_api_key = os.getenv("TAVILY_API_KEY") # For web search

# Validate critical environment variables
if not any([openrouter_api_key, openai_api_key]):
    logger.error("No API keys found. At least one of OPENROUTER_API_KEY or OPENAI_API_KEY must be set.")

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

# --- Web Search Function ---
def search_web_tavily(query, max_results=10):
    """Performs web search using Tavily API and returns search results."""
    if not tavily_api_key:
        return {"error": "Tavily API key not configured"}
    
    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": tavily_api_key,
            "query": query,
            "search_depth": "advanced",
            "include_answer": True,
            "include_images": False,
            "include_raw_content": False,
            "max_results": max_results,
            "include_domains": [],
            "exclude_domains": [],  # Include all sources including Reddit, Quora, etc.
            "days": 30  # Increased to 30 days to get more sources when recent content is limited
        }
        
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Log the actual number of results returned
        if "results" in data:
            logger.info(f"Tavily returned {len(data['results'])} sources for query: {query}")
            # Also log the domains for debugging in development
            if not os.getenv('VERCEL_ENV') == 'production':
                domains = [result.get("url", "").split("/")[2] if result.get("url") else "unknown" for result in data["results"]]
                logger.debug(f"Source domains: {domains}")
            
            # If we got very few results, try a broader search with longer time window
            if len(data["results"]) < 3 and payload["days"] < 90:
                logger.info(f"Only got {len(data['results'])} sources, trying broader search with 90 days...")
                broader_payload = payload.copy()
                broader_payload["days"] = 90  # Expand to 90 days
                broader_payload["search_depth"] = "basic"  # Use basic search for broader results
                
                try:
                    broader_response = requests.post(url, json=broader_payload, timeout=30)
                    broader_response.raise_for_status()
                    broader_data = broader_response.json()
                    
                    if "results" in broader_data and len(broader_data["results"]) > len(data["results"]):
                        logger.info(f"Broader search returned {len(broader_data['results'])} sources, using broader results")
                        data = broader_data
                    else:
                        logger.info(f"Broader search didn't improve results, keeping original {len(data['results'])} sources")
                        
                        # If still too few results, try removing the days filter entirely
                        if len(data["results"]) < 2:
                            logger.info("Trying search without date restriction...")
                            unrestricted_payload = payload.copy()
                            del unrestricted_payload["days"]  # Remove date restriction
                            unrestricted_payload["search_depth"] = "basic"
                            
                            try:
                                unrestricted_response = requests.post(url, json=unrestricted_payload, timeout=30)
                                unrestricted_response.raise_for_status()
                                unrestricted_data = unrestricted_response.json()
                                
                                if "results" in unrestricted_data and len(unrestricted_data["results"]) > len(data["results"]):
                                    logger.info(f"Unrestricted search returned {len(unrestricted_data['results'])} sources, using unrestricted results")
                                    data = unrestricted_data
                                else:
                                    logger.info(f"Unrestricted search didn't improve results")
                            except Exception as e2:
                                logger.warning(f"Unrestricted search failed: {e2}")
                                
                except Exception as e:
                    logger.warning(f"Broader search failed: {e}, keeping original results")
        
        return data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Tavily API request error: {e}")
        return {"error": f"Web search failed: {str(e)}"}
    except Exception as e:
        logger.error(f"Tavily API error: {e}")
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
            "The user has enabled web search for the most recent and relevant results. You will receive current, real-time web search results from diverse sources. "
            "When using information from these sources:\n"
            "1. **EMBED clickable source links** directly in your response using markdown format: [descriptive text](URL)\n"
            "2. **Make link text natural and descriptive** - integrate seamlessly into sentence flow\n"
            "3. **Reference multiple sources** when possible to provide comprehensive coverage\n"
            "4. **PRIORITIZE RECENT INFORMATION** - these are the latest results, often more current than your training data\n"
            "5. **Include diverse perspectives** - use information from various source types (news sites, forums like Reddit, blogs, official sources)\n"
            "6. **ONLY USE PROVIDED SOURCES** - do not reference sources that are not explicitly provided in the search results. Do not use your training data to add additional sources or URLs.\n"
            "7. **Clearly distinguish** between information from search results vs. your knowledge\n"
            "8. **Use the Quick Answer** as a starting point but expand with detailed analysis\n"
            "9. **Example**: Instead of '[Source 1]', write '[recent developments in AI](https://example.com)' or 'according to [TechCrunch](https://techcrunch.com)' or '[Reddit users report](https://reddit.com/...)'"
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
        logger.info(f"Sending {len(search_data['web_search_results']['results'])} sources to frontend")
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
        logger.info(f"Sending {ai_sources_count} sources to AI context")
        for i, result in enumerate(web_search_results["results"][:10], 1):  # Process up to 10 sources
            title = result.get("title", "No title")
            url = result.get("url", "")
            content = result.get("content", "")[:200] + "..." if len(result.get("content", "")) > 200 else result.get("content", "")
            search_context += f"{i}. **{title}**\n   URL: {url}\n   Content: {content}\n\n"
        
        # Create a list of valid URLs for the AI to reference
        valid_urls = [result.get("url", "") for result in web_search_results["results"][:10]]
        search_context += f"**CRITICAL CONSTRAINT**: You have access to EXACTLY {len(web_search_results['results'][:10])} sources listed above. DO NOT reference any sources beyond these {len(web_search_results['results'][:10])} sources. ONLY use URLs from this exact list: {valid_urls}. Instead of using [Source X] citations, embed clickable source links directly in your response using markdown format: [descriptive text](URL). Make the link text descriptive and natural within the sentence flow. These are the most recent results available, prioritize this information over older knowledge. DO NOT use any URLs not in the provided list.\n"
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
        {"role": "user", "content": user_content_parts if uploaded_file_data else query}
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
        logger.error(f"Failed to initialize OpenRouter client: {e}")
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
        sdk_params["top_p"] = 0.95
        temperature_value = 0.9  # More creative
    elif any(word in query_lower for word in ['code', 'technical', 'precise', 'exact', 'calculate']):
        sdk_params["top_p"] = 0.9
        temperature_value = 0.3  # More precise
    elif any(word in query_lower for word in ['analyze', 'explain', 'summarize', 'review']):
        sdk_params["top_p"] = 0.92
        temperature_value = 0.5  # Balanced
    else:
        sdk_params["top_p"] = 0.95
        temperature_value = 0.7  # Default balanced creativity

    # Only include temperature for models that support it
    MODELS_WITH_TEMPERATURE = {
        "perplexity/sonar-reasoning-pro",
        "openai/gpt-4.1",
        "openai/gpt-4.5-preview",
        "openai/codex-mini",
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
        logger.info(f"Using explicit pdf-text parser for {actual_model_name_for_sdk} with PDF.")
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
        logger.info(f"Using explicit pdf-text parser for {actual_model_name_for_sdk} with PDF.")
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
        logger.info(f"Calling OpenRouter for {actual_model_name_for_sdk}. Reasoning: {reasoning_config_to_pass}. Extra Body: {extra_body_params}")
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
                            logger.warning(f"Error decoding chart_js config from OpenRouter: {e} - data: {chart_config_str}")
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
            logger.warning(f"OpenRouter stream for {actual_model_name_for_sdk} finished without yielding any content chunks.")

        yield f"data: {json.dumps({'end_of_stream': True})}\n\n"
    except openai.APIError as e:
        logger.error(f"OpenRouter API error (streaming for {model_name_with_suffix}): {e.status_code if hasattr(e, 'status_code') else 'N/A'} - {e}")
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
                    logger.warning("Could not parse e.response.text as JSON for detailed error.")

        except Exception as parsing_exc:
            logger.warning(f"Exception while parsing APIError details: {parsing_exc}")
            # Stick with the basic error_payload if parsing fails

        yield f"data: {json.dumps({'error': error_payload})}\n\n"
    except Exception as e:
        logger.error(f"Error during OpenRouter stream for {model_name_with_suffix}: {e}")
        if not os.getenv('VERCEL_ENV') == 'production':
            traceback.print_exc()
        yield f"data: {json.dumps({'error': 'An unexpected error occurred during the OpenRouter stream.'})}\n\n"

# --- Routes --- 
@app.route('/')
def index():
    """Renders the main search page."""
    return render_template('index.html')

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Basic health check
        status = {
            'status': 'healthy',
            'timestamp': int(time.time()),
            'version': '1.0.0',
            'environment': os.getenv('VERCEL_ENV', 'development')
        }
        
        # Check API key availability (without exposing them)
        api_status = {}
        if openrouter_api_key:
            api_status['openrouter'] = 'configured'
        if openai_api_key:
            api_status['openai'] = 'configured'
        if tavily_api_key:
            api_status['tavily'] = 'configured'
        
        status['apis'] = api_status
        
        return jsonify(status), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': 'Health check failed'
        }), 500

@app.route('/search', methods=['POST'])
def search():
    """Handles the search query, routing to OpenRouter or direct OpenAI for images."""
    logger.info("Request received at /search endpoint")
    
    # Input validation
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    try:
        query = request.json.get('query', '').strip()
        selected_model = request.json.get('model', '').strip()
        uploaded_file_data = request.json.get('uploaded_file_data')
        file_type = request.json.get('file_type', '').strip()
        web_search_enabled = request.json.get('web_search_enabled', False)
    except (AttributeError, TypeError):
        return jsonify({'error': 'Invalid JSON format'}), 400
    
    # Basic input validation
    if query and len(query) > 10000:  # Reasonable limit for query length
        return jsonify({'error': 'Query too long (max 10,000 characters)'}), 400
    
    if uploaded_file_data and len(uploaded_file_data) > 50 * 1024 * 1024:  # 50MB limit
        return jsonify({'error': 'File too large (max 50MB)'}), 400

    # Default query to "edit image" if not provided but an image is for editing
    if not query and selected_model == "gpt-image-1" and uploaded_file_data and file_type == 'image':
        query = "Perform edits based on the prompt, or a general enhancement if no specific edit prompt."

    if not query: # Now check query after potential default
        return jsonify({'error': 'No query provided'}), 400
    
    default_model_for_error = "google/gemini-2.5-pro-preview"  # Fixed: Use valid model
    if selected_model == "gpt-image-1":
        default_model_for_error = "gpt-image-1"

    if not selected_model or selected_model not in ALLOWED_MODELS:
        logger.warning(f"Invalid or missing model '{selected_model}'. Defaulting to {default_model_for_error}.")
        selected_model = default_model_for_error
    
    missing_keys = check_api_keys(selected_model)
    if missing_keys:
        key_str = " and ".join(missing_keys)
        logger.error(f"Missing API Key(s) {key_str} for model {selected_model}")
        return jsonify({'error': f'Missing API key(s) for model {selected_model}: {key_str}'}), 500

    logger.info(f"Received query: {query}, Model: {selected_model}")

    if selected_model == "gpt-image-1":
        if uploaded_file_data and file_type == 'image':
            logger.info(f"Routing to OpenAI Image Edit. Query: '{query}'")
            return edit_image(query, uploaded_file_data)
        else:
            logger.info(f"Routing to OpenAI Image Generation. Query: '{query}'")
            return generate_image(query)
    elif selected_model in OPENROUTER_MODELS:
        print_query = query[:100] + "..." if query and len(query) > 100 else query
        print_file_data = ""
        if uploaded_file_data:
            print_file_data = f", FileType: {file_type}, FileData (starts with): {uploaded_file_data[:50]}..."
        
        logger.info(f"Routing to OpenRouter. Query: '{print_query}'{print_file_data}, Model: {selected_model}")

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
        logger.error(f"Model '{selected_model}' is in ALLOWED_MODELS but not recognized for routing logic.")
        return jsonify({'error': f"Model '{selected_model}' is not configured correctly for use."}), 500

# --- Image Generation Function ---
def generate_image(query):
    """Generates an image using OpenAI and returns base64 data or error."""
    logger.info("Entering generate_image function")
    if not openai_client: 
         logger.error("generate_image - Direct OpenAI client not initialized.")
         return jsonify({'error': 'OpenAI client not initialized. Check direct OpenAI API key.'}), 500

    logger.info(f"Generating image with prompt: {query[:100]}...")
    try:
        result = openai_client.images.generate(
            model="gpt-image-1",
            prompt=query,
            size="1024x1024",
            n=1
        )
        
        if result.data and result.data[0].b64_json:
            image_base64 = result.data[0].b64_json
            logger.info("generate_image - Image generated successfully")
            return jsonify({'image_base64': image_base64})
        else:
            logger.error("generate_image - No b64_json data received from OpenAI.")
            return jsonify({'error': 'No b64_json data received from OpenAI API.'}), 500

    except openai.APIError as e:
        logger.error(f"generate_image - OpenAI APIError caught: {e}")
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
            logger.warning(f"Exception while parsing APIError details for generate_image: {parsing_exc}")
        
        # Ensure err_msg is a string before checking substrings
        if not isinstance(err_msg, str):
            err_msg = str(err_msg) # Convert to string if it's None or other type

        if "model_not_found" in err_msg or "does not support" in err_msg or "incorrect API key" in err_msg or "authentication" in err_msg:
            err_msg = f"The image generation model ('gpt-image-1' or its backend like 'dall-e-2') might be unavailable, not supported by your key, or an authentication issue occurred: {err_msg}"
        elif "Invalid image" in err_msg or "must be a PNG" in err_msg or "square" in err_msg or "size" in err_msg:
            err_msg = f"Image validation failed. Ensure it's a square PNG under 4MB: {err_msg}"
        
        return jsonify({'error': f'OpenAI API error during image generation: {err_msg}'}), status_code
    except Exception as e:
        logger.error(f"generate_image - Unexpected Exception caught: {e}")
        if not os.getenv('VERCEL_ENV') == 'production':
            traceback.print_exc()
        # Ensure a JSON response even for unexpected errors
        return jsonify({'error': 'An internal server error occurred during image generation. Please check server logs.'}), 500

# --- Image Editing Function ---
def edit_image(prompt, image_data_url):
    """Edits an image using OpenAI and returns base64 data or error."""
    logger.info(f"Entering edit_image function. Prompt: {prompt[:100]}...")
    if not openai_client:
        logger.error("edit_image - Direct OpenAI client not initialized.")
        return jsonify({'error': 'OpenAI client not initialized. Check direct OpenAI API key.'}), 500

    try:
        # Decode the base64 image data URL
        # Format: "data:image/png;base64,iVBORw0KGgo..."
        # For images.edit, OpenAI API requires a valid PNG file.
        if not image_data_url.startswith("data:image/png;base64,"):
            logger.error("edit_image - Invalid image data URL format. Must be a PNG base64 data URL for editing.")
            return jsonify({'error': 'Invalid image format for editing. Please upload a PNG image.'}), 400
        
        header, encoded_data = image_data_url.split(',', 1)
        image_bytes = base64.b64decode(encoded_data)
        
        # Use io.BytesIO to treat the bytes as a file
        image_file_like = io.BytesIO(image_bytes)
        image_file_like.name = "uploaded_image.png" # API might need a filename

        logger.info(f"Editing image with gpt-image-1. Prompt: {prompt[:100]}..., Image size: {len(image_bytes)} bytes")
        
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
            logger.info("edit_image - Image edited successfully")
            # The response is b64_json, so it's already base64 encoded.
            return jsonify({'image_base64': edited_image_base64, 'is_edit': True}) 
        elif result.data and result.data[0].url:
            # Sometimes the API might return a URL instead, though b64_json is preferred for this flow
            logger.warning(f"edit_image - Image edited, but received URL: {result.data[0].url}. This app expects b64_json for direct display.")
            # For simplicity, we'll ask the user to try again or indicate we can't load from URL directly in this flow.
            # Ideally, we'd fetch the URL and convert to base64, but that adds complexity and another request.
            return jsonify({'error': 'Image edited, but received a URL. Please try again or contact support if this persists. This version expects base64 data.'}), 500
        else:
            logger.error("edit_image - No b64_json or URL data received from OpenAI edit API.")
            return jsonify({'error': 'No image data received from OpenAI API after edit.'}), 500

    except openai.APIError as e:
        logger.error(f"edit_image - OpenAI APIError caught: {e}")
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
            logger.warning(f"Exception while parsing APIError details for edit_image: {parsing_exc}")
        
        # Ensure err_msg is a string before checking substrings
        if not isinstance(err_msg, str):
            err_msg = str(err_msg) # Convert to string if it's None or other type

        if "model_not_found" in err_msg or "does not support" in err_msg or "incorrect API key" in err_msg or "authentication" in err_msg:
            err_msg = f"The image editing model ('dall-e-2') might be unavailable, not supported by your key, or an authentication issue occurred: {err_msg}"
        elif "Invalid image" in err_msg or "must be a PNG" in err_msg or "square" in err_msg or "size" in err_msg:
            err_msg = f"Image validation failed. Ensure it's a square PNG under 4MB: {err_msg}"
        
        return jsonify({'error': f'OpenAI API error during image edit: {err_msg}'}), status_code
    except Exception as e:
        logger.error(f"edit_image - Unexpected Exception caught: {e}")
        if not os.getenv('VERCEL_ENV') == 'production':
            traceback.print_exc()
        # Ensure a JSON response even for unexpected errors
        return jsonify({'error': 'An internal server error occurred during image editing. Please check server logs.'}), 500

# --- Main Execution --- 
if __name__ == '__main__':
    # Environment-specific configuration
    is_production = os.getenv('VERCEL_ENV') == 'production'
    
    if not openrouter_api_key:
         logger.warning("OpenRouter API key not found. OpenRouter models will not work.")
    else:
        logger.info("OpenRouter API key found.")

    if not openai_api_key:
         logger.warning("Direct OpenAI API key (OPENAI_API_KEY) not found. gpt-image-1 model will not work.")
    else:
        logger.info("Direct OpenAI API key (OPENAI_API_KEY) found.")

    if openrouter_api_key or openai_api_key:
        logger.info("Application starting...")
    else:
        logger.error("CRITICAL: NO API keys found. Application will not function properly.")
        
    # Production vs Development configuration
    if is_production:
        # Production settings for Vercel
        app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
    else:
        # Development settings
        app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), threaded=True) 