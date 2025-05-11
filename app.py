import os
import json
import openai
import requests # For Perplexity API
import google.generativeai as genai # Reverted to official import
from google.generativeai.types import GenerationConfig # Added for token limits
# from google.generativeai.types import Tool # For Google Search Grounding (REMOVED as grounding is disabled for now)
# Add base64 for image handling
import base64 
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
import traceback

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure API keys (ensure they are set in .env)
openai.api_key = os.getenv("OPENAI_API_KEY") # Keep this for OpenAI
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY") # Added for Gemini
openrouter_api_key = os.getenv("OPENROUTER_API_KEY") # Added for OpenRouter
# xai_api_key = os.getenv("XAI_API_KEY") # Removed for xAI

# --- API Clients (Optional but good practice) ---
# Initialize OpenAI client (recommended way)
openai_client = openai.OpenAI() if openai.api_key else None
# Initialize xAI client
# xai_client = openai.OpenAI(base_url="https://api.x.ai/v1", api_key=xai_api_key) if xai_api_key else None # Removed

# Configure Gemini client
if gemini_api_key:
    genai.configure(api_key=gemini_api_key)

# Perplexity API endpoint
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

# Allowed models (add more as needed and update frontend)
ALLOWED_MODELS = {
    # Perplexity (Updated based on table)
    "sonar-deep-research", # Deep Research Model
    "sonar",                # 128k
    "sonar-pro",            # 200k
    "sonar-reasoning",      # 128k
    "sonar-reasoning-pro",  # 128k
    "r1-1776",              # 128k
    # OpenAI
    "gpt-4.1",
    "o4-mini-2025-04-16",
    "o3-2025-04-16",
    "gpt-4o-search-preview-2025-03-11",
    "gpt-image-1", # Image Model
    "gpt-4.5-preview-2025-02-27", # New model
    # xAI Grok Models - REMOVED
    # Gemini Models
    "gemini-2.5-pro", # User-friendly name
    # OpenRouter Models
    "microsoft/phi-4-reasoning-plus:free",
    "deepseek/deepseek-r1:free",
    "google/gemini-2.5-pro-preview", # New OpenRouter paid model
    "perplexity/sonar-deep-research", # OpenRouter Perplexity model
}

# Explicit set of all OpenRouter model IDs
OPENROUTER_MODELS = {
    "microsoft/phi-4-reasoning-plus:free",
    "deepseek/deepseek-r1:free",
    "google/gemini-2.5-pro-preview",
    "perplexity/sonar-deep-research",
}

# Mapping for actual model IDs if they differ from user-friendly names
MODEL_ID_MAPPING = {
    "gemini-2.5-pro": "models/gemini-2.5-pro-exp-03-25" 
}

# --- Error Handling --- 
def check_api_keys(model_name):
    """Checks if the necessary API key for the selected model is loaded."""
    actual_model_id = MODEL_ID_MAPPING.get(model_name, model_name) # Get actual ID for checks

    # Check if it's an OpenAI model (standard prefix or specific custom names)
    is_openai_model = (
        actual_model_id.startswith('gpt-') or 
        actual_model_id == "o4-mini-2025-04-16" or 
        actual_model_id == "o3-2025-04-16" or
        actual_model_id == "gpt-4o-search-preview-2025-03-11" or
        actual_model_id == "gpt-image-1"
    )
    # is_xai_model = model_name.startswith('grok-') # Removed
    is_gemini_model = actual_model_id.startswith('gemini-') # This is for direct Gemini API
    is_openrouter_model = actual_model_id in OPENROUTER_MODELS

    missing = []
    if is_openai_model:
        if not openai.api_key or not openai_client: # Also check client initialization
            missing.append("OpenAI")
    # elif is_xai_model: # Removed xAI check
    #     if not xai_api_key or not xai_client:
    #         missing.append("xAI")
    elif is_gemini_model: # Added Gemini check (for direct Gemini API)
        if not gemini_api_key:
            missing.append("Gemini")
    elif is_openrouter_model: # Added OpenRouter check (for all OpenRouter models)
        if not openrouter_api_key:
            missing.append("OpenRouter")
    else: # Assuming Perplexity otherwise (if not OpenAI or Gemini)
        if not perplexity_api_key:
            missing.append("Perplexity")
    return missing

