import os
import json
import openai
import base64
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
import traceback
import io # Added for image editing

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure API keys
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY") # For direct OpenAI (e.g., gpt-image-1)

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

# --- Streaming Generator for OpenRouter ---
def stream_openrouter(query, model_name_with_suffix, reasoning_config=None, uploaded_file_data=None, file_type=None):
    """Generator for responses from OpenRouter.
    Uses streaming for all OpenRouter models.
    Accepts an optional reasoning_config dictionary.
    Accepts optional uploaded_file_data (base64 data URL) and file_type ('image' or 'pdf').
    """
    if not openrouter_api_key:
        yield f"data: {json.dumps({'error': 'OpenRouter API key not configured.'})}\n\n"
        return

    # Improved system prompt for better responses
    enhanced_openrouter_system_prompt = (
        "You are Comet, an expert, friendly, and detail-oriented AI assistant. "
        "Always provide clear, accurate, and actionable answers. "
        "When appropriate, show your reasoning step by step, and ask clarifying questions if the user's request is ambiguous. "
        "Format your responses for readability, using lists, headings, and code blocks as needed."
    )
    
    user_content_parts = [{"type": "text", "text": query}]

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
        "temperature": 0.7,  # More creative, but not too random
        "top_p": 0.95        # Encourage diversity
    }

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
        stream = openrouter_client_instance.chat.completions.create(**sdk_params, extra_body=extra_body_params)
        buffer = ""
        in_chart_config_block = False
        chart_config_str = ""
        content_received_from_openrouter = False # Flag to track content

        for chunk in stream:
            print(f"Debug: Raw chunk for {actual_model_name_for_sdk}: {chunk}")
            delta = chunk.choices[0].delta
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

    # Default query to "edit image" if not provided but an image is for editing
    if not query and selected_model == "gpt-image-1" and uploaded_file_data and file_type == 'image':
        query = "Perform edits based on the prompt, or a general enhancement if no specific edit prompt."

    if not query: # Now check query after potential default
        return jsonify({'error': 'No query provided'}), 400
    
    default_model_for_error = "openai/gpt-4o:online"
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
            file_type=file_type
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

# --- Main Execution --- 
if __name__ == '__main__':
    if not openrouter_api_key:
         print("\n*** WARNING: OpenRouter API key not found in .env. OpenRouter models will not work. ***\n")
    else:
        print("\nOpenRouter API key found.\n")

    if not openai_api_key:
         print("\n*** WARNING: Direct OpenAI API key (OPENAI_API_KEY) not found in .env. gpt-image-1 model will not work. ***\n")
    else:
        print("Direct OpenAI API key (OPENAI_API_KEY) found.\n")

    if openrouter_api_key or openai_api_key:
        print("Application starting...\n")
    else:
        print("\n*** CRITICAL WARNING: NO API keys (OpenRouter or direct OpenAI) found in .env. Application will likely not function. ***\n")
        
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), threaded=True) 