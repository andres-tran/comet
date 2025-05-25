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
    const fileInput = document.getElementById('file-input'); // Get file input
    const attachFileButton = document.getElementById('attach-file-button'); // Get attach file button
    const reasoningContainer = document.getElementById('reasoning-container'); // Get reasoning container
    const reasoningContent = document.getElementById('reasoning-content'); // Get reasoning content div

    // --- State for uploaded file ---
    let uploadedFileBase64 = null;
    let uploadedFileType = null;
    let uploadedFileName = null;

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
            // Keep results container hidden on new search, it will be shown on next query
            resultsContainer.innerHTML = ''; // Clear content but keep it hidden
            resultsContainer.style.display = 'none'; 
            errorContainer.style.display = 'none';
            errorContainer.textContent = '';
            downloadArea.style.display = 'none';
            downloadArea.innerHTML = '';
            clearAttachedFile(); // Clear any attached file
            input.focus();
        });
    }

    // --- File Input Handling ---
    const filePreviewArea = document.getElementById('file-preview-area');
    function updateFilePreview() {
        if (!uploadedFileBase64 || !uploadedFileType) {
            filePreviewArea.style.display = 'none';
            filePreviewArea.innerHTML = '';
            return;
        }
        filePreviewArea.style.display = 'flex';
        let previewHTML = '';
        if (uploadedFileType.startsWith('image/')) {
            previewHTML = `<img src="${uploadedFileBase64}" alt="Preview" />`;
        } else if (uploadedFileType === 'application/pdf') {
            previewHTML = `<span class="pdf-icon"><i class="fas fa-file-pdf"></i></span>`;
        }
        previewHTML += `<span>${uploadedFileName || 'File attached'}</span>`;
        previewHTML += `<button class="remove-file-btn" title="Remove file" tabindex="0"><i class="fas fa-times"></i></button>`;
        filePreviewArea.innerHTML = previewHTML;
        // Remove file event
        const removeBtn = filePreviewArea.querySelector('.remove-file-btn');
        if (removeBtn) {
            removeBtn.addEventListener('click', (e) => {
                e.preventDefault();
                clearAttachedFile();
                updateFilePreview();
            });
        }
    }

    if (attachFileButton && fileInput) {
        attachFileButton.addEventListener('click', () => {
            fileInput.click();
        });
        fileInput.addEventListener('change', (event) => {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    uploadedFileBase64 = e.target.result;
                    uploadedFileType = file.type;
                    uploadedFileName = file.name;
                    attachFileButton.innerHTML = '<i class="fas fa-file-alt"></i>';
                    attachFileButton.title = `Attached: ${uploadedFileName}`;
                    updateFilePreview();
                };
                reader.onerror = (err) => {
                    displayError("Error reading file. Please try again.");
                    clearAttachedFile();
                    updateFilePreview();
                };
                reader.readAsDataURL(file);
            }
            fileInput.value = null;
        });
    }
    function clearAttachedFile() {
        uploadedFileBase64 = null;
        uploadedFileType = null;
        uploadedFileName = null;
        if (fileInput) fileInput.value = null;
        if (attachFileButton) {
            attachFileButton.innerHTML = '<i class="fas fa-paperclip"></i>';
            attachFileButton.title = 'Attach File';
        }
        filePreviewArea.style.display = 'none';
        filePreviewArea.innerHTML = '';
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
    let reasoningBuffer = ""; // Buffer for accumulating reasoning content
    let chartInstance = null; // To keep track of the chart

    function initializeNewSearch() {
        markdownBuffer = ""; // Clear buffer for new search
        reasoningBuffer = ""; // Clear reasoning buffer
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
        const placeholder = resultsContainer.querySelector('.placeholder-text');
        if(placeholder) placeholder.style.display = 'none';

        if (reasoningContainer) reasoningContainer.style.display = 'none'; // Hide reasoning container
        if (reasoningContent) reasoningContent.innerHTML = ''; // Clear old reasoning

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

        if (!query && !uploadedFileBase64) { // Require query if no file, or file if no query
            displayError("Please enter a search query or attach a file.");
            return;
        }
        if (!query && uploadedFileBase64) {
             // If only a file is present, we might need a default query for some models
             // For now, let's allow it and the backend can decide. Or we can enforce a query.
             console.log("Proceeding with file only, no text query.");
        }

        // Prepare payload
        const payload = {
            query: query, // Query can be empty if a file is attached
            model: selectedModel
        };

        if (uploadedFileBase64 && uploadedFileType) {
            payload.uploaded_file_data = uploadedFileBase64;
            if (uploadedFileType.startsWith('image/')) {
                payload.file_type = 'image';
            } else if (uploadedFileType === 'application/pdf') {
                payload.file_type = 'pdf';
            } else {
                console.warn("Unsupported file type stored:", uploadedFileType);
                // displayError might be too disruptive here, backend will validate.
            }
        }

        // Reset UI states
        resultsContainer.style.display = 'block'; // Make sure results container is visible
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
            if (payload.uploaded_file_data && payload.file_type === 'image') {
                thinkingText.textContent = 'Editing image...'; // New text for editing
            } else {
                thinkingText.textContent = 'Generating image...';
            }
        } else {
            thinkingText.textContent = 'Thinking...'; // Unified for OpenRouter text models
        }

        let accumulatedResponse = "";
        let currentError = null;

        // --- Handle Non-Streaming Models (Image Only) ---
        const nonStreamingModels = ['gpt-image-1']; // Array for clarity, even if only one
        if (nonStreamingModels.includes(selectedModel)) {
            // This block is specifically for gpt-image-1 now
            console.log(`Image model selected: ${selectedModel}. Using non-streaming fetch.`);
            resultsContainer.innerHTML = ''; // Clear results area
            resultsContainer.style.display = 'block'; 
            thinkingIndicator.style.display = 'flex'; 
            // thinkingText already set above

            try {
                const response = await fetch('/search', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload),
                });

                thinkingIndicator.style.display = 'none';
                const data = await response.json();

                if (!response.ok) {
                    // data.error here should be the structured error from Flask's jsonify
                    throw data.error || new Error(`Error: ${response.status} ${response.statusText}`);
                }
                if (data.error) { // This might be redundant if !response.ok covers it via jsonify
                    throw data.error; 
                }

                // Handle image response (this is the only case for this block now)
                if (data.image_base64) {
                    const img = document.createElement('img');
                    // gpt-image-1 from direct OpenAI API sends raw base64 for PNG
                    img.src = `data:image/png;base64,${data.image_base64}`;
                    img.alt = data.is_edit ? "Edited Image: " + query : "Generated Image: " + query;
                    img.classList.add('generated-image');
                    resultsContainer.appendChild(img);

                    // Create and add download button
                    const downloadButton = document.createElement('a');
                    downloadButton.href = img.src;
                    let filename = `comet-${query.substring(0, 20).replace(/\s+/g, '_') || 'image'}.png`;
                    downloadButton.download = filename;
                    downloadButton.textContent = 'Download Image';
                    downloadButton.classList.add('download-button');
                    downloadArea.appendChild(downloadButton);
                    downloadArea.style.display = 'block';
                } else {
                    throw new Error("Received response but no image data found.");
                }

            } catch (error) {
                console.error('Search failed for image model:', error);
                displayError(error); // Pass the whole error object or message string
                resultsContainer.style.display = 'none';
                resultsContainer.innerHTML = '';
                thinkingIndicator.style.display = 'none';
            } finally {
                 if (thinkingIndicator.style.display !== 'none') {
                     thinkingIndicator.style.display = 'none';
                 }
                const loadingP = resultsContainer.querySelector('p.loading-text');
                if (loadingP) loadingP.remove();
            }
            return; // Stop execution for gpt-image-1
        }
        // --- End Non-Streaming Handling ---

        // --- Proceed with Text Streaming Logic (Handles all OpenRouter models) --- 
        console.log("Streaming text model selected (OpenRouter). Using streaming fetch.");
        // thinkingText already set for OpenRouter models
        try {
            const response = await fetch('/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                // Handle immediate HTTP errors (e.g., 404, 500 before streaming starts)
                let errorToThrow;
                try {
                    // Try to get error from body if available
                    const errorData = await response.json(); // Non-streaming error response
                    errorToThrow = errorData.error || new Error(`Error: ${response.status} ${response.statusText}`);
                } catch (e) { 
                    errorToThrow = new Error(`Error: ${response.status} ${response.statusText}. Could not parse error response.`);
                }
                throw errorToThrow;
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
                            try {
                                const data = JSON.parse(jsonData);

                                if (!isFirstChunkProcessed) {
                                    thinkingIndicator.style.display = 'none'; // Hide after first actual data
                                    resultsContainer.innerHTML = ''; // Clear any initial "Thinking..." text from results
                                    resultsContainer.style.display = 'block'; // Explicitly show container
                                    isFirstChunkProcessed = true;
                                }

                                if (data.error) {
                                    console.error("Error from stream data:", data.error);
                                    currentError = data.error; // Store the error
                                    displayError(data.error); // Pass the structured error from stream
                                    resultsContainer.style.display = 'none'; 
                                    return; // Stop processing this stream
                                }

                                if (data.reasoning) {
                                    reasoningBuffer += data.reasoning;
                                    if (reasoningContent) {
                                        reasoningContent.textContent = reasoningBuffer; // Display raw reasoning text
                                    }
                                    if (reasoningContainer && reasoningBuffer.trim() !== '') {
                                        reasoningContainer.style.display = 'block'; // Show if there's content
                                    }
                                }

                                if (data.chunk) {
                                    accumulatedResponse += data.chunk;
                                    renderAndUpdateTables(resultsContainer, accumulatedResponse);
                                }

                                if (data.end_of_stream) {
                                    console.log('End of stream signal received from backend.');
                                    // The main loop's `done` condition will handle final cleanup.
                                    if (reasoningBuffer.trim() === '' && reasoningContainer) {
                                        reasoningContainer.style.display = 'none'; // Hide if empty
                                    }
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
            displayError(error); // Pass the whole error object or message string
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
        hideSkeletonLoader();
    });

    function displayError(errorInput) {
        let displayHTML = '';
        if (typeof errorInput === 'string') {
            displayHTML = `<p>${errorInput}</p>`;
        } else if (errorInput && typeof errorInput === 'object') {
            // Main message
            displayHTML = `<p>${errorInput.message || 'An unspecified error occurred.'}</p>`;
            
            // Code
            if (errorInput.code) {
                displayHTML += `<p><small>Error Code: ${errorInput.code}</small></p>`;
            }

            // Metadata
            if (errorInput.metadata) {
                let metadataHTML = '<div class="error-metadata"><small><strong>Details:</strong><ul>';
                if (errorInput.metadata.provider_name) {
                    metadataHTML += `<li>Provider: ${errorInput.metadata.provider_name}</li>`;
                }
                if (errorInput.metadata.reasons && Array.isArray(errorInput.metadata.reasons)) {
                    metadataHTML += '<li>Reasons:<ul>';
                    errorInput.metadata.reasons.forEach(reason => {
                        metadataHTML += `<li>${reason}</li>`;
                    });
                    metadataHTML += '</ul></li>';
                }
                if (errorInput.metadata.flagged_input) {
                    // Sanitize flagged_input before displaying to prevent XSS
                    const flaggedInputText = document.createElement('textarea');
                    flaggedInputText.textContent = errorInput.metadata.flagged_input;
                    metadataHTML += `<li>Flagged Input: <pre><code>${flaggedInputText.innerHTML}</code></pre></li>`;
                }
                // Could add more specific metadata handling here if needed
                if (errorInput.metadata.raw && typeof errorInput.metadata.raw === 'string') {
                     metadataHTML += `<li>Raw details: ${errorInput.metadata.raw.substring(0,100)}...</li>`;
                } else if (errorInput.metadata.raw && typeof errorInput.metadata.raw === 'object') {
                    metadataHTML += `<li>Raw details: ${JSON.stringify(errorInput.metadata.raw).substring(0,100)}...</li>`;
                }
                metadataHTML += '</ul></small></div>';
                displayHTML += metadataHTML;
            }
        } else {
            displayHTML = '<p>An unexpected error occurred. Check the console for details.</p>';
        }

        errorContainer.innerHTML = displayHTML;
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

    // --- Skeleton Loader ---
    const skeletonLoader = document.getElementById('skeleton-loader');
    function showSkeletonLoader() {
        if (skeletonLoader) skeletonLoader.style.display = 'block';
    }
    function hideSkeletonLoader() {
        if (skeletonLoader) skeletonLoader.style.display = 'none';
    }

    // --- Copy to Clipboard Buttons ---
    function copyToClipboard(text) {
        if (!navigator.clipboard) {
            // fallback
            const textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        } else {
            navigator.clipboard.writeText(text);
        }
    }
    const copyResultsBtn = document.getElementById('copy-results-btn');
    const copyReasoningBtn = document.getElementById('copy-reasoning-btn');
    if (copyResultsBtn) {
        copyResultsBtn.addEventListener('click', () => {
            const text = resultsContainer ? resultsContainer.innerText : '';
            copyToClipboard(text);
            copyResultsBtn.classList.add('copied');
            copyResultsBtn.title = 'Copied!';
            setTimeout(() => {
                copyResultsBtn.classList.remove('copied');
                copyResultsBtn.title = 'Copy Results';
            }, 1200);
        });
    }
    if (copyReasoningBtn) {
        copyReasoningBtn.addEventListener('click', () => {
            const text = reasoningContent ? reasoningContent.innerText : '';
            copyToClipboard(text);
            copyReasoningBtn.classList.add('copied');
            copyReasoningBtn.title = 'Copied!';
            setTimeout(() => {
                copyReasoningBtn.classList.remove('copied');
                copyReasoningBtn.title = 'Copy Reasoning';
            }, 1200);
        });
    }
}); 