# --- Streaming Generators --- 

def stream_openai(query, model_name):
    """Generator for streaming responses from OpenAI."""
    if not openai_client:
        yield f"data: {json.dumps({'error': 'OpenAI client not initialized. Check API key.'})}\n\n"
        return

    model_token_limits = {
        "gpt-4.1": 32768,
        "o4-mini-2025-04-16": 100000,
        "o3-2025-04-16": 100000,
        "gpt-4o-search-preview-2025-03-11": 16384,
        "gpt-4.5-preview-2025-02-27": 16384,
        "default": 16384
    }
    max_tokens = model_token_limits.get(model_name, model_token_limits["default"])

    # Enhanced System Prompt for OpenAI
    enhanced_openai_system_prompt = """You are Comet, an advanced AI agent specializing in deep research, logical reasoning, and code generation.
Your purpose is to deliver insightful, well-reasoned answers and functional code.

## Core Competencies:
*   **Deep Research:** Conduct thorough analysis and synthesize complex information.
*   **Logical Reasoning:** Deduce, infer, and evaluate information to form sound conclusions.
*   **Code Generation:** Create, explain, and troubleshoot code in various languages.

## Operational Approach:
1.  **Understand & Analyze:** Decipher query intent, complexities, and requirements.
2.  **Research & Reason:** Access knowledge, perform web research, and apply logical frameworks.
3.  **Develop & Explain:** Construct comprehensive explanations, generate code, and provide clear justifications.
4.  **Format Clearly (Markdown):** Utilize Markdown for optimal structure, readability, and presentation (headings, lists, code blocks).
5.  **Maintain Integrity:** Ensure responses are accurate, objective, and helpful.
6.  **Acknowledge Limits:** Clearly state if a request is beyond current capabilities.

## Chart Generation:
*   **Priority:** Provide data/config for interactive Chart.js charts.
*   **Format:** Use a JSON object (e.g., `\"chartjs_config\"`).
*   **Fallback:** May use QuickChart.io for static images.
*   **Reproducibility:** Always provide Python code (Matplotlib/Seaborn) for chart recreation.
*   **Context:** Explain data and charts in your main response.

## Code-Specific Guidelines:
*   When providing code, ensure it is well-commented and follows best practices.
*   Specify the language and any necessary dependencies.
*   Offer explanations of the code's logic and functionality.

## Core Directives:
*   **Ethical Conduct:** No unethical, hateful, biased, or illegal content/code.
*   **Privacy:** Do not use or request personal information.
*   **Focus:** Address the user's research, reasoning, or coding query.
"""

    messages = [
        {"role": "system", "content": enhanced_openai_system_prompt},
        {"role": "user", "content": query}
    ]

    api_params = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "max_completion_tokens": max_tokens,
    }

    try:
        print(f"Calling chat.completions.create with params: {{'model': {model_name}, 'messages': ...}}")
        stream = openai_client.chat.completions.create(**api_params)
        buffer = ""
        in_chart_config_block = False
        chart_config_str = ""

        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is not None:
                buffer += content

                # Attempt to detect and extract chartjs_config block
                # This is a simple detection logic, could be made more robust
                start_marker = "[[CHARTJS_CONFIG_START]]"
                end_marker = "[[CHARTJS_CONFIG_END]]"

                if not in_chart_config_block and start_marker in buffer:
                    # Emit content before the block
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
                            print(f"Error decoding chart_js config: {e} - data: {chart_config_str}")
                            # Yield the problematic string as a regular chunk for debugging
                            yield f"data: {json.dumps({'chunk': start_marker + chart_config_str + end_marker})}" + "\n\n"
                        
                        buffer = post_block_content
                        in_chart_config_block = False
                        chart_config_str = ""
                    else:
                        chart_config_str += buffer
                        buffer = "" # Consumed into chart_config_str
                
                if not in_chart_config_block and buffer:
                    # Yield remaining buffer if not in a block and buffer is not empty
                    # This handles cases where buffer doesn't end with a marker or has content after a block
                    # To avoid sending incomplete chunks too often, we can check for newlines or a certain length
                    if "\n" in buffer or len(buffer) > 80: # Heuristic to send complete-ish lines
                        yield f"data: {json.dumps({'chunk': buffer})}\n\n"
                        buffer = ""

        # Yield any remaining content in the buffer (e.g. if stream ends before end_marker or newline)
        if buffer: # This includes if in_chart_config_block is true but no end_marker was found
            if in_chart_config_block: # Means block was not properly terminated
                 yield f"data: {json.dumps({'chunk': start_marker + chart_config_str + buffer})}" + "\n\n" # yield as text
            else:
                 yield f"data: {json.dumps({'chunk': buffer})}\n\n"

        yield f"data: {json.dumps({'end_of_stream': True})}\n\n"
    except openai.APIError as e:
        print(f"OpenAI API error during stream: {e}")
        err_msg = str(e)
        if hasattr(e, 'body') and isinstance(e.body, dict) and 'message' in e.body:
            err_msg = e.body['message']
        elif hasattr(e, 'message'):
             err_msg = e.message
        yield f"data: {json.dumps({'error': f'OpenAI API error: {err_msg}'})}\n\n"
    except Exception as e:
        print(f"Error during OpenAI stream: {e}")
        traceback.print_exc()
        yield f"data: {json.dumps({'error': 'An unexpected error occurred during the OpenAI stream.'})}\n\n"

def stream_perplexity(query, model_name):
    """Generator for streaming responses from Perplexity."""
    headers = {
        "Authorization": f"Bearer {perplexity_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" # Important for Perplexity streaming
    }

    # Enhanced System Prompt for Perplexity
    enhanced_perplexity_system_prompt = """You are Comet, an AI specializing in meticulous research, step-by-step reasoning, and precise code assistance.
Your goal is to provide accurate, detailed, and well-justified answers and code.

## Core Strengths:
*   **Meticulous Research:** Provide precise, current, and verifiable information.
*   **Step-by-Step Reasoning:** Clearly articulate the logic behind conclusions.
*   **Precise Code Assistance:** Offer accurate code snippets and explanations.

## Methodology:
1.  **Analyze & Deconstruct:** Understand requests, employing systematic reasoning.
2.  **Verify & Justify:** Use knowledge and web search for information, explaining your reasoning.
3.  **Elaborate & Code:** Offer comprehensive explanations and precise code where applicable.
4.  **Format (Markdown):** Use Markdown for clarity (headings, lists, code blocks).
5.  **Objectivity & Precision:** Focus on factual reporting and exactitude.
6.  **Acknowledge Limits:** Openly state if information or a solution is unavailable.

## Coding Guidelines:
*   Provide functional and clear code examples.
*   Explain the purpose and usage of the code.

## Core Protocols:
*   **Ethical Conduct:** No unethical, hateful, biased, illegal, or deceptive content/code.
*   **Privacy:** Do not use or request personal information.
*   **Focus:** Adhere to the research, reasoning, or coding task.
"""

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": enhanced_perplexity_system_prompt},
            {"role": "user", "content": query}
        ],
        "stream": True,
        "max_tokens": 10000, # Increased token limit for Perplexity
    }

    try:
        with requests.post(PERPLEXITY_API_URL, headers=headers, json=payload, stream=True) as response:
            response.raise_for_status() # Check for HTTP errors immediately
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data:'):
                        try:
                            # Remove 'data: ' prefix and parse JSON
                            data_str = decoded_line[len('data: '):]
                            if data_str.strip() == "[DONE]": # Perplexity specific DONE signal
                                yield f"data: {json.dumps({'end_of_stream': True})}\n\n"
                                break
                            data = json.loads(data_str)
                            # Extract content based on Perplexity stream structure
                            content = data.get('choices', [{}])[0].get('delta', {}).get('content')
                            if content:
                                yield f"data: {json.dumps({'chunk': content})}\n\n"
                        except json.JSONDecodeError:
                            print(f"Warning: Could not decode JSON from Perplexity stream: {decoded_line}")
                        except Exception as e:
                             print(f"Error processing Perplexity stream line: {decoded_line}, Error: {e}")
                             # Don't yield error here unless it's fatal, maybe just log

            # Check if loop finished without explicit DONE (might happen on errors before stream starts fully)
            # If no DONE signal was received, signal end manually if response was otherwise ok
            # yield f"data: {json.dumps({'end_of_stream': True})}\n\n"

    except requests.exceptions.RequestException as e:
        print(f"Perplexity API request failed: {e}")
        error_detail = str(e)
        if e.response is not None:
            try:
                # Try reading error from non-streaming response if possible
                error_json = e.response.json()
                error_detail = error_json.get('error', {}).get('message', str(e))
            except ValueError: # JSONDecodeError
                error_detail = e.response.text
            except Exception as inner_e:
                 print(f"Error reading error response: {inner_e}")
                 error_detail = e.response.text # Fallback
        yield f"data: {json.dumps({'error': f'Perplexity API error: {error_detail}'})}\n\n"
    except Exception as e:
        print(f"Error during Perplexity stream: {e}")
        traceback.print_exc()
        yield f"data: {json.dumps({'error': 'An unexpected error occurred during the Perplexity stream.'})}\\n\\n"

# --- Streaming Generator for OpenRouter ---
def stream_openrouter(query, model_name_with_suffix):
    """Generator for streaming responses from OpenRouter, using OpenAI's SDK."""
    if not openrouter_api_key:
        yield f"data: {json.dumps({'error': 'OpenRouter API key not configured.'})}\n\n"
        return

    # Model name for OpenRouter API might not include the ':free' suffix
    actual_model_name = model_name_with_suffix.split(':')[0]

    # Initialize a specific client for OpenRouter
    try:
        openrouter_client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_api_key
        )
    except Exception as e:
        print(f"Failed to initialize OpenRouter client: {e}")
        yield f"data: {json.dumps({'error': 'Failed to initialize OpenRouter client.'})}\n\n"
        return

    # Using a similar enhanced system prompt as OpenAI for consistency, can be customized
    enhanced_openrouter_system_prompt = """You are Comet, an advanced AI agent (via OpenRouter) specializing in deep research, logical reasoning, and code generation.
Your purpose is to deliver insightful, well-reasoned answers and functional code.

## Core Competencies:
*   **Deep Research:** Conduct thorough analysis and synthesize complex information.
*   **Logical Reasoning:** Deduce, infer, and evaluate information to form sound conclusions.
*   **Code Generation:** Create, explain, and troubleshoot code in various languages.

## Operational Approach:
1.  **Understand & Analyze:** Decipher query intent, complexities, and requirements.
2.  **Research & Reason:** Access knowledge and apply logical frameworks.
3.  **Develop & Explain:** Construct comprehensive explanations, generate code, and provide clear justifications.
4.  **Format Clearly (Markdown):** Utilize Markdown for optimal structure, readability, and presentation.
5.  **Maintain Integrity:** Ensure responses are accurate, objective, and helpful.
6.  **Acknowledge Limits:** Clearly state if a request is beyond current capabilities.

## Core Directives:
*   **Ethical Conduct:** No unethical, hateful, biased, or illegal content/code.
*   **Privacy:** Do not use or request personal information.
*   **Focus:** Address the user's research, reasoning, or coding query.
"""
    messages = [
        {"role": "system", "content": enhanced_openrouter_system_prompt},
        {"role": "user", "content": query}
    ]

    # Token limits might vary for OpenRouter free models; using a general default or find specific ones
    # For "microsoft/phi-4-reasoning-plus", context length is high, output might be less constrained by typical free limits
    # Setting a generous max_tokens for now, but this might need adjustment based on specific model behavior.
    # OpenRouter itself might enforce limits.
    max_tokens = 8000 # A reasonable default, adjust if needed

    api_params = {
        "model": actual_model_name,
        "messages": messages,
        "stream": True,
        "max_completion_tokens": max_tokens, # Note: OpenRouter uses max_tokens in some contexts
                                         # but OpenAI SDK uses max_completion_tokens.
                                         # The OpenAI SDK will likely handle this.
    }

    try:
        print(f"Calling OpenRouter (via OpenAI SDK) with params: {{'model': {actual_model_name}, 'messages': ...}}")
        stream = openrouter_client.chat.completions.create(**api_params)
        buffer = ""
        # Chart extraction logic is kept from OpenAI for now, can be removed if not applicable to OpenRouter models
        in_chart_config_block = False
        chart_config_str = ""

        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is not None:
                buffer += content
                # Chart extraction logic (can be removed if OpenRouter models don't use this format)
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
                            yield f"data: {json.dumps({'chunk': start_marker + chart_config_str + end_marker})}" + "\n\n"
                        buffer = post_block_content
                        in_chart_config_block = False
                        chart_config_str = ""
                    else:
                        chart_config_str += buffer
                        buffer = ""
                
                if not in_chart_config_block and buffer:
                    if "\\n" in buffer or len(buffer) > 80:
                        yield f"data: {json.dumps({'chunk': buffer})}\n\n"
                        buffer = ""

        if buffer:
            if in_chart_config_block:
                 yield f"data: {json.dumps({'chunk': start_marker + chart_config_str + buffer})}" + "\n\n"
            else:
                 yield f"data: {json.dumps({'chunk': buffer})}\n\n"

        yield f"data: {json.dumps({'end_of_stream': True})}\n\n"
    except openai.APIError as e: # Catching OpenAI specific errors as we use that SDK
        print(f"OpenRouter API error (via OpenAI SDK): {e}")
        err_msg = str(e)
        if hasattr(e, 'body') and isinstance(e.body, dict) and 'message' in e.body:
            err_msg = e.body['message']
        elif hasattr(e, 'message'):
             err_msg = e.message
        yield f"data: {json.dumps({'error': f'OpenRouter API error: {err_msg}'})}\n\n"
    except Exception as e:
        print(f"Error during OpenRouter stream: {e}")
        traceback.print_exc()
        yield f"data: {json.dumps({'error': 'An unexpected error occurred during the OpenRouter stream.'})}\n\n"

# --- Streaming Generator for Gemini ---
def stream_gemini(query, model_name):
    """Generator for streaming responses from Gemini."""
    actual_model_id = MODEL_ID_MAPPING.get(model_name, model_name)

    if not gemini_api_key:
        yield f"data: {json.dumps({'error': 'Gemini API key not configured.'})}\n\n"
        return

    try:
        model = genai.GenerativeModel(actual_model_id)
        
        enhanced_gemini_system_prompt = """You are Comet, a highly advanced AI (Gemini), functioning as an unparalleled intelligence for research, reasoning, and coding.
Your objective is to deliver comprehensive, precise, insightful answers, and robust code solutions.

## Core Capabilities:
*   **Profound Research:** Synthesize complex information with depth and accuracy.
*   **Sophisticated Reasoning:** Employ advanced logic to analyze and derive conclusions.
*   **Advanced Coding:** Generate, debug, and explain code across multiple languages.

## Operational Modus:
1.  **Deconstruct & Understand:** Meticulously analyze queries for intent, assumptions, and technical requirements.
2.  **Synthesize & Reason:** Integrate knowledge (internal, search) and apply logical frameworks for accurate, well-supported outcomes. Cite sources.
3.  **Develop & Articulate:** Formulate thorough explanations and generate high-quality code, clearly articulating the rationale.
4.  **Format (Markdown):** Use Markdown for optimal structure (headings, lists, code blocks, tables).
5.  **Professionalism & Accuracy:** Be helpful, exact, objective, and ensure technical correctness.
6.  **Acknowledge Boundaries:** Clearly state limitations in knowledge or capability.

## Coding Principles:
*   Deliver well-structured, efficient, and commented code.
*   Specify languages, dependencies, and execution environments.
*   Provide clear explanations of algorithms and design choices.

## Core Directives:
*   **Ethical Conduct:** No unethical, hateful, discriminatory, illegal, or misleading content/code.
*   **Privacy:** Do not solicit or use personal information.
*   **Focus:** Address the user's research, reasoning, or coding query.
"""
        
        full_prompt = f"{enhanced_gemini_system_prompt}\n\nUser Query: {query}"

        # Define the Google Search tool
        # Using the simpler string-based tool enabling for now
        # google_search_tool = Tool(google_search_retrieval={}) 

        print(f"Calling Gemini's generate_content with model: {actual_model_id} (Search Grounding Disabled for now)") # Updated log
        
        # Configure generation settings for Gemini
        gen_config = None
        if actual_model_id == "models/gemini-2.5-pro-exp-03-25":
            print(f"Applying GenerationConfig with max_output_tokens=65536 for {actual_model_id}")
            gen_config = GenerationConfig(max_output_tokens=65536)

        response_stream = model.generate_content(
            full_prompt, 
            stream=True, 
            generation_config=gen_config
            # tools='google_search_retrieval' # Simpler string form - REMOVED to disable grounding
        )

        for chunk in response_stream:
            if chunk.prompt_feedback and chunk.prompt_feedback.block_reason:
                reason_enum = chunk.prompt_feedback.block_reason
                reason_name = reason_enum.name if hasattr(reason_enum, 'name') else str(reason_enum)
                error_msg = f'Content generation issue: {reason_name} (prompt feedback).'
                print(f"Gemini stream error: {error_msg}")
                yield f"data: {json.dumps({'error': error_msg})}\n\n"
                yield f"data: {json.dumps({'end_of_stream': True, 'status': 'blocked_prompt'})}\n\n"
                return

            if not chunk.candidates:
                print("Gemini stream: Chunk received with no candidates.")
                continue

            for candidate_obj in chunk.candidates:
                if candidate_obj.finish_reason == 3: # SAFETY
                    error_msg = 'Content generation stopped: SAFETY. The response may have contained sensitive or harmful content.'
                    # Consider logging candidate_obj.safety_ratings for more details
                    print(f"Gemini stream error: {error_msg}")
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
                    yield f"data: {json.dumps({'end_of_stream': True, 'status': 'blocked_safety'})}\n\n"
                    return # Stop streaming for this request
                elif candidate_obj.finish_reason == 4: # RECITATION
                    error_msg = 'Content generation stopped: RECITATION. The response was too similar to existing content.'
                    print(f"Gemini stream error: {error_msg}")
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
                    yield f"data: {json.dumps({'end_of_stream': True, 'status': 'blocked_recitation'})}\n\n"
                    return # Stop streaming for this request
                
                if candidate_obj.content and candidate_obj.content.parts:
                    for part in candidate_obj.content.parts:
                        if hasattr(part, 'text') and part.text:
                            yield f"data: {json.dumps({'chunk': part.text})}\n\n"

        yield f"data: {json.dumps({'end_of_stream': True, 'status': 'completed'})}\n\n"

    except genai.types.BlockedPromptException as e:
        print(f"Gemini API BlockedPromptException: {e}")
        yield f"data: {json.dumps({'error': f'Your prompt was blocked by the API. {str(e)}'})}\n\n"
        yield f"data: {json.dumps({'end_of_stream': True, 'status': 'blocked_prompt_exception'})}\n\n"
    except genai.types.StopCandidateException as e:
        print(f"Gemini API StopCandidateException: {e}") # Should be handled by finish_reason generally
        yield f"data: {json.dumps({'error': f'Content generation stopped unexpectedly. {str(e)}'})}\n\n"
        yield f"data: {json.dumps({'end_of_stream': True, 'status': 'stopped_candidate_exception'})}\n\n"
    except Exception as e:
        print(f"Error during Gemini stream: {e}")
        traceback.print_exc()
        # Try to get a more specific error message if available
        error_message = str(e)
        if hasattr(e, 'message'): # Some specific API errors might have this
             error_message = e.message
        yield f"data: {json.dumps({'error': f'Gemini API error: {error_message}'})}\n\n"

# --- Routes --- 
@app.route('/')
def index():
    """Renders the main search page."""
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    """Handles the search query, returning a stream for text or JSON for image."""
    print("--- Request received at /search endpoint ---") # Log Route Entry
    query = request.json.get('query')
    selected_model = request.json.get('model')

    # Basic validation
    if not query:
        # For non-streaming error before choice
        return jsonify({'error': 'No query provided'}), 400
    
    if not selected_model or selected_model not in ALLOWED_MODELS:
        print(f"Warning: Invalid or missing model '{selected_model}'. Defaulting to sonar-pro.")
        selected_model = "sonar-pro" # Defaulting is safer than erroring pre-stream

    missing_keys = check_api_keys(selected_model)
    if missing_keys:
        key_str = " and ".join(missing_keys)
        print(f"Error: Missing API Key(s) {key_str} for model {selected_model}")
        # Return non-streaming error before choice
        return jsonify({'error': f'Missing API key(s) in .env file for model {selected_model}: {key_str}'}), 500

    print(f"Received query: {query}, Model: {selected_model}")

    # --- Route to Image or Text Streaming --- 
    if selected_model == "gpt-image-1":
        return generate_image(query)
    else:
        is_standard_openai_text_model = (
            selected_model.startswith('gpt-') or 
            selected_model == "o4-mini-2025-04-16" or 
            selected_model == "o3-2025-04-16"
        )
        if is_standard_openai_text_model:
            generator = stream_openai(query, selected_model)
        elif selected_model.startswith('gemini-'):
            generator = stream_gemini(query, selected_model)
        elif selected_model in OPENROUTER_MODELS: # Routing for all OpenRouter models
            generator = stream_openrouter(query, selected_model)
        else:
            generator = stream_perplexity(query, selected_model)
        return Response(generator, mimetype='text/event-stream')

# --- Image Generation Function ---
def generate_image(query):
    """Generates an image using OpenAI and returns base64 data or error."""
    print("--- Entering generate_image function ---") # Log Entry
    if not openai_client:
         # Return standard JSON response for image errors
         print("ERROR: generate_image - OpenAI client not initialized.") # Log Error
         return jsonify({'error': 'OpenAI client not initialized. Check API key.'}), 500

    print(f"Generating image with prompt: {query[:100]}...")
    try:
        result = openai_client.images.generate(
            model="gpt-image-1",
            prompt=query,
            size="1024x1024"
        )
        
        if result.data and result.data[0].b64_json:
            image_base64 = result.data[0].b64_json
            print("SUCCESS: generate_image - Image generated, returning JSON.") # Log Success
            return jsonify({'image_base64': image_base64})
        else:
            print("ERROR: generate_image - No image data received from OpenAI.") # Log Error
            return jsonify({'error': 'No image data received from OpenAI.'}), 500

    except openai.APIError as e:
        print(f"ERROR: generate_image - OpenAI APIError caught: {e}") # Log Specific Error
        err_msg = str(e)
        # Attempt to extract more specific error message if available
        if hasattr(e, 'body') and isinstance(e.body, dict) and 'message' in e.body:
            err_msg = e.body['message']
        elif hasattr(e, 'message'):
            err_msg = e.message
        return jsonify({'error': f'OpenAI API error: {err_msg}'}), 500
    except Exception as e:
        print(f"ERROR: generate_image - Unexpected Exception caught: {e}") # Log Specific Error
        traceback.print_exc()
        return jsonify({'error': 'An internal server error occurred during image generation.'}), 500

# --- xAI Image Generation Function (New) --- DELETED
# def generate_xai_image(query):
#     ...

# --- Main Execution --- 
if __name__ == '__main__':
    # Startup checks remain the same
    if not openai_client and not perplexity_api_key and not openrouter_api_key and not gemini_api_key: # Updated check for all major keys
         print("\n*** WARNING: No API keys (OpenAI, Perplexity, OpenRouter, Gemini) found in .env ***")
         print("Please add at least one API key to the .env file and restart.\n")
    else:
        if not openai_client:
             print("\n*** WARNING: OpenAI API key not found in .env. OpenAI models will not work. ***\n")
        if not perplexity_api_key:
             print("\n*** WARNING: Perplexity API key not found in .env. Perplexity models will not work. ***\n")
        if not gemini_api_key:
             print("\n*** WARNING: Gemini API key not found in .env. Gemini models will not work. ***\n")
        if not openrouter_api_key:
             print("\n*** WARNING: OpenRouter API key not found in .env. OpenRouter models will not work. ***\n")
        # if not xai_api_key: # Removed xAI key warning
        #      print("\n*** WARNING: xAI API key not found in .env. Grok models will not work. ***\n")

    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), threaded=True) 