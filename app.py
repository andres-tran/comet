import os
import json
import openai
import requests # For Perplexity API
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
    "sonar-deep-research",
    "sonar-reasoning-pro",
    "codellama-70b-instruct",
    # OpenAI
    "gpt-4.1",
    "o4-mini-2025-04-16",
    "o3-2025-04-16",
}

# --- Error Handling --- 
def check_api_keys(model_name):
    """Checks if the necessary API key for the selected model is loaded."""
    # Check if it's an OpenAI model (standard prefix or specific custom names)
    is_openai_model = (
        model_name.startswith('gpt-') or 
        model_name == "o4-mini-2025-04-16" or 
        model_name == "o3-2025-04-16"
    )
    
    if is_openai_model:
        if not openai.api_key:
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

    try:
        stream = openai_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a helpful and meticulous AI assistant. Think step-by-step to deeply understand the query. Provide a comprehensive and well-reasoned answer. **Always format your entire response using Markdown.**"},
                {"role": "user", "content": query}
            ],
            stream=True,
            max_completion_tokens=2048, # Correct parameter for OpenAI completion length
        )
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is not None:
                # Send chunk data formatted as SSE
                yield f"data: {json.dumps({'chunk': content})}\n\n"
        # Signal end of stream (optional, but good practice)
        yield f"data: {json.dumps({'end_of_stream': True})}\n\n"

    except openai.APIError as e:
        print(f"OpenAI API error during stream: {e}")
        err_msg = str(e)
        if hasattr(e, 'body') and e.body and 'message' in e.body:
            err_msg = e.body['message']
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
            {"role": "system", "content": "You are a precise and thorough AI assistant. Reason step-by-step about the user query to provide an accurate and detailed response. **Always format your entire response using Markdown.**"},
            {"role": "user", "content": query}
        ],
        "stream": True,
        "max_tokens": 2048, # Allow longer responses
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
    """Handles the search query, returning a Server-Sent Event stream."""
    query = request.json.get('query')
    selected_model = request.json.get('model')

    # Basic validation (can be done before streaming starts)
    if not query:
        # Cannot easily return JSON error in streaming context, log and return empty stream or signal error
        print("Error: No query provided")
        def error_stream(): yield f"data: {json.dumps({'error': 'No query provided'})}\n\n"
        return Response(error_stream(), mimetype='text/event-stream')

    if not selected_model or selected_model not in ALLOWED_MODELS:
        print(f"Warning: Invalid or missing model '{selected_model}'. Defaulting to sonar-pro.")
        selected_model = "sonar-pro"

    missing_keys = check_api_keys(selected_model)
    if missing_keys:
        key_str = " and ".join(missing_keys)
        print(f"Error: Missing API Key(s) {key_str}")
        def error_stream_keys(): yield f"data: {json.dumps({'error': f'Missing API key(s) in .env file for model {selected_model}: {key_str}'})}\n\n"
        return Response(error_stream_keys(), mimetype='text/event-stream')

    print(f"Received query: {query}, Model: {selected_model}")

    # --- Choose the appropriate streaming generator ---
    # Check if it's an OpenAI model (standard prefix or specific custom names)
    is_openai_model_route = (
        selected_model.startswith('gpt-') or 
        selected_model == "o4-mini-2025-04-16" or 
        selected_model == "o3-2025-04-16"
    )

    if is_openai_model_route:
        generator = stream_openai(query, selected_model)
    else:
        generator = stream_perplexity(query, selected_model)

    # Return the streaming response
    return Response(generator, mimetype='text/event-stream')

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