document.addEventListener('DOMContentLoaded', () => {
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
        } else {
            body.classList.remove('dark-mode');
            themeToggleButton.innerHTML = '<i class="fas fa-moon"></i>'; // Show moon icon
            localStorage.setItem('theme', 'light');
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

    // Function to add Copy buttons to <pre> blocks
    function addCopyButtons() {
        const preBlocks = resultsContainer.querySelectorAll('pre');
        preBlocks.forEach(pre => {
            // Avoid adding multiple buttons
            if (pre.querySelector('.copy-button')) {
                return;
            }

            const codeBlock = pre.querySelector('code');
            if (!codeBlock) return; // Only add to pre blocks containing code

            const button = document.createElement('button');
            button.textContent = 'Copy';
            button.className = 'copy-button';
            button.setAttribute('aria-label', 'Copy code to clipboard');
            // Style the button - consider moving to CSS
            button.style.position = 'absolute';
            button.style.top = '0.5em';
            button.style.right = '0.5em';
            button.style.padding = '0.2em 0.5em';
            button.style.border = '1px solid var(--border-color)';
            button.style.borderRadius = '4px';
            button.style.backgroundColor = 'var(--secondary-bg-color)';
            button.style.color = 'var(--primary-text-color)';
            button.style.cursor = 'pointer';
            button.style.fontSize = '0.8em';
            button.style.opacity = '0.7'; // Slightly transparent initially
            button.style.transition = 'opacity 0.2s';

            // Add hover effect for visibility
             pre.style.position = 'relative'; // Parent needs relative position
             pre.addEventListener('mouseover', () => { button.style.opacity = '1'; });
             pre.addEventListener('mouseout', () => { button.style.opacity = '0.7'; });


            button.addEventListener('click', async () => {
                const codeToCopy = codeBlock.innerText;
                try {
                    await navigator.clipboard.writeText(codeToCopy);
                    button.textContent = 'Copied!';
                    setTimeout(() => {
                        button.textContent = 'Copy';
                    }, 2000); // Revert after 2 seconds
                } catch (err) {
                    console.error('Failed to copy code:', err);
                    button.textContent = 'Error';
                    setTimeout(() => {
                        button.textContent = 'Copy';
                    }, 2000);
                }
            });

            pre.appendChild(button);
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

        // Add copy buttons after rendering
        addCopyButtons();
    }

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
        const nonStreamingModels = ['gpt-image-1']; // Removed search model
        if (nonStreamingModels.includes(selectedModel)) {
            const isImageModel = selectedModel === 'gpt-image-1'; // This will always be true now
            console.log(`Image model selected. Using non-streaming fetch.`);
            resultsContainer.innerHTML = ''; // Clear results area
            thinkingIndicator.style.display = 'flex'; // Show thinking indicator
            thinkingText.textContent = isImageModel ? 'Generating an image...' : 'Searching the web...'; // Custom text

            try {
                const response = await fetch('/search', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ query: query, model: selectedModel }),
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
                        img.src = `data:image/png;base64,${data.image_base64}`;
                        img.alt = query; // Use prompt as alt text
                        img.classList.add('generated-image'); // Add class for styling
                        resultsContainer.appendChild(img);

                        // Create and add download button
                        const downloadButton = document.createElement('a');
                        downloadButton.href = img.src;
                        downloadButton.download = `comet-${query.substring(0, 20).replace(/\s+/g, '_') || 'image'}.png`; // Suggest filename
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
                                // Render Markdown and wrap tables
                                renderAndUpdateTables(resultsContainer, accumulatedResponse); // Use helper function
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
            if (accumulatedResponse.trim() === '' && resultsContainer.innerHTML.trim() === ''){
                 resultsContainer.innerHTML = '<p>Received an empty response.</p>';
             }

            // Ensure copy buttons are added even if the last chunk didn't trigger rendering
            addCopyButtons();

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
}); 