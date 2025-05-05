document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('search-form');
    const input = document.getElementById('search-input');
    const modelSelect = document.getElementById('model-select'); // Get the select element
    const resultsContainer = document.getElementById('results-container');
    const errorContainer = document.getElementById('error-container');
    const thinkingIndicator = document.querySelector('.thinking-indicator'); // Get thinking indicator

    // Configure marked.js (optional: customize options here if needed)
    // marked.setOptions({...});

    form.addEventListener('submit', async (event) => {
        event.preventDefault();

        const query = input.value.trim();
        const selectedModel = modelSelect.value;

        if (!query) {
            displayError("Please enter a search query.");
            return;
        }

        // Reset UI states
        resultsContainer.style.display = 'block';
        resultsContainer.innerHTML = ''; // Clear previous results immediately
        thinkingIndicator.style.display = 'flex'; // Show thinking animation
        // Clear placeholder explicitly if it exists
        const placeholder = resultsContainer.querySelector('.placeholder-text');
        if (placeholder) placeholder.remove();
        resultsContainer.classList.remove('error'); // Remove error class if present
        errorContainer.style.display = 'none';
        errorContainer.textContent = '';

        let accumulatedResponse = "";
        let currentError = null;

        try {
            const response = await fetch('/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query: query, model: selectedModel }),
            });

            if (!response.ok) {
                // Handle immediate HTTP errors (e.g., 404, 500 before streaming starts)
                let errorMessage = `Error: ${response.status} ${response.statusText}`;
                try {
                    // Try to get error from body if available
                    const errorData = await response.json(); // Non-streaming error response
                    errorMessage = errorData.error || errorMessage;
                } catch (e) { /* Ignore if body isn't JSON */ }
                throw new Error(errorMessage);
            }

            // --- Process the Stream --- 
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            // resultsContainer.innerHTML = ''; // Cleared earlier
            let isFirstChunk = true; // Flag to track the first data arrival

            while (true) {
                const { value, done } = await reader.read();
                if (done) {
                    console.log('Stream finished.');
                    break; // Exit loop when stream is done
                }

                const sseMessages = decoder.decode(value, { stream: true }).split('\n\n');

                sseMessages.forEach(message => {
                    if (message.trim().length === 0) return; // Skip empty messages

                    if (message.startsWith('data:')) {
                        const jsonData = message.substring(5).trim(); // Remove 'data: '
                        try {
                            const data = JSON.parse(jsonData);

                            // Hide thinking indicator on first valid data/error
                            if (isFirstChunk) {
                                thinkingIndicator.style.display = 'none';
                                isFirstChunk = false;
                            }

                            if (data.error) {
                                console.error("Error from stream:", data.error);
                                currentError = data.error; // Store the error
                                // Stop processing further chunks on error
                                reader.cancel('Error received'); // Optional: signal cancellation
                                return; // Exit forEach loop
                            }

                            if (data.chunk) {
                                accumulatedResponse += data.chunk;
                                // Render Markdown
                                resultsContainer.innerHTML = marked.parse(accumulatedResponse);
                            }

                            if (data.end_of_stream) {
                                console.log('End of stream signal received.');
                                // No need to break here, the reader.read() loop will handle 'done'
                            }

                        } catch (e) {
                            console.error('Failed to parse SSE data:', jsonData, e);
                            // Decide how to handle parse errors, maybe display a message
                            currentError = 'Error parsing response stream.';
                            reader.cancel('Parse error');
                            return;
                        }
                    } else {
                        console.warn("Received non-SSE formatted message:", message);
                    }
                });
                 // If an error was detected inside the loop, break the outer while loop
                 if (currentError) {
                    break;
                 }
            }
            // --- End Stream Processing ---

            // After stream finishes, check if an error occurred during streaming
            if (currentError) {
                 throw new Error(currentError);
            }
            // If response finished but is empty, show message
            if (accumulatedResponse.trim() === ''){
                 resultsContainer.innerHTML = '<p>Received an empty response.</p>';
            } else if (!currentError && resultsContainer.innerHTML.trim() === '') {
                 // If stream ended successfully but nothing was ever rendered (edge case)
                 resultsContainer.innerHTML = '<p>Received an empty response.</p>';
            }

        } catch (error) {
            console.error('Search failed:', error);
            displayError(error.message || 'An unexpected error occurred.');
            resultsContainer.style.display = 'none'; // Hide results on error
            resultsContainer.innerHTML = ''; // Clear any partial results
            thinkingIndicator.style.display = 'none'; // Hide thinking indicator on fetch error
        } finally {
            // Ensure thinking indicator is hidden if stream ends without data/error (edge case)
             if (thinkingIndicator.style.display !== 'none') {
                 thinkingIndicator.style.display = 'none';
             }
            // Ensure the specific loading text P element is gone
            const loadingP = resultsContainer.querySelector('p.loading-text');
            if (loadingP) loadingP.remove();
        }
    });

    function displayError(message) {
        errorContainer.textContent = message;
        errorContainer.style.display = 'block';
        resultsContainer.classList.add('error'); // Add error class for potential styling
    }

    input.addEventListener('input', () => {
        if (errorContainer.style.display !== 'none') {
            errorContainer.style.display = 'none';
            resultsContainer.classList.remove('error');
        }
    });
}); 