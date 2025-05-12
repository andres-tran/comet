import os
import json
import openai
import base64
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
import traceback

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
    "x-ai/grok-3-mini-beta:online",
    "x-ai/grok-3-beta:online",
    "anthropic/claude-3.7-sonnet",
    "anthropic/claude-3.7-sonnet:thinking",
    "openai/gpt-4o-2024-11-20:online",
    "openai/gpt-4.1",
    "perplexity/sonar-reasoning-pro",
    "openai/gpt-4o-search-preview",
    "openai/gpt-4.5-preview",
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
def stream_openrouter(query, model_name_with_suffix, reasoning_config=None):
    """Generator for responses from OpenRouter.
    Uses streaming for all OpenRouter models.
    Accepts an optional reasoning_config dictionary.
    """
    if not openrouter_api_key:
        yield f"data: {json.dumps({'error': 'OpenRouter API key not configured.'})}\n\n"
        return

    enhanced_openrouter_system_prompt = "You are Comet, a helpful and fun AI agent."
    messages = [
        {"role": "system", "content": enhanced_openrouter_system_prompt},
        {"role": "user", "content": query}
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
    elif actual_model_name_for_sdk == "openai/gpt-4.1": # Stated 32,768 generation capacity
        max_tokens_val = 32768
    elif actual_model_name_for_sdk == "openai/gpt-4o-search-preview": # Stated 16,384 generation capacity
        max_tokens_val = 16384
    elif actual_model_name_for_sdk == "openai/gpt-4.5-preview": # Stated 16,384 generation capacity
        max_tokens_val = 16384
    # For other models, max_tokens_val remains the default of 30000

    sdk_params = {
        "model": actual_model_name_for_sdk,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens_val
    }

    extra_body_params = {}
    # If reasoning_config is passed (e.g. for :thinking models with exclude: True)
    if reasoning_config:
        extra_body_params["reasoning"] = reasoning_config

    # Add web_search_options for specific models
    if actual_model_name_for_sdk == "openai/gpt-4.1":
        extra_body_params["web_search_options"] = {"search_context_size": "high"}

    try:
        print(f"Calling OpenRouter for {actual_model_name_for_sdk}. Reasoning: {reasoning_config}. Extra Body: {extra_body_params}")
        stream = openrouter_client_instance.chat.completions.create(**sdk_params, extra_body=extra_body_params)
        buffer = ""
        in_chart_config_block = False
        chart_config_str = ""
        content_received_from_openrouter = False # Flag to track content

        for chunk in stream:
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
        print(f"OpenRouter API error (streaming for {model_name_with_suffix}): {e}")
        err_msg = str(e)
        if hasattr(e, 'body') and isinstance(e.body, dict) and 'message' in e.body:
            err_msg = e.body['message']
        elif hasattr(e, 'message'):
             err_msg = e.message
        yield f"data: {json.dumps({'error': f'OpenRouter API error: {err_msg}'})}\n\n"
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

    if not query:
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
        return generate_image(query)
    elif selected_model in OPENROUTER_MODELS:
        reasoning_config_to_pass = None # Initialize
        if selected_model.endswith(':thinking'):
            print(f"Model {selected_model} is a :thinking model. Setting default reasoning_config with exclude:True.")
            reasoning_config_to_pass = {"effort": "high", "exclude": True}
        generator = stream_openrouter(query, selected_model, reasoning_config_to_pass)
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
        err_msg = str(e)
        if hasattr(e, 'body') and isinstance(e.body, dict) and 'message' in e.body:
            err_msg = e.body['message']
        elif hasattr(e, 'message'):
            err_msg = e.message
        return jsonify({'error': f'OpenAI API error: {err_msg}'}), 500
    except Exception as e:
        print(f"ERROR: generate_image - Unexpected Exception caught: {e}")
        traceback.print_exc()
        return jsonify({'error': 'An internal server error occurred during image generation.'}), 500

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