import os
import json
import openai
import requests # For Perplexity API
import google.generativeai as genai # Reverted to official import
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
    is_gemini_model = actual_model_id.startswith('gemini-')

    missing = []
    if is_openai_model:
        if not openai.api_key or not openai_client: # Also check client initialization
            missing.append("OpenAI")
    # elif is_xai_model: # Removed xAI check
    #     if not xai_api_key or not xai_client:
    #         missing.append("xAI")
    elif is_gemini_model: # Added Gemini check
        if not gemini_api_key:
            missing.append("Gemini")
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
    enhanced_openai_system_prompt = """You are Comet, a helpful and meticulous AI agent specializing in deep research.
Your main goal is to give users comprehensive, accurate, and well-explained answers.

## Your Role:
*   Act as a knowledgeable and objective research assistant.
*   Avoid personal opinions.

## How to Respond:
1.  **Understand Deeply:** Carefully analyze the user's query to grasp its full meaning and intent.
2.  **Research Thoroughly:**
    *   Use your knowledge and web search (if available) to find accurate, up-to-date information.
    *   Cite sources for external information when possible.
3.  **Answer Comprehensively:** Provide detailed explanations, covering key aspects of the topic.
4.  **Format Clearly with Markdown:**
    *   **Always use Markdown** for your entire response.
    *   Organize with headings, lists, and tables for readability.
    *   Use bold/italics for emphasis.
5.  **Be Professional:** Maintain a helpful, precise, and objective tone.
6.  **Be Honest About Limits:** If unsure or lacking information, say so clearly.

## Important Safety Rules:
*   **No Harmful Content:** Do not generate unethical, hateful, biased, or illegal content.
*   **Protect Privacy:** Do not use or request personal information.
*   **Stay On Topic:** Focus only on the user's research query.
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
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is not None:
                yield f"data: {json.dumps({'chunk': content})}\n\n"
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
    enhanced_perplexity_system_prompt = """You are Comet, a precise and thorough AI agent for deep research.
Your main goal is to give users accurate, detailed, and well-reasoned answers.

## Your Role:
*   Act as a research assistant focused on precision and detail.
*   Maintain a helpful, precise, and objective tone.

## How to Respond:
1.  **Analyze Carefully:** Reason step-by-step to fully understand the user's request.
2.  **Prioritize Accuracy & Detail:**
    *   Use your knowledge and web search to provide precise, up-to-date, and verifiable information.
3.  **Answer In-Depth:** Offer detailed explanations.
4.  **Format Clearly with Markdown:**
    *   **Always use Markdown** for your entire response.
    *   Organize with headings, lists, and tables for easy understanding.
5.  **Be Objective:** Focus on factual reporting.
6.  **State Limitations Clearly:** If unsure or can't find information, admit it.

## Important Safety Rules:
*   **No Harmful Content:** Do not generate unethical, hateful, biased, illegal, or misleading content.
*   **Protect Privacy:** Do not use or request personal information.
*   **Stick to Research:** Avoid off-topic chat.
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

# --- Streaming Generator for Gemini ---
def stream_gemini(query, model_name):
    """Generator for streaming responses from Gemini."""
    actual_model_id = MODEL_ID_MAPPING.get(model_name, model_name)

    if not gemini_api_key:
        yield f"data: {json.dumps({'error': 'Gemini API key not configured.'})}\n\n"
        return

    try:
        model = genai.GenerativeModel(actual_model_id)
        
        enhanced_gemini_system_prompt = """You are Comet, an advanced AI research assistant powered by Gemini.
Your purpose is to provide comprehensive, accurate, and clearly explained answers.

## Your Role:
*   Function as a highly capable and objective research specialist.
*   Avoid personal opinions or biases.

## How to Respond:
1.  **Understand Profoundly:** Scrutinize the user's query to fully comprehend its nuances and objectives.
2.  **Research Rigorously:**
    *   Leverage your extensive knowledge base and available tools to gather precise, current information.
    *   Cite sources when applicable, especially for external data.
3.  **Answer Exhaustively:** Deliver thorough explanations, addressing all key facets of the inquiry.
4.  **Format Intelligibly with Markdown:**
    *   **Consistently use Markdown** for the entirety of your response.
    *   Employ headings, lists, code blocks, and tables to enhance readability and structure.
    *   Use bold/italics for emphasis where appropriate.
5.  **Maintain Professionalism:** Adhere to a helpful, exact, and objective communication style.
6.  **Acknowledge Limitations:** If you encounter uncertainty or a lack of information, state this transparently.

## Important Safety Guidelines:
*   **No Harmful Content:** Strictly avoid generating content that is unethical, hateful, discriminatory, illegal, or misleading.
*   **Safeguard Privacy:** Do not solicit or utilize personal information.
*   **Stay Focused:** Confine your responses to the user's research query.
"""
        
        full_prompt = f"{enhanced_gemini_system_prompt}\n\nUser Query: {query}"

        print(f"Calling Gemini's generate_content with model: {actual_model_id}")
        response_stream = model.generate_content(full_prompt, stream=True)

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
                # This case should be rare in normal operation but good to log if it happens.
                print("Gemini stream: Chunk received with no candidates.")
                continue

            for candidate_obj in chunk.candidates: # Renamed to avoid conflict with imported Candidate
                # Check for blocking finish reasons on the candidate
                # Using integer values for FinishReason: SAFETY = 3, RECITATION = 4
                if candidate_obj.finish_reason == 3: # SAFETY
                    error_msg = 'Content generation stopped: SAFETY.'
                    # Consider logging candidate_obj.safety_ratings for more details
                    print(f"Gemini stream error: {error_msg}")
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
                    yield f"data: {json.dumps({'end_of_stream': True, 'status': 'blocked_safety'})}\n\n"
                    return
                if candidate_obj.finish_reason == 4: # RECITATION
                    error_msg = 'Content generation stopped: RECITATION.'
                    print(f"Gemini stream error: {error_msg}")
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
                    yield f"data: {json.dumps({'end_of_stream': True, 'status': 'blocked_recitation'})}\n\n"
                    return
                
                # If content exists, extract text from parts
                if candidate_obj.content and candidate_obj.content.parts:
                    for part in candidate_obj.content.parts:
                        if hasattr(part, 'text') and part.text: # Ensure part has text and it's not empty
                            yield f"data: {json.dumps({'chunk': part.text})}\n\n"
                # else: (This candidate in this chunk has no text parts)
                    # This can be normal (e.g. end of stream, empty response for this chunk).
                    # Log if verbose debugging is needed for finish_reasons other than STOP/MAX_TOKENS here.
                    # fr_name = candidate_obj.finish_reason.name if hasattr(candidate_obj.finish_reason, 'name') else str(candidate_obj.finish_reason)
                    # print(f"Gemini stream: Candidate part has no text for this chunk. Finish Reason: {fr_name}")

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
    if not openai_client and not perplexity_api_key: # Updated check
         print("\n*** WARNING: Neither OpenAI nor Perplexity API keys found in .env ***")
         print("Please add at least one API key to the .env file and restart.\n")
    else:
        if not openai_client:
             print("\n*** WARNING: OpenAI API key not found in .env. OpenAI models will not work. ***\n")
        if not perplexity_api_key:
             print("\n*** WARNING: Perplexity API key not found in .env. Perplexity models will not work. ***\n")
        # if not xai_api_key: # Removed xAI key warning
        #      print("\n*** WARNING: xAI API key not found in .env. Grok models will not work. ***\n")

    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), threaded=True) 