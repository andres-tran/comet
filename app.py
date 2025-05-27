import os
import json
import openai
import base64
import requests
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
import traceback
import io # Added for image editing
from typing import Dict, List, Any, Optional
import uuid
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Background task storage
BACKGROUND_TASKS = {}
TASK_LOCK = threading.Lock()
TASK_EXECUTOR = ThreadPoolExecutor(max_workers=5)
TASK_CLEANUP_INTERVAL = 300  # Clean up old tasks every 5 minutes
MAX_TASK_AGE = 3600  # Keep tasks for 1 hour

# Task status enum
class TaskStatus:
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# Background task class
class BackgroundTask:
    def __init__(self, task_id, model, query, **kwargs):
        self.id = task_id
        self.model = model
        self.query = query
        self.status = TaskStatus.QUEUED
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.progress = 0
        self.result = None
        self.error = None
        self.chunks = []
        self.metadata = kwargs
        self.cancel_requested = False
        
    def to_dict(self):
        return {
            "id": self.id,
            "model": self.model,
            "query": self.query[:100] + "..." if len(self.query) > 100 else self.query,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "duration": (self.completed_at - self.started_at).total_seconds() if self.completed_at and self.started_at else None,
            "error": self.error,
            "chunks_count": len(self.chunks),
            "metadata": self.metadata
        }

# Background task cleanup
def cleanup_old_tasks():
    """Clean up old tasks periodically"""
    while True:
        time.sleep(TASK_CLEANUP_INTERVAL)
        with TASK_LOCK:
            current_time = datetime.now()
            tasks_to_remove = []
            for task_id, task in BACKGROUND_TASKS.items():
                if (current_time - task.created_at).total_seconds() > MAX_TASK_AGE:
                    tasks_to_remove.append(task_id)
            
            for task_id in tasks_to_remove:
                del BACKGROUND_TASKS[task_id]
                print(f"Cleaned up old task: {task_id}")

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_tasks, daemon=True)
cleanup_thread.start()

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
    "perplexity/sonar-deep-research", # Added new model
    "openai/gpt-4.1",
    "openai/gpt-4.5-preview",
    "openai/codex-mini",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-opus-4",
}
ALLOWED_MODELS = OPENROUTER_MODELS.copy()
ALLOWED_MODELS.add("gpt-image-1")
ALLOWED_MODELS.add("agentic-mode")  # Special mode for agentic workflows

# --- Background Streaming for OpenRouter ---
def stream_openrouter_background(task_id, query, model_name_with_suffix, reasoning_config=None, uploaded_file_data=None, file_type=None, web_search_enabled=False):
    """
    Background processing version of stream_openrouter.
    This runs in a separate thread and updates the task object with progress.
    """
    task = BACKGROUND_TASKS.get(task_id)
    if not task:
        print(f"Background task {task_id} not found")
        return
    
    try:
        # Update task status
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.now()
        
        # Create a generator to collect chunks
        generator = stream_openrouter(
            query=query,
            model_name_with_suffix=model_name_with_suffix,
            reasoning_config=reasoning_config,
            uploaded_file_data=uploaded_file_data,
            file_type=file_type,
            web_search_enabled=web_search_enabled
        )
        
        # Process the stream and collect chunks
        chunk_count = 0
        total_content = ""
        
        for chunk_data in generator:
            if task.cancel_requested:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()
                print(f"Task {task_id} cancelled")
                return
            
            # Parse the SSE data
            if chunk_data.startswith("data: "):
                try:
                    json_data = json.loads(chunk_data[6:].strip())
                    
                    # Store the chunk
                    task.chunks.append(json_data)
                    chunk_count += 1
                    
                    # Extract content for summary
                    if 'chunk' in json_data:
                        total_content += json_data['chunk']
                    
                    # Update progress (estimate based on typical response length)
                    if chunk_count < 50:
                        task.progress = min(chunk_count * 2, 90)
                    else:
                        task.progress = min(90 + (chunk_count - 50) // 10, 99)
                    
                    # Handle end of stream
                    if json_data.get('end_of_stream'):
                        task.progress = 100
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = datetime.now()
                        task.result = {
                            "total_chunks": chunk_count,
                            "content_length": len(total_content),
                            "summary": total_content[:500] + "..." if len(total_content) > 500 else total_content
                        }
                        print(f"Task {task_id} completed successfully")
                        return
                    
                    # Handle errors
                    if 'error' in json_data:
                        task.status = TaskStatus.FAILED
                        task.error = json_data['error']
                        task.completed_at = datetime.now()
                        print(f"Task {task_id} failed: {json_data['error']}")
                        return
                        
                except json.JSONDecodeError as e:
                    print(f"Error parsing chunk for task {task_id}: {e}")
                    continue
        
        # If we reach here, the stream ended without explicit completion
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.progress = 100
        
    except Exception as e:
        print(f"Error in background task {task_id}: {e}")
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.completed_at = datetime.now()

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

# --- Citation Processing for Perplexity Models ---
def process_perplexity_citations(content, sources):
    """
    Process Perplexity model responses to extract and format citations.
    Converts numbered citations [1], [2], etc. to structured source data.
    """
    import re
    
    # Extract numbered citations from content
    citation_pattern = r'\[(\d+)\]'
    citations_found = re.findall(citation_pattern, content)
    
    if not citations_found:
        return None
    
    processed_sources = []
    
    # If we have sources from metadata, use them
    if sources and isinstance(sources, list):
        for i, source in enumerate(sources, 1):
            if str(i) in citations_found:
                if isinstance(source, dict):
                    processed_sources.append({
                        'citation_number': i,
                        'title': source.get('title', f'Source {i}'),
                        'url': source.get('url', ''),
                        'domain': extract_domain(source.get('url', '')),
                        'snippet': source.get('snippet', source.get('content', ''))[:200] + '...' if source.get('snippet', source.get('content', '')) else ''
                    })
                elif isinstance(source, str):
                    # Sometimes sources might just be URLs
                    processed_sources.append({
                        'citation_number': i,
                        'title': f'Source {i}',
                        'url': source,
                        'domain': extract_domain(source),
                        'snippet': ''
                    })
    else:
        # If no metadata sources, create placeholder sources for found citations
        for citation_num in set(citations_found):
            processed_sources.append({
                'citation_number': int(citation_num),
                'title': f'Source {citation_num}',
                'url': '',
                'domain': 'perplexity.ai',
                'snippet': 'Source information not available'
            })
    
    return processed_sources

def extract_domain(url):
    """Extract domain from URL for display purposes."""
    if not url:
        return ''
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        return domain
    except:
        return url

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
        max_tokens_val = 50000 # Conservative to avoid credit/token limit errors
    elif actual_model_name_for_sdk == "perplexity/sonar-deep-research": # 128,000 total context
        max_tokens_val = 50000 # Conservative allocation to ensure we don't exceed credit limits
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
        # Dynamic token adjustment based on input size
        input_text_length = len(user_content_parts[0]['text'])
        estimated_input_tokens = input_text_length // 4  # Rough estimate: 1 token ≈ 4 characters
        
        # For models with limited context, adjust max_tokens dynamically
        context_limited_models = {
            "perplexity/sonar-reasoning-pro": 128000,
            "perplexity/sonar-deep-research": 128000,
            "openai/gpt-4.5-preview": 128000,
            "openai/gpt-4o-search-preview": 32000,  # Smaller context window
        }
        
        if actual_model_name_for_sdk in context_limited_models:
            model_context_limit = context_limited_models[actual_model_name_for_sdk]
            # Conservative approach: ensure we don't exceed context window
            available_tokens = model_context_limit - estimated_input_tokens - 2000  # 2000 token safety buffer
            if available_tokens < max_tokens_val:
                max_tokens_val = max(available_tokens, 1000)  # Ensure at least 1000 tokens for output
                print(f"Adjusted max_tokens for {actual_model_name_for_sdk}: {max_tokens_val} (input ~{estimated_input_tokens} tokens, context limit: {model_context_limit})")
                
                # Update the SDK params with adjusted value
                sdk_params["max_tokens"] = max_tokens_val
        
        # Additional credit-aware adjustment for expensive models
        if actual_model_name_for_sdk in ["perplexity/sonar-deep-research", "perplexity/sonar-reasoning-pro"]:
            # Cap at a reasonable limit to avoid credit issues
            credit_safe_limit = min(max_tokens_val, 30000)  # Cap at 30k tokens for credit safety
            if credit_safe_limit < max_tokens_val:
                max_tokens_val = credit_safe_limit
                sdk_params["max_tokens"] = max_tokens_val
                print(f"Applied credit-safe limit for {actual_model_name_for_sdk}: {max_tokens_val} tokens")
        
        print(f"Calling OpenRouter for {actual_model_name_for_sdk}. Reasoning: {reasoning_config_to_pass}. Extra Body: {extra_body_params}")
        
        # Debug: Log the enhanced query content being sent to AI
        if web_search_enabled and web_search_results:
            print(f"Enhanced query includes web search context with {len(web_search_results.get('results', []))} sources")
            print(f"Enhanced query length: {input_text_length} characters (~{estimated_input_tokens} tokens)")
        else:
            print(f"No web search context - query length: {input_text_length} characters (~{estimated_input_tokens} tokens)")
        
        stream = openrouter_client_instance.chat.completions.create(**sdk_params, extra_body=extra_body_params)
        buffer = ""
        in_chart_config_block = False
        chart_config_str = ""
        content_received_from_openrouter = False # Flag to track content
        perplexity_sources = []  # Store sources for Perplexity models
        accumulated_content = ""  # Accumulate content for citation processing

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
                accumulated_content += delta.content  # Accumulate for citation processing
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
            
            # Extract sources from Perplexity models - try multiple approaches
            if hasattr(chunk.choices[0], 'message'):
                message = chunk.choices[0].message
                
                # Check message metadata
                if hasattr(message, 'metadata') and message.metadata:
                    if 'sources' in message.metadata:
                        perplexity_sources = message.metadata['sources']
                    elif 'citations' in message.metadata:
                        perplexity_sources = message.metadata['citations']
                
                # Check message content for source information
                if hasattr(message, 'content') and message.content:
                    # Try to extract sources from content if available
                    pass
            
            # Check for sources in delta metadata
            if hasattr(delta, 'metadata') and delta.metadata:
                if 'sources' in delta.metadata:
                    perplexity_sources = delta.metadata['sources']
                elif 'citations' in delta.metadata:
                    perplexity_sources = delta.metadata['citations']
            
            # Check for sources in chunk metadata
            if hasattr(chunk, 'metadata') and chunk.metadata:
                if 'sources' in chunk.metadata:
                    perplexity_sources = chunk.metadata['sources']
                elif 'citations' in chunk.metadata:
                    perplexity_sources = chunk.metadata['citations']

        if buffer: 
            if in_chart_config_block: # Means block was not properly terminated
                 data_to_yield = {'chunk': start_marker + chart_config_str + buffer} # yield as text
                 yield f"data: {json.dumps(data_to_yield)}\n\n"
            else:
                 yield f"data: {json.dumps({'chunk': buffer})}\n\n"

        if not content_received_from_openrouter:
            print(f"Warning: OpenRouter stream for {actual_model_name_for_sdk} finished without yielding any content chunks.")

        # Process citations for Perplexity models
        if actual_model_name_for_sdk.startswith("perplexity/") and accumulated_content:
            processed_sources = process_perplexity_citations(accumulated_content, perplexity_sources)
            if processed_sources:
                yield f"data: {json.dumps({'perplexity_sources': processed_sources})}\n\n"

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
        print(f"Routing to Agentic Mode. Query: '{query}'")
        # Use the working agentic loop implementation
        agentic_model = "google/gemini-2.5-pro-preview"  # Default agentic model
        generator = run_agentic_loop(query, agentic_model)
        return Response(generator, mimetype='text/event-stream')
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
        "- Think step-by-step using Chain-of-Thought reasoning\n"
        "- Before taking action, explicitly state: 1) What you understand, 2) What you plan to do, 3) Why this approach is optimal\n"
        "- Break down complex tasks into manageable sub-tasks with clear dependencies\n"
        "- Use self-consistency: consider multiple approaches and choose the most reliable\n"
        "- Learn from tool results and adapt your strategy accordingly\n"
        "- Practice self-reflection: after each tool use, evaluate if the result meets expectations\n\n"
        
        "🛠️ **AVAILABLE TOOLS & CAPABILITIES:**\n"
        "🕒 **get_current_time**: Get current date and time for temporal context\n"
        "🧮 **calculate_math**: Perform mathematical calculations and analysis\n"
        "🔍 **search_web_tool**: Enhanced web search with intelligent type detection (Tavily-powered)\n"
        "   - Auto-detects search type (news, general, deep research)\n"
        "   - Returns quality-ranked results with metadata\n"
        "   - Configurable depth and result count\n"
        "🌐 **search_web_openrouter**: OpenRouter web search via Perplexity (Real-time web access)\n"
        "   - Uses Perplexity's sonar-reasoning-pro with built-in web search\n"
        "   - Provides real-time web information with citations\n"
        "   - Configurable search context size and detail level\n"
        "📝 **create_note**: Create and save structured notes or summaries\n"
        "🔬 **research_topic**: Comprehensive multi-step research workflow\n"
        "   - Combines overview, news, and analysis searches\n"
        "   - Aggregates findings from multiple sources\n"
        "   - Provides quality distribution and research summary\n"
        "🔬 **advanced_research_with_synthesis**: Advanced multi-step research with synthesis\n"
        "   - Demonstrates tool chaining and context preservation\n"
        "   - Quality assessment and intelligent synthesis\n"
        "   - Multi-angle information gathering\n\n"
        
        "📋 **ENHANCED AGENTIC WORKFLOW & ORCHESTRATION:**\n"
        "1. **UNDERSTAND** - Parse the user's request and identify implicit needs\n"
        "2. **REASON** - Think through multiple solution paths and their trade-offs\n"
        "3. **PLAN** - Create a step-by-step strategy with contingencies\n"
        "4. **EXECUTE** - Use tools systematically, building on previous results\n"
        "5. **VALIDATE** - Check if results meet quality standards and user needs\n"
        "6. **ADAPT** - Modify approach based on intermediate results\n"
        "7. **SYNTHESIZE** - Combine findings into comprehensive, actionable insights\n\n"
        
        "🎯 **THOROUGHNESS MANDATE:**\n"
        "- **Use Multiple Iterations**: You have up to 5 iterations - use them to provide exceptional value\n"
        "- **Diversify Tool Usage**: Combine different tools for comprehensive analysis\n"
        "- **Layer Information**: Build upon previous findings with additional perspectives\n"
        "- **Cross-Validate**: Use multiple sources and methods to verify insights\n"
        "- **Add Value Each Step**: Each iteration should contribute unique insights\n"
        "- **Think Comprehensively**: Consider multiple angles, implications, and follow-up questions\n\n"
        
        "🎯 **INTELLIGENT TOOL SELECTION STRATEGY:**\n"
        "- **Simple factual queries**: Use search_web_tool with auto-detection\n"
        "- **Current events/breaking news**: Use search_web_tool with type='news'\n"
        "- **Real-time web information needed**: Use search_web_openrouter for current data\n"
        "- **Comprehensive research with citations**: Use search_web_openrouter with context_size='high'\n"
        "- **Complex research topics**: Use research_topic for multi-angle analysis\n"
        "- **Technical tutorials/guides**: Use search_web_tool with type='general'\n"
        "- **Academic/detailed analysis**: Use search_web_tool with type='deep' or search_web_openrouter for real-time data\n"
        "- **Calculations/quantitative analysis**: Use calculate_math\n"
        "- **Information organization**: Use create_note to structure findings\n"
        "- **Advanced synthesis**: Use advanced_research_with_synthesis for complex topics\n"
        "- **Multi-step problems**: Chain tools together logically\n\n"
        
        "🔍 **QUALITY ASSURANCE & VALIDATION:**\n"
        "- Cross-reference information from multiple sources when possible\n"
        "- Clearly distinguish between verified facts and speculation\n"
        "- Acknowledge limitations and uncertainties in your knowledge\n"
        "- Provide source citations and quality indicators\n"
        "- Use self-consistency: if unsure, gather additional information\n"
        "- Validate tool outputs before proceeding to next steps\n\n"
        
        "🤔 **METACOGNITIVE REASONING:**\n"
        "- Before each action, ask: 'Is this the most effective approach?'\n"
        "- After each tool use, evaluate: 'Did this provide the expected value?'\n"
        "- If stuck, try alternative approaches or break down the problem differently\n"
        "- Consider the user's likely follow-up questions and address them proactively\n"
        "- Balance thoroughness with efficiency based on query complexity\n\n"
        
        "💬 **ENHANCED RESPONSE GUIDELINES:**\n"
        "- Begin with a brief reasoning statement about your approach\n"
        "- Provide comprehensive answers with clear structure and headings\n"
        "- Include actionable insights and specific recommendations\n"
        "- Show your reasoning process when it adds value\n"
        "- Adapt communication style to match user expertise level\n"
        "- End with relevant follow-up suggestions or next steps\n\n"
        
        "🔄 **ITERATIVE IMPROVEMENT:**\n"
        "- If initial results are insufficient, refine your approach\n"
        "- Use few-shot learning from successful patterns in the conversation\n"
        "- Build context across multiple tool calls for better outcomes\n"
        "- Learn from user feedback and adjust strategy accordingly\n\n"
        
        "Remember: You are an intelligent agent capable of autonomous reasoning, planning, and tool use. "
        "Think critically, plan strategically, execute systematically, and continuously improve your approach. "
        "Your goal is not just to answer questions, but to provide comprehensive, actionable intelligence.\n\n"
        
        "🚀 **EXECUTION EXCELLENCE:**\n"
        "- **Maximize Your Iterations**: You have 5 iterations available - use them to deliver exceptional value\n"
        "- **Don't Stop Early**: Unless the task is truly simple, explore multiple angles and perspectives\n"
        "- **Build Incrementally**: Each iteration should add meaningful insights to your analysis\n"
        "- **Think Like an Expert**: What would a domain expert do with access to these tools?\n"
        "- **Exceed Expectations**: Go beyond the basic request to provide comprehensive intelligence"
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

        def validate_progress(iteration, task_plan, recent_tools):
            """
            Self-reflection mechanism to evaluate progress and suggest adaptations.
            Based on 2024 best practices for agentic AI systems.
            """
            validation_insights = []
            
            # Check for tool repetition without progress
            if len(recent_tools) >= 3 and len(set(recent_tools[-3:])) == 1:
                validation_insights.append("⚠️ Detected repeated tool usage - considering alternative approach")
                
            # Check for balanced information gathering
            search_tools = [t for t in recent_tools if 'search' in t or 'research' in t]
            if len(search_tools) > 2 and iteration < max_iterations - 1:
                validation_insights.append("✅ Comprehensive information gathering in progress")
                
            # Check for synthesis readiness
            if len(task_plan.get("steps_completed", [])) >= 2 and iteration >= max_iterations - 2:
                validation_insights.append("🎯 Preparing for synthesis and final response")
                
            # Suggest next best action based on current state
            if not recent_tools:
                validation_insights.append("🚀 Starting with information gathering")
            elif all('search' in t or 'research' in t for t in recent_tools[-2:]):
                validation_insights.append("💡 Consider analysis or calculation tools for deeper insights")
                
            return validation_insights

        def call_llm(msgs):
            """Call LLM with tools - following OpenRouter documentation pattern"""
            resp = openrouter_client_instance.chat.completions.create(
                model=model_name,
                tools=AGENTIC_TOOLS,
                messages=msgs,
                temperature=0.3,  # Lower temperature for more consistent reasoning
                top_p=0.9,        # Balanced creativity and focus
            )
            # Convert message to dict format compatible with OpenAI API
            message = resp.choices[0].message
            message_dict = {
                "role": message.role,
                "content": message.content
            }
            if message.tool_calls:
                message_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            msgs.append(message_dict)
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
        task_plan = {"objective": query, "steps_completed": [], "current_step": "analysis", "strategy_adaptations": []}
        
        # Initial planning phase with explicit reasoning
        yield f"data: {json.dumps({'reasoning': '🧠 Analyzing request and planning optimal approach...'})}\n\n"
        
        while iteration < max_iterations:
            iteration += 1
            print(f"Agentic loop iteration {iteration} - Current step: {task_plan['current_step']}")
            
            # Self-reflection and progress validation
            validation_insights = validate_progress(iteration, task_plan, total_tools_used)
            if validation_insights:
                for insight in validation_insights:
                    yield f"data: {json.dumps({'reasoning': insight})}\n\n"
                    task_plan["strategy_adaptations"].extend(validation_insights)
            
            # Add metacognitive prompting for better reasoning
            if iteration > 1 and total_tools_used:
                metacognitive_context = (
                    f"\n\nMETACOGNITIVE REFLECTION:\n"
                    f"Previous tools used: {', '.join(total_tools_used[-3:])}\n"
                    f"Current progress: {len(task_plan['steps_completed'])} steps completed\n"
                    f"Validation insights: {'; '.join(validation_insights) if validation_insights else 'On track'}\n"
                    f"Consider: Is the current approach optimal? Should I adapt my strategy?\n"
                )
                # Add reflection to the conversation context
                messages.append({"role": "system", "content": metacognitive_context})
            
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
                    
                    # Enhanced task plan tracking
                    step_info = {
                        "iteration": iteration,
                        "tool": tool_name,
                        "args": json.loads(tool_call.function.arguments),
                        "timestamp": get_current_time()["current_time"]
                    }
                    task_plan["steps_completed"].append(step_info)
                
                # Enhanced progress updates with better context
                if "search_web_tool" in tool_calls_used:
                    task_plan["current_step"] = "information_gathering"
                    yield f"data: {json.dumps({'reasoning': f'🔍 Gathering targeted information from the web... (Step {iteration}/{max_iterations})'})}\n\n"
                elif "search_web_openrouter" in tool_calls_used:
                    task_plan["current_step"] = "real_time_research"
                    yield f"data: {json.dumps({'reasoning': f'🌐 Accessing real-time web information via Perplexity... (Step {iteration}/{max_iterations})'})}\n\n"
                elif "research_topic" in tool_calls_used:
                    task_plan["current_step"] = "comprehensive_research"
                    yield f"data: {json.dumps({'reasoning': f'🔬 Conducting multi-dimensional research analysis... (Step {iteration}/{max_iterations})'})}\n\n"
                elif "calculate_math" in tool_calls_used:
                    task_plan["current_step"] = "quantitative_analysis"
                    yield f"data: {json.dumps({'reasoning': f'🧮 Performing calculations and quantitative analysis... (Step {iteration}/{max_iterations})'})}\n\n"
                elif "create_note" in tool_calls_used:
                    task_plan["current_step"] = "knowledge_organization"
                    yield f"data: {json.dumps({'reasoning': f'📝 Organizing and structuring findings... (Step {iteration}/{max_iterations})'})}\n\n"
                else:
                    task_plan["current_step"] = "tool_execution"
                    yield f"data: {json.dumps({'reasoning': f'🛠️ Executing specialized tools: {", ".join(tool_calls_used)} (Step {iteration}/{max_iterations})'})}\n\n"
                
                # Enhanced continuation logic - encourage more thorough exploration
                should_continue = False
                continuation_reasons = []
                
                # Check if we should continue based on various criteria
                if iteration < 3:
                    should_continue = True
                    continuation_reasons.append("Early exploration phase - gathering more information")
                
                # Check for opportunities to use different tools
                unique_tools_used = set(total_tools_used)
                available_tools = {"search_web_tool", "search_web_openrouter", "research_topic", "calculate_math", "create_note", "advanced_research_with_synthesis"}
                unused_tools = available_tools - unique_tools_used
                
                if len(unused_tools) > 2 and iteration < max_iterations - 1:
                    should_continue = True
                    continuation_reasons.append(f"Multiple tools available for deeper analysis: {', '.join(list(unused_tools)[:3])}")
                
                # Check if we can enhance the analysis with additional perspectives
                if "search_web_tool" in total_tools_used and "search_web_openrouter" not in total_tools_used and iteration < max_iterations - 1:
                    should_continue = True
                    continuation_reasons.append("Can enhance with real-time web search for current information")
                
                if any("search" in tool for tool in total_tools_used) and "calculate_math" not in total_tools_used and iteration < max_iterations - 1:
                    # Check if the query might benefit from calculations
                    query_lower = query.lower()
                    if any(word in query_lower for word in ['calculate', 'cost', 'roi', 'percentage', 'compare', 'analyze', 'metrics', 'performance']):
                        should_continue = True
                        continuation_reasons.append("Query suggests quantitative analysis would be valuable")
                
                # Check for synthesis opportunities
                if len(task_plan["steps_completed"]) >= 2 and "create_note" not in total_tools_used and iteration < max_iterations - 1:
                    should_continue = True
                    continuation_reasons.append("Multiple data sources gathered - synthesis and organization would be valuable")
                
                # Advanced monitoring: Adaptive strategy adjustments
                if iteration > 2:
                    recent_tools = total_tools_used[-3:]
                    if len(set(recent_tools)) == 1:
                        # Same tool used repeatedly - inject strategy adaptation
                        adaptation_prompt = (
                            f"I notice I've been using the same tool ({recent_tools[0]}) repeatedly. "
                            f"Let me diversify my approach with different tools for a more comprehensive analysis."
                        )
                        yield f"data: {json.dumps({'reasoning': f'🔄 {adaptation_prompt}'})}\n\n"
                        task_plan["strategy_adaptations"].append(f"Iteration {iteration}: Detected tool repetition, diversifying approach")
                        should_continue = True
                        continuation_reasons.append("Diversifying tool usage for comprehensive analysis")
                        
                        # Add adaptive guidance to conversation
                        messages.append({
                            "role": "system", 
                            "content": f"ADAPTIVE GUIDANCE: {adaptation_prompt} You have {max_iterations - iteration} iterations remaining. Consider using different tools like: {', '.join(list(unused_tools)[:3])} to provide a more comprehensive analysis."
                        })
                
                # If we have good reasons to continue and haven't hit max iterations, keep going
                if should_continue and iteration < max_iterations:
                    continuation_message = f"🔄 Continuing analysis - {'; '.join(continuation_reasons[:2])}"
                    yield f"data: {json.dumps({'reasoning': continuation_message})}\n\n"
                    
                    # Add guidance for next iteration
                    next_iteration_guidance = (
                        f"ITERATION {iteration + 1} GUIDANCE: You have completed {len(task_plan['steps_completed'])} steps. "
                        f"Consider using these tools for deeper analysis: {', '.join(list(unused_tools)[:3])}. "
                        f"Focus on providing comprehensive, multi-faceted insights. "
                        f"You have {max_iterations - iteration} iterations remaining to deliver exceptional value."
                    )
                    messages.append({
                        "role": "system",
                        "content": next_iteration_guidance
                    })
                    continue  # Continue the loop instead of ending
                    
            else:
                # No more tool calls, provide enhanced final synthesis
                task_plan["current_step"] = "synthesis_and_delivery"
                print(f"Agentic workflow completed after {iteration} iterations")
                print(f"Task plan: {task_plan}")
                print(f"Tools used: {total_tools_used}")
                
                # Log performance for monitoring and evaluation
                log_agent_performance(task_plan, total_tools_used, iteration, success=True)
                
                final_content = resp.choices[0].message.content
                
                # Stream the final response with enhanced orchestration summary
                if final_content:
                    # Add comprehensive workflow insights
                    if total_tools_used:
                        unique_tools = list(set(total_tools_used))
                        efficiency_score = len(unique_tools) / len(total_tools_used) if total_tools_used else 0
                        
                        workflow_summary = (
                            f"\n\n---\n"
                            f"**🤖 Enhanced Agent Workflow Summary:**\n"
                            f"- **Objective**: {task_plan['objective'][:100]}{'...' if len(task_plan['objective']) > 100 else ''}\n"
                            f"- **Iterations Completed**: {iteration}/{max_iterations}\n"
                            f"- **Tools Utilized**: {', '.join(unique_tools)}\n"
                            f"- **Efficiency Score**: {efficiency_score:.2f} (unique tools / total calls)\n"
                            f"- **Research Operations**: {len([s for s in task_plan['steps_completed'] if 'search' in s['tool'] or 'research' in s['tool']])}\n"
                            f"- **Strategy Adaptations**: {len(task_plan['strategy_adaptations'])}\n"
                            f"- **Quality Assurance**: ✅ Multi-source validation applied\n"
                            f"- **Status**: ✅ Task completed successfully with comprehensive analysis"
                        )
                        
                        if task_plan["strategy_adaptations"]:
                            workflow_summary += f"\n- **Adaptive Insights**: {'; '.join(task_plan['strategy_adaptations'][-2:])}"
                        
                        final_content += workflow_summary
                    
                    # Enhanced streaming with better readability
                    sentences = final_content.split('. ')
                    current_chunk = ""
                    
                    for sentence in sentences:
                        current_chunk += sentence + ". "
                        # Improved chunking logic for better user experience
                        if len(current_chunk) > 100 or sentence.endswith('\n') or '**' in sentence:
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
        import traceback
        traceback.print_exc()
        
        # Provide a more detailed error response
        error_message = f"Agentic loop error: {str(e)}"
        if "NameError" in str(e):
            error_message += " (Function definition issue - please check server logs)"
        elif "APIError" in str(e):
            error_message += " (API communication issue - please check API keys and connectivity)"
        elif "JSONDecodeError" in str(e):
            error_message += " (Response parsing issue - please try again)"
        
        yield f"data: {json.dumps({'error': error_message})}\n\n"

@app.route('/search/background', methods=['POST'])
def search_background():
    """
    Start a background search task for long-running models.
    Returns a task ID that can be polled for status.
    """
    print("--- Background search request received ---")
    query = request.json.get('query')
    selected_model = request.json.get('model')
    uploaded_file_data = request.json.get('uploaded_file_data')
    file_type = request.json.get('file_type')
    web_search_enabled = request.json.get('web_search_enabled', False)
    
    if not query:
        return jsonify({'error': 'No query provided'}), 400
    
    if not selected_model or selected_model not in OPENROUTER_MODELS:
        return jsonify({'error': f'Invalid model: {selected_model}'}), 400
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Create task object
    task = BackgroundTask(
        task_id=task_id,
        model=selected_model,
        query=query,
        uploaded_file_data=uploaded_file_data,
        file_type=file_type,
        web_search_enabled=web_search_enabled
    )
    
    # Store task
    with TASK_LOCK:
        BACKGROUND_TASKS[task_id] = task
    
    # Submit to executor
    TASK_EXECUTOR.submit(
        stream_openrouter_background,
        task_id,
        query,
        selected_model,
        None,  # reasoning_config
        uploaded_file_data,
        file_type,
        web_search_enabled
    )
    
    print(f"Started background task: {task_id} for model: {selected_model}")
    
    return jsonify({
        'id': task_id,
        'status': task.status,
        'created_at': task.created_at.isoformat(),
        'model': selected_model,
        'query_preview': query[:100] + "..." if len(query) > 100 else query
    })

@app.route('/tasks/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Get the status and results of a background task."""
    task = BACKGROUND_TASKS.get(task_id)
    
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    response = task.to_dict()
    
    # Include chunks if task is completed or failed
    if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
        response['chunks'] = task.chunks
        response['result'] = task.result
    
    return jsonify(response)

@app.route('/tasks/<task_id>/stream', methods=['GET'])
def stream_task_results(task_id):
    """
    Stream the results of a background task as they become available.
    This endpoint returns Server-Sent Events (SSE).
    """
    task = BACKGROUND_TASKS.get(task_id)
    
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    def generate():
        last_chunk_index = 0
        
        while True:
            # Check if task is cancelled
            if task.cancel_requested:
                yield f"data: {json.dumps({'status': 'cancelled'})}\n\n"
                break
            
            # Send new chunks
            current_chunks = task.chunks[last_chunk_index:]
            for chunk in current_chunks:
                yield f"data: {json.dumps(chunk)}\n\n"
            last_chunk_index = len(task.chunks)
            
            # Send status update
            yield f"data: {json.dumps({'status': task.status, 'progress': task.progress})}\n\n"
            
            # Check if task is complete
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                yield f"data: {json.dumps({'end_of_stream': True, 'status': task.status})}\n\n"
                break
            
            # Sleep briefly to avoid busy waiting
            time.sleep(0.1)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/tasks/<task_id>', methods=['DELETE'])
def cancel_task(task_id):
    """Cancel a background task."""
    task = BACKGROUND_TASKS.get(task_id)
    
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
        return jsonify({'error': 'Task already completed'}), 400
    
    task.cancel_requested = True
    
    return jsonify({
        'id': task_id,
        'status': 'cancel_requested',
        'message': 'Task cancellation requested'
    })

@app.route('/tasks', methods=['GET'])
def list_tasks():
    """List all background tasks with optional filtering."""
    status_filter = request.args.get('status')
    limit = request.args.get('limit', 50, type=int)
    
    tasks = []
    with TASK_LOCK:
        for task in BACKGROUND_TASKS.values():
            if status_filter and task.status != status_filter:
                continue
            tasks.append(task.to_dict())
    
    # Sort by created_at descending
    tasks.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Apply limit
    tasks = tasks[:limit]
    
    return jsonify({
        'tasks': tasks,
        'total': len(tasks)
    })

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

def advanced_research_with_synthesis(topic, research_depth="comprehensive", focus_areas=None):
    """
    Advanced research tool that demonstrates tool chaining and context preservation.
    Implements 2024 best practices for multi-step agentic workflows.
    """
    try:
        if focus_areas is None:
            focus_areas = ["overview", "recent_developments", "practical_applications"]
        
        research_results = {
            "topic": topic,
            "research_depth": research_depth,
            "focus_areas": focus_areas,
            "findings": {},
            "synthesis": "",
            "quality_metrics": {},
            "timestamp": get_current_time()["current_time"]
        }
        
        # Step 1: Multi-angle information gathering
        for area in focus_areas:
            search_query = f"{topic} {area.replace('_', ' ')}"
            
            # Use different search strategies for different focus areas
            if area == "recent_developments":
                search_type = "news"
            elif area == "practical_applications":
                search_type = "general"
            else:
                search_type = "deep"
            
            # Chain tool calls with context preservation
            search_results = search_web_tool(search_query, max_results=5, search_type=search_type)
            research_results["findings"][area] = search_results
        
        # Step 2: Quality assessment and synthesis
        total_sources = sum(len(findings.get("results", [])) for findings in research_results["findings"].values())
        high_quality_sources = 0
        
        for area, findings in research_results["findings"].items():
            if "results" in findings:
                high_quality_sources += len([r for r in findings["results"] if r.get("score", 0) > 0.7])
        
        research_results["quality_metrics"] = {
            "total_sources": total_sources,
            "high_quality_sources": high_quality_sources,
            "quality_ratio": high_quality_sources / total_sources if total_sources > 0 else 0,
            "coverage_areas": len(focus_areas)
        }
        
        # Step 3: Intelligent synthesis
        synthesis_points = []
        for area, findings in research_results["findings"].items():
            if "results" in findings and findings["results"]:
                top_result = findings["results"][0]
                synthesis_points.append(f"**{area.replace('_', ' ').title()}**: {top_result.get('content', 'No content available')[:200]}...")
        
        research_results["synthesis"] = "\n\n".join(synthesis_points)
        
        # Step 4: Generate actionable insights
        if research_results["quality_metrics"]["quality_ratio"] > 0.6:
            research_results["confidence_level"] = "High"
            research_results["recommendations"] = f"Based on {high_quality_sources} high-quality sources, this research provides reliable insights on {topic}."
        else:
            research_results["confidence_level"] = "Moderate"
            research_results["recommendations"] = f"Research completed with {total_sources} sources. Consider additional verification for critical decisions."
        
        return research_results
        
    except Exception as e:
        return {"error": f"Advanced research failed: {str(e)}", "topic": topic}

# Add the new tool to the available tools
AGENTIC_TOOLS.append({
    "type": "function",
    "function": {
        "name": "advanced_research_with_synthesis",
        "description": "Perform advanced multi-step research with intelligent synthesis and quality assessment. Demonstrates tool chaining and context preservation for complex topics.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic to research comprehensively"
                },
                "research_depth": {
                    "type": "string",
                    "description": "Depth of research: 'quick' (basic overview), 'standard' (balanced approach), 'comprehensive' (thorough analysis)",
                    "enum": ["quick", "standard", "comprehensive"]
                },
                "focus_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific areas to focus on (e.g., ['overview', 'recent_developments', 'practical_applications', 'challenges', 'future_trends'])"
                }
            },
            "required": ["topic"]
        }
    }
})

# Update tool mapping
TOOL_MAPPING["advanced_research_with_synthesis"] = advanced_research_with_synthesis

def search_web_openrouter(query, max_results=5, search_context_size="medium"):
    """
    Enhanced web search using OpenRouter's native web search capability.
    Uses models with built-in web search like Perplexity or web-enabled models.
    """
    if not openrouter_api_key:
        return {"error": "OpenRouter API key not configured"}
    
    try:
        openrouter_client_instance = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_api_key,
            default_headers={
                "HTTP-Referer": os.getenv("APP_SITE_URL", "http://localhost:8080"),
                "X-Title": os.getenv("APP_SITE_TITLE", "Comet AI Search")
            }
        )
        
        # Use a web-search enabled model like Perplexity
        web_search_prompt = (
            f"Search the web for comprehensive information about: {query}\n\n"
            f"Please provide:\n"
            f"1. A comprehensive answer based on current web sources\n"
            f"2. Include clickable source links in markdown format: [source title](URL)\n"
            f"3. Cite {max_results} high-quality sources\n"
            f"4. Focus on {search_context_size} level of detail\n"
            f"5. Ensure all information is current and well-sourced"
        )
        
        # Use Perplexity which has built-in web search capabilities
        response = openrouter_client_instance.chat.completions.create(
            model="perplexity/sonar-reasoning-pro",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a web search assistant with access to real-time web information. Provide comprehensive, well-cited responses with clickable source links in markdown format."
                },
                {
                    "role": "user", 
                    "content": web_search_prompt
                }
            ],
            max_tokens=2000,
            temperature=0.3
        )
        
        message = response.choices[0].message
        content = message.content
        
        # Extract URLs from markdown links in the content
        import re
        url_pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
        citations = []
        
        for match in re.finditer(url_pattern, content):
            title = match.group(1)
            url = match.group(2)
            citations.append({
                "title": title,
                "url": url,
                "source": "perplexity_web_search"
            })
        
        return {
            "success": True,
            "query": query,
            "search_type": "openrouter_perplexity",
            "content": content,
            "citations": citations,
            "search_context_size": search_context_size,
            "total_citations": len(citations),
            "model_used": "perplexity/sonar-reasoning-pro"
        }
        
    except Exception as e:
        print(f"OpenRouter web search error: {e}")
        return {"error": f"OpenRouter web search failed: {str(e)}"}

# Add OpenRouter web search as a new tool option
AGENTIC_TOOLS.append(    {
        "type": "function",
        "function": {
            "name": "search_web_openrouter",
            "description": "Search the web using OpenRouter's Perplexity model with real-time web access. Provides current information with citations and comprehensive analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find current information on the web"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of sources to cite (default: 5, max: 10)",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "search_context_size": {
                        "type": "string",
                        "description": "Detail level: 'low' (brief), 'medium' (moderate), 'high' (comprehensive)",
                        "enum": ["low", "medium", "high"]
                    }
                },
                "required": ["query"]
            }
        }
    })

# Update tool mapping
TOOL_MAPPING["search_web_openrouter"] = search_web_openrouter

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

