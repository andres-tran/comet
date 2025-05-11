document.addEventListener('DOMContentLoaded', () => {
    // Register Service Worker
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            // Correct path for static JS file
            navigator.serviceWorker.register('/static/sw.js') 
                .then(registration => {
                    console.log('ServiceWorker registration successful with scope: ', registration.scope);
                })
                .catch(error => {
                    console.log('ServiceWorker registration failed: ', error);
                });
        });
    }

    const form = document.getElementById('search-form');
    const input = document.getElementById('search-input');
    const modelSelect = document.getElementById('model-select'); // Get the select element
    const resultsContainer = document.getElementById('results-container');
    const errorContainer = document.getElementById('error-container');
    const thinkingIndicator = document.querySelector('.thinking-indicator'); // Get thinking indicator
    const thinkingText = document.getElementById('thinking-text'); // Get the text span
    const downloadArea = document.getElementById('download-area'); // Get download area
    const themeToggleButton = document.getElementById('theme-toggle-button'); // Get toggle button
    const body = document.body; // Get body element
    const metaThemeColor = document.getElementById('theme-color-meta'); // Get theme-color meta tag
    const newSearchButton = document.getElementById('new-search-button'); // Get new search button

    // Configure marked.js (optional: customize options here if needed)
    // marked.setOptions({...});

    // --- Theme Handling --- 
    const currentTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;

    // Function to apply theme class and update button icon
    function applyTheme(theme) {
        if (theme === 'dark') {
            body.classList.add('dark-mode');
            themeToggleButton.innerHTML = '<i class="fas fa-sun"></i>'; // Show sun icon
            localStorage.setItem('theme', 'dark');
            if (metaThemeColor) metaThemeColor.setAttribute('content', '#000000'); // Update meta tag
        } else {
            body.classList.remove('dark-mode');
            themeToggleButton.innerHTML = '<i class="fas fa-moon"></i>'; // Show moon icon
            localStorage.setItem('theme', 'light');
            if (metaThemeColor) metaThemeColor.setAttribute('content', '#ffffff'); // Update meta tag
        }
    }

    // Initialize theme based on localStorage or system preference
    if (currentTheme) {
        applyTheme(currentTheme);
    } else if (prefersDark) {
        applyTheme('dark'); // Default to dark if system prefers and no localStorage
    } else {
        applyTheme('light'); // Default to light otherwise
    }

    // Theme toggle button event listener
    themeToggleButton.addEventListener('click', () => {
        if (body.classList.contains('dark-mode')) {
            applyTheme('light');
        } else {
            applyTheme('dark');
        }
    });
    // --- End Theme Handling ---

    // New Search button logic
    if (newSearchButton) {
        newSearchButton.addEventListener('click', (e) => {
            e.preventDefault();
            input.value = '';
            if (input.tagName === 'TEXTAREA') {
                input.style.height = '';
                input.dispatchEvent(new Event('input'));
            }
            resultsContainer.innerHTML = '<p class="placeholder-text">Your AI search results will appear here.</p>';
            resultsContainer.style.display = 'block';
            errorContainer.style.display = 'none';
            errorContainer.textContent = '';
            downloadArea.style.display = 'none';
            downloadArea.innerHTML = '';
            input.focus();
        });
    }

    // Helper function to render Markdown and wrap tables
    function renderAndUpdateTables(container, markdownContent) {
        // Parse the full markdown content
        const rawHtml = marked.parse(markdownContent);

        // Use a temporary element to easily manipulate the DOM
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = rawHtml;

        // Find all tables within the parsed content
        const tables = tempDiv.querySelectorAll('table');
        
        tables.forEach(table => {
            // Check if the table is already wrapped (to avoid double wrapping)
            if (!table.parentElement || !table.parentElement.classList.contains('table-wrapper')) {
                 // Create wrapper div
                const wrapper = document.createElement('div');
                wrapper.className = 'table-wrapper';

                // Insert wrapper before the table in the temporary DOM
                table.parentNode.insertBefore(wrapper, table);

                // Move the table inside the wrapper
                wrapper.appendChild(table);
            }
        });

        // Update the actual container's content
        container.innerHTML = tempDiv.innerHTML;
    }

    let currentEventSource = null;
    let currentResultsWrapper = null;
    let markdownBuffer = ""; // Buffer for accumulating markdown content
    let chartInstance = null; // To keep track of the chart

    function initializeNewSearch() {
        markdownBuffer = ""; // Clear buffer for new search
        if (currentResultsWrapper) {
            currentResultsWrapper.innerHTML = ''; // Clear previous results content
        }
        // Clear any existing chart
        const chartContainer = document.getElementById('chart-container');
        if (chartInstance) {
            chartInstance.destroy();
            chartInstance = null;
        }
        if (chartContainer) chartContainer.style.display = 'none';

        // Create a new results wrapper for this search stream
        currentResultsWrapper = document.createElement('div');
        currentResultsWrapper.className = 'response-item'; // Add a class for styling if needed
        resultsContainer.appendChild(currentResultsWrapper);
        resultsContainer.querySelector('.placeholder-text').style.display = 'none';
        thinkingIndicator.style.display = 'flex';
        errorContainer.textContent = '';
        errorContainer.style.display = 'none';
        downloadArea.style.display = 'none';
        if (downloadArea.firstChild) downloadArea.firstChild.remove(); // Remove old button
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();

        const query = input.value.trim();
        const selectedModel = modelSelect.value;

        if (!query) {
            displayError("Please enter a search query.");
            return;
        }

        // Prepare payload
        const payload = {
            query: query,
            model: selectedModel
        };

        // Reset UI states
        resultsContainer.style.display = 'block';
        resultsContainer.innerHTML = ''; // Clear previous results immediately
        downloadArea.style.display = 'none'; // Hide download area
        downloadArea.innerHTML = ''; // Clear previous button
        thinkingIndicator.style.display = 'flex'; // Show thinking animation
        // Clear placeholder explicitly if it exists
        const placeholder = resultsContainer.querySelector('.placeholder-text');
        if (placeholder) placeholder.remove();
        resultsContainer.classList.remove('error'); // Remove error class if present
        errorContainer.style.display = 'none';
        errorContainer.textContent = '';

        // Set appropriate thinking text
        if (selectedModel === 'gpt-image-1') {
            thinkingText.textContent = 'Generating an image...';
        } else {
            thinkingText.textContent = 'Searching the web...';
        }

        let accumulatedResponse = "";
        let currentError = null;

        // --- Handle Non-Streaming Models (Image Only) ---
        const nonStreamingModels = ['gpt-image-1'];
        if (nonStreamingModels.includes(selectedModel)) {
            const isImageModel = selectedModel === 'gpt-image-1';
            console.log(`Image model selected: ${selectedModel}. Using non-streaming fetch.`);
            resultsContainer.innerHTML = ''; // Clear results area
            thinkingIndicator.style.display = 'flex'; // Show thinking indicator
            thinkingText.textContent = isImageModel ? 'Generating an image...' : 'Searching the web...'; // Custom text

            try {
                const response = await fetch('/search', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload), // Use payload
                });

                thinkingIndicator.style.display = 'none'; // Hide indicator once response received
                const data = await response.json(); // Expecting JSON for images

                if (!response.ok) {
                    // Throw error from JSON response if available, otherwise status text
                    throw new Error(data.error || `Error: ${response.status} ${response.statusText}`);
                }

                if (data.error) {
                    throw new Error(data.error);
                }

                if (isImageModel) {
                    // Handle image response (this is the only case now)
                    if (data.image_base64) {
                        const img = document.createElement('img');
                        img.src = `data:image/jpeg;base64,${data.image_base64}`; // Assuming jpeg for grok, png for openai. Backend sends full data URI for grok.
                        // To be more robust, backend should ideally send raw base64 and type, or frontend parses the data URI prefix.
                        // For now, if grok sends `data:image/jpeg;base64,...` this will work.
                        // If OpenAI also sends `data:image/png;base64,...`, then `img.src = data.image_base64` would be cleaner if backend normalizes it.
                        // Let's assume backend for grok sends the full data URI string, and for gpt-image-1 it sends raw base64.
                        if (selectedModel === 'gpt-image-1') {
                            img.src = `data:image/png;base64,${data.image_base64}`;
                        }

                        img.alt = query; // Use prompt as alt text
                        img.classList.add('generated-image'); // Add class for styling
                        resultsContainer.appendChild(img);

                        // Display revised prompt if available (for grok-2-image)
                        if (data.revised_prompt) {
                            // This was specific to Grok, but could be kept if other models might use it.
                            // For now, assuming only Grok used it and removing for clarity unless specified otherwise.
                            // const revisedPromptText = document.createElement('p');
                            // revisedPromptText.classList.add('revised-prompt-text');
                            // revisedPromptText.innerHTML = `<strong>Revised Prompt:</strong> ${data.revised_prompt.replace(/</g, "&lt;").replace(/>/g, "&gt;")}`;
                            // resultsContainer.appendChild(revisedPromptText);
                        }

                        // Create and add download button
                        const downloadButton = document.createElement('a');
                        downloadButton.href = img.src;

                        let filename = `comet-${query.substring(0, 20).replace(/\s+/g, '_') || 'image'}`;
                        if (selectedModel === 'gpt-image-1') {
                            filename += '.png';
                        }
                        downloadButton.download = filename;

                        downloadButton.textContent = 'Download Image';
                        downloadButton.classList.add('download-button');
                        downloadArea.appendChild(downloadButton);
                        downloadArea.style.display = 'block'; // Show the download area
                    } else {
                        throw new Error("Received response but no image data found.");
                    }
                } else {
                    // Handle non-streaming text response (e.g., search models)
                    if (data.answer) {
                        // Render the full Markdown response and wrap tables
                        renderAndUpdateTables(resultsContainer, data.answer); // Use helper function
                    } else {
                         throw new Error("Received response but no answer found.");
                    }
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
            return; // Stop execution for non-streaming models (i.e., image model)
        }
        // --- End Non-Streaming Handling ---

        // --- Proceed with Text Streaming Logic (Handles all text models including search) --- 
        console.log("Streaming text model selected. Using streaming fetch.");
        thinkingText.textContent = 'Thinking...'; // Reset thinking text for streaming
        try {
            const response = await fetch('/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload), // Use payload
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

            // --- Revert to Live Text Streaming Logic ---
            console.log("Using live streaming fetch for text model.");
            thinkingText.textContent = 'Thinking...'; // Initial thinking text
            
            accumulatedResponse = ""; // Reset accumulated response for this new request
            let lineBuffer = ''; // To handle lines that might be split across chunks
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let isFirstChunkProcessed = false;

            async function processStream() {
                while (true) {
                    const { value, done } = await reader.read();
                    if (done) {
                        console.log("Stream reading complete.");
                        if (thinkingIndicator.style.display !== 'none') {
                            thinkingIndicator.style.display = 'none';
                        }
                        if (accumulatedResponse.trim() === '' && !currentError && resultsContainer.innerHTML.trim() === '') {
                             resultsContainer.innerHTML = '<p>Stream ended with no content.</p>';
                        }
                        break; // Exit loop when stream is done
                    }

                    // Decode and process the current chunk
                    lineBuffer += decoder.decode(value, { stream: true });
                    let lines = lineBuffer.split("\n");

                    // Keep the last (potentially incomplete) line in the buffer
                    lineBuffer = lines.pop(); 

                    for (const line of lines) {
                        if (line.trim().length === 0) continue; // Skip empty lines (often between SSE messages)
                        
                        if (line.startsWith('data:')) {
                            const jsonData = line.substring(5).trim();
                            if (jsonData === '[DONE]') { // Handle Perplexity [DONE] signal or similar if needed
                                console.log("Received [DONE] signal in stream.");
                                // This might be redundant if `end_of_stream` is used by all backends
                                continue;
                            }
                            try {
                                const data = JSON.parse(jsonData);

                                if (!isFirstChunkProcessed) {
                                    thinkingIndicator.style.display = 'none'; // Hide after first actual data
                                    resultsContainer.innerHTML = ''; // Clear any initial "Thinking..." text from results
                                    isFirstChunkProcessed = true;
                                }

                                if (data.error) {
                                    console.error("Error from stream data:", data.error);
                                    currentError = data.error; // Store the error
                                    // Optionally, display error directly and stop further processing
                                    displayError(data.error);
                                    resultsContainer.style.display = 'none'; 
                                    return; // Stop processing this stream
                                }

                                if (data.chunk) {
                                    accumulatedResponse += data.chunk;
                                    renderAndUpdateTables(resultsContainer, accumulatedResponse);
                                }

                                if (data.end_of_stream) {
                                    console.log('End of stream signal received from backend.');
                                    // The main loop's `done` condition will handle final cleanup.
                                    return; // Or break, depending on if more data could follow `end_of_stream`
                                }

                                if (data.chart_config) { // Handle chart_config event
                                    thinkingIndicator.style.display = 'none';
                                    renderChart(data.chart_config);
                                }

                            } catch (e) {
                                console.warn('Failed to parse SSE data line:', jsonData, e);
                                // Decide if this is a fatal error for the stream or can be skipped
                            }
                        } else {
                            console.log("Skipping non-data line from stream:", line);
                        }
                    }
                }
            }

            await processStream(); // Start processing the stream
            // --- End Live Text Streaming Logic ---

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
        downloadArea.style.display = 'none'; // Hide download area on error
    }

    input.addEventListener('input', () => {
        if (errorContainer.style.display !== 'none') {
            errorContainer.style.display = 'none';
            resultsContainer.classList.remove('error');
            downloadArea.style.display = 'none'; // Also hide download area when clearing error
        }
    });

    // Auto-resize search textarea as user types
    const searchInput = document.getElementById('search-input');
    if (searchInput && searchInput.tagName === 'TEXTAREA') {
        searchInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
        // Optional: trigger resize on page load if there's pre-filled text
        searchInput.dispatchEvent(new Event('input'));
    }

    function renderChart(chartConfig) {
        const chartContainer = document.getElementById('chart-container');
        const ctx = document.getElementById('interactive-chart').getContext('2d');
        
        if (chartInstance) {
            chartInstance.destroy(); // Destroy previous chart instance if it exists
        }

        try {
            // Basic validation or transformation of config if needed
            if (typeof chartConfig.options === 'undefined') chartConfig.options = {};
            if (typeof chartConfig.options.responsive === 'undefined') chartConfig.options.responsive = true;
            if (typeof chartConfig.options.maintainAspectRatio === 'undefined') chartConfig.options.maintainAspectRatio = true; // Or false if you want to control via CSS strictly

            chartInstance = new Chart(ctx, chartConfig);
            if (chartContainer) chartContainer.style.display = 'block';
        } catch (e) {
            console.error("Error rendering chart:", e);
            // Optionally display this error to the user
            const errorDiv = document.createElement('div');
            errorDiv.className = 'chart-render-error';
            errorDiv.textContent = `Chart.js Error: ${e.message}. Check console for details.`;
            if(currentResultsWrapper) currentResultsWrapper.appendChild(errorDiv);
            else resultsContainer.appendChild(errorDiv);
        }
    }

    function renderResponseChunk(chunk) {
        // ... existing code ...
    }
}); 