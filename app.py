import os
import json
import openai
import requests # For Perplexity API
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

# --- API Clients (Optional but good practice) ---
# Initialize OpenAI client (recommended way)
openai_client = openai.OpenAI() if openai.api_key else None

# Perplexity API endpoint
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

# Allowed models (add more as needed and update frontend)
ALLOWED_MODELS = {
    # Perplexity
    "sonar-pro",
    # "sonar-deep-research", # Removed
    "sonar-reasoning-pro",
    # OpenAI
    "gpt-4.1", 
    "o4-mini-2025-04-16",
    "o3-2025-04-16",
    "gpt-4o-search-preview-2025-03-11",
    "gpt-image-1", # Image Model
}

# --- Error Handling --- 
def check_api_keys(model_name):
    """Checks if the necessary API key for the selected model is loaded."""
    # Check if it's an OpenAI model (standard prefix or specific custom names)
    is_openai_model = (
        model_name.startswith('gpt-') or 
        model_name == "o4-mini-2025-04-16" or 
        model_name == "o3-2025-04-16" or
        model_name == "gpt-4o-search-preview-2025-03-11" or
        model_name == "gpt-image-1"
    )
    
    if is_openai_model:
        if not openai.api_key or not openai_client: # Also check client initialization
            return ["OpenAI"]
    else: # Assuming Perplexity otherwise
        if not perplexity_api_key:
            return ["Perplexity"]
    return [] # No missing keys for the selected model type

# --- Streaming Generators --- 

def stream_openai(query, model_name):
    """Generator for streaming responses from OpenAI."""
    if not openai_client:
        yield f"data: {json.dumps({'error': 'OpenAI client not initialized. Check API key.'})}\n\n"
        return

    # --- Prepare API Call Parameters ---
    api_params = {
        "model": model_name,
        "messages": [
            # System prompt might need adjustment depending on how the model uses search
            {"role": "system", "content": "You are a helpful and meticulous AI assistant. Think step-by-step to deeply understand the query. Provide a comprehensive and well-reasoned answer. **Always format your entire response using Markdown.** If relevant, use web search results to provide up-to-date information."},
            {"role": "user", "content": query}
        ],
        "stream": True,
        "max_completion_tokens": 10000, 
    }

    try:
        print(f"Calling chat.completions.create with params: {api_params}")
        stream = openai_client.chat.completions.create(**api_params)
        
        for chunk in stream:
            # TODO: Need to inspect chunk structure if tools are used
            # It might contain tool_calls instead of/in addition to delta.content
            # For now, assume standard content streaming
            content = chunk.choices[0].delta.content
            if content is not None:
                # Send chunk data formatted as SSE
                yield f"data: {json.dumps({'chunk': content})}\n\n"
        # Signal end of stream (optional, but good practice)
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
    payload = {
        "model": model_name,
        "messages": [
            # Using a similar reasoning prompt for Perplexity
            {"role": "system", "content": "You are a precise and thorough AI assistant. Reason step-by-step about the user query to provide an accurate and detailed response. **Always format your entire response using Markdown.**"},
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
        yield f"data: {json.dumps({'error': 'An unexpected error occurred during the Perplexity stream.'})}\n\n"

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
        # Determine if it's standard OpenAI text or Perplexity text
        is_standard_openai_text_model = (
            selected_model.startswith('gpt-') or 
            selected_model == "o4-mini-2025-04-16" or 
            selected_model == "o3-2025-04-16"
            # Exclude image and search models handled above
        )
        # Handle potentially removed non-streaming perplexity models if needed
        # elif selected_model == "sonar-deep-research": 
        #     return generate_perplexity_non_streaming(query, selected_model)

        if is_standard_openai_text_model:
            generator = stream_openai(query, selected_model)
        else: # Assume Perplexity model (including sonar-deep-research)
            generator = stream_perplexity(query, selected_model)
        
        # Return the streaming response for text models
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

# --- Main Execution --- 
if __name__ == '__main__':
    # Startup checks remain the same
    if not openai_client and not perplexity_api_key:
         print("\n*** WARNING: Neither OpenAI nor Perplexity API key found in .env ***")
         print("Please add at least one API key to the .env file and restart.\n")
    elif not openai_client:
         print("\n*** WARNING: OpenAI API key not found in .env. OpenAI models will not work. ***\n")
    elif not perplexity_api_key:
         print("\n*** WARNING: Perplexity API key not found in .env. Perplexity models will not work. ***\n")

    app.run(debug=True, threaded=True) # Added threaded=True, often helpful for streaming 