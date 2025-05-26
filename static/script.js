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
    const webSearchButton = document.getElementById('web-search-button'); // Get web search button
    const reasoningContainer = document.getElementById('reasoning-container'); // Get reasoning container
    const reasoningContent = document.getElementById('reasoning-content'); // Get reasoning content div
    const toggleReasoningBtn = document.getElementById('toggle-reasoning-btn'); // Get toggle button
    const reasoningHeader = document.querySelector('.reasoning-header'); // Get reasoning header

    // --- State for uploaded file ---
    let uploadedFileBase64 = null;
    let uploadedFileType = null;
    let uploadedFileName = null;
    
    // --- State for web search ---
    let webSearchEnabled = false;
    let webSearchInProgress = false;

    // --- Toggle reasoning container ---
    let isReasoningCollapsed = false; // Start expanded when shown
    
    function toggleReasoning() {
        isReasoningCollapsed = !isReasoningCollapsed;
        
        if (isReasoningCollapsed) {
            reasoningContent.classList.add('collapsed');
            toggleReasoningBtn.classList.add('collapsed');
        } else {
            reasoningContent.classList.remove('collapsed');
            toggleReasoningBtn.classList.remove('collapsed');
        }
    }
    
    // Add click event to toggle button and header
    if (toggleReasoningBtn) {
        toggleReasoningBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleReasoning();
        });
    }
    
    if (reasoningHeader) {
        reasoningHeader.addEventListener('click', () => {
            toggleReasoning();
        });
    }

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
            
            // Add visual feedback
            newSearchButton.classList.add('clearing');
            setTimeout(() => {
                newSearchButton.classList.remove('clearing');
            }, 600);
            
            // Clear input and reset its height
            input.value = '';
            if (input.tagName === 'TEXTAREA') {
                input.style.height = '';
                input.dispatchEvent(new Event('input'));
            }
            
            // Clear results container
            resultsContainer.innerHTML = '';
            resultsContainer.style.display = 'none';
            
            // Clear and hide reasoning container (AI thinking process)
            if (reasoningContainer) {
                reasoningContainer.style.display = 'none';
                reasoningContainer.classList.remove('fade-in');
            }
            if (reasoningContent) {
                reasoningContent.innerHTML = '';
                reasoningContent.classList.remove('collapsed');
            }
            if (toggleReasoningBtn) {
                toggleReasoningBtn.classList.remove('collapsed');
            }
            
            // Reset reasoning state
            reasoningBuffer = "";
            isReasoningCollapsed = false;
            
            // Clear error container
            errorContainer.style.display = 'none';
            errorContainer.textContent = '';
            
            // Clear download area
            downloadArea.style.display = 'none';
            downloadArea.innerHTML = '';
            
            // Clear any existing chart
            const chartContainer = document.getElementById('chart-container');
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            if (chartContainer) {
                chartContainer.style.display = 'none';
            }
            
            // Clear attached file
            clearAttachedFile();
            
                    // Clear web search sources
        clearWebSearchSources();
            
            // Reset web search state (optional - you might want to keep it enabled)
            // webSearchEnabled = false;
            // if (webSearchButton) {
            //     webSearchButton.classList.remove('web-search-enabled');
            //     webSearchButton.title = 'Enable Web Search';
            // }
            
            // Clear buffers
            markdownBuffer = "";
            
            // Hide thinking indicator
            if (thinkingIndicator) {
                thinkingIndicator.style.display = 'none';
            }
            
            // Update copy button visibility
            updateCopyButtonVisibility();
            
            // Focus on input
            input.focus();
            
            console.log('New search initiated - all previous content cleared');
        });
    }

    // --- File Input Handling ---
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
                    attachFileButton.classList.add('file-attached');
                };
                reader.onerror = (err) => {
                    displayError("Error reading file. Please try again.");
                    clearAttachedFile();
                };
                reader.readAsDataURL(file);
            }
            fileInput.value = null;
        });
    }
    
    // --- Web Search Button Handling ---
    if (webSearchButton) {
        webSearchButton.addEventListener('click', () => {
            webSearchEnabled = !webSearchEnabled;
            
            if (webSearchEnabled) {
                webSearchButton.classList.add('web-search-enabled');
                webSearchButton.innerHTML = '<i class="fas fa-globe"></i>';
                webSearchButton.title = 'Web Search Enabled - Click to disable';
            } else {
                webSearchButton.classList.remove('web-search-enabled');
                webSearchButton.innerHTML = '<i class="fas fa-globe"></i>';
                webSearchButton.title = 'Enable Web Search';
            }
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
            attachFileButton.classList.remove('file-attached');
        }
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
        updateCopyButtonVisibility();
    }

    let currentEventSource = null;
    let currentResultsWrapper = null;
    let markdownBuffer = ""; // Buffer for accumulating markdown content
    let reasoningBuffer = ""; // Buffer for accumulating reasoning content
    let chartInstance = null; // To keep track of the chart
    let webSearchResults = null; // Store web search results

        function initializeNewSearch() {
        markdownBuffer = ""; // Clear buffer for new search
        reasoningBuffer = ""; // Clear reasoning buffer
        webSearchResults = null; // Clear web search results
        if (currentResultsWrapper) {
            currentResultsWrapper.innerHTML = ''; // Clear previous results content
        }
        
        // Clear web search sources
        clearWebSearchSources();
        
        // Hide web search progress
        hideWebSearchProgress();
        
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
        if (reasoningContent) {
            reasoningContent.innerHTML = ''; // Clear old reasoning
            reasoningContent.classList.remove('collapsed'); // Reset to expanded state
        }
        if (toggleReasoningBtn) {
            toggleReasoningBtn.classList.remove('collapsed'); // Reset toggle button
        }
        isReasoningCollapsed = false; // Reset collapsed state

        // Show web search progress if enabled
        if (webSearchEnabled) {
            showWebSearchProgress();
        }

        thinkingIndicator.style.display = 'flex';
        errorContainer.textContent = '';
        errorContainer.style.display = 'none';
        downloadArea.style.display = 'none';
        if (downloadArea.firstChild) downloadArea.firstChild.remove(); // Remove old button
        updateCopyButtonVisibility();
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
            model: selectedModel,
            web_search_enabled: webSearchEnabled
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
        initializeNewSearch(); // Initialize the search properly
        resultsContainer.style.display = 'block'; // Make sure results container is visible
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
            if (webSearchEnabled) {
                thinkingText.textContent = 'Searching the web...'; // Web search text
            } else {
                thinkingText.textContent = 'Thinking...'; // Unified for OpenRouter text models
            }
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
            let lastUpdateTime = Date.now();
            let chunkCount = 0;

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
                        // Add a subtle animation when content is complete
                        if (currentResultsWrapper) {
                            currentResultsWrapper.style.animation = 'fadeInComplete 0.3s ease-out';
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

                                if (data.web_search_results) {
                                    webSearchResults = data.web_search_results;
                                    console.log(`Received web search results with ${data.web_search_results.results ? data.web_search_results.results.length : 0} sources`);
                                    
                                    // Update progress indicator with success status
                                    updateWebSearchProgress(
                                        `Found ${data.web_search_results.results ? data.web_search_results.results.length : 0} sources`,
                                        'Processing search results...'
                                    );
                                    
                                    // Create and display web search sources UI
                                    displayWebSearchSources(data.web_search_results);
                                    
                                    // Hide progress indicator after a brief delay
                                    setTimeout(() => {
                                        hideWebSearchProgress();
                                    }, 1000);
                                }

                                if (data.reasoning) {
                                    reasoningBuffer += data.reasoning;
                                    if (reasoningContent) {
                                        // Render markdown for reasoning content
                                        const reasoningHtml = marked.parse(reasoningBuffer);
                                        reasoningContent.innerHTML = reasoningHtml;
                                    }
                                    if (reasoningContainer && reasoningBuffer.trim() !== '') {
                                        reasoningContainer.style.display = 'block'; // Show if there's content
                                        // Add smooth fade-in animation
                                        if (!reasoningContainer.classList.contains('fade-in')) {
                                            reasoningContainer.classList.add('fade-in');
                                        }
                                    }
                                }

                                if (data.chunk) {
                                    chunkCount++;
                                    accumulatedResponse += data.chunk;
                                    
                                    // Update thinking text with progress
                                    const currentTime = Date.now();
                                    if (currentTime - lastUpdateTime > 500) { // Update every 500ms
                                        const dots = '.'.repeat((chunkCount % 4));
                                        thinkingText.textContent = `Processing${dots}`;
                                        lastUpdateTime = currentTime;
                                    }
                                    
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

    // Auto-resize search textarea as user types with scroll prevention
    const searchInput = document.getElementById('search-input');
    if (searchInput && searchInput.tagName === 'TEXTAREA') {
        let isResizing = false;
        let savedScrollPosition = { top: 0, left: 0 };
        let scrollLocked = false;
        
        // Function to save current scroll position
        const saveScrollPosition = () => {
            savedScrollPosition = {
                top: window.pageYOffset || document.documentElement.scrollTop,
                left: window.pageXOffset || document.documentElement.scrollLeft
            };
        };
        
        // Function to restore scroll position
        const restoreScrollPosition = () => {
            if (scrollLocked) {
                window.scrollTo(savedScrollPosition.left, savedScrollPosition.top);
            }
        };
        
        // Global scroll prevention
        const preventGlobalScroll = (event) => {
            if (scrollLocked) {
                event.preventDefault();
                event.stopPropagation();
                restoreScrollPosition();
                return false;
            }
        };
        
        // Add global scroll listeners
        window.addEventListener('scroll', preventGlobalScroll, { passive: false });
        document.addEventListener('scroll', preventGlobalScroll, { passive: false });
        
        // Additional prevention for wheel events on the textarea
        searchInput.addEventListener('wheel', function(event) {
            // Allow scrolling within the textarea if it has overflow
            if (this.scrollHeight > this.clientHeight) {
                // Let the textarea handle its own scrolling
                return;
            }
            // Prevent page scrolling when textarea doesn't need to scroll
            event.preventDefault();
            event.stopPropagation();
        }, { passive: false });
        
        // Prevent touch scrolling on mobile
        searchInput.addEventListener('touchstart', function(event) {
            scrollLocked = true;
            saveScrollPosition();
        });
        
        searchInput.addEventListener('touchmove', function(event) {
            if (scrollLocked) {
                event.preventDefault();
                restoreScrollPosition();
            }
        }, { passive: false });
        
        searchInput.addEventListener('touchend', function(event) {
            setTimeout(() => {
                scrollLocked = false;
            }, 100);
        });
        
        searchInput.addEventListener('input', function() {
            if (isResizing) return;
            isResizing = true;
            
            // Lock scrolling and save position
            scrollLocked = true;
            saveScrollPosition();
            
            // Temporarily disable scroll restoration and smooth scrolling
            const originalScrollBehavior = document.documentElement.style.scrollBehavior;
            document.documentElement.style.scrollBehavior = 'auto';
            
            // Resize the textarea
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            
            // Immediately restore scroll position multiple times to ensure it sticks
            restoreScrollPosition();
            requestAnimationFrame(() => {
                restoreScrollPosition();
                requestAnimationFrame(() => {
                    restoreScrollPosition();
                    // Unlock scrolling after a delay
                    setTimeout(() => {
                        scrollLocked = false;
                        isResizing = false;
                    }, 100);
                });
            });
            
            // Restore original styles
            document.documentElement.style.scrollBehavior = originalScrollBehavior;
        });
        
        // Prevent scrolling on focus and other events
        const preventScroll = function(event) {
            scrollLocked = true;
            saveScrollPosition();
            
            // Use multiple restoration attempts for better reliability
            requestAnimationFrame(() => {
                restoreScrollPosition();
                requestAnimationFrame(() => {
                    restoreScrollPosition();
                    setTimeout(() => {
                        scrollLocked = false;
                    }, 50);
                });
            });
        };
        
        searchInput.addEventListener('focus', preventScroll);
        searchInput.addEventListener('click', preventScroll);
        searchInput.addEventListener('mousedown', preventScroll);
        
        // Prevent scroll on keydown for certain keys that might cause scrolling
        searchInput.addEventListener('keydown', function(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                // Allow form submission on Enter without Shift
                return;
            }
            
            // For other keys, prevent any potential scrolling
            scrollLocked = true;
            saveScrollPosition();
            
            setTimeout(() => {
                restoreScrollPosition();
                scrollLocked = false;
            }, 50);
        });
        
        // Additional scroll prevention on paste events
        searchInput.addEventListener('paste', function(event) {
            scrollLocked = true;
            saveScrollPosition();
            
            setTimeout(() => {
                restoreScrollPosition();
                // Trigger input event to resize after paste
                this.dispatchEvent(new Event('input'));
                setTimeout(() => {
                    scrollLocked = false;
                }, 50);
            }, 10);
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

    // --- Enhanced Copy to Clipboard Buttons ---
    function copyToClipboard(text) {
        return new Promise((resolve, reject) => {
            if (!navigator.clipboard) {
                // fallback for older browsers
                try {
                    const textarea = document.createElement('textarea');
                    textarea.value = text;
                    textarea.style.position = 'fixed';
                    textarea.style.opacity = '0';
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                    resolve();
                } catch (err) {
                    reject(err);
                }
            } else {
                navigator.clipboard.writeText(text).then(resolve).catch(reject);
            }
        });
    }

    function showCopyFeedback(button, success = true) {
        const originalText = button.innerHTML;
        const originalTitle = button.title;
        
        if (success) {
            button.classList.add('copied');
            button.innerHTML = '<i class="fas fa-check"></i> Copied!';
            button.title = 'Copied to clipboard!';
        } else {
            button.style.color = '#ef4444';
            button.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Failed';
            button.title = 'Copy failed - try again';
        }
        
        setTimeout(() => {
            button.classList.remove('copied');
            button.innerHTML = originalText;
            button.title = originalTitle;
            button.style.color = '';
        }, 2000);
    }

    const copyResultsBtn = document.getElementById('copy-results-btn');
    const copyReasoningBtn = document.getElementById('copy-reasoning-btn');
    
    if (copyResultsBtn) {
        copyResultsBtn.addEventListener('click', async () => {
            try {
                // Get clean text content without copy button text
                const resultsClone = resultsContainer.cloneNode(true);
                const copyBtn = resultsClone.querySelector('.copy-btn');
                if (copyBtn) copyBtn.remove();
                
                // Extract text and clean it up
                let text = resultsClone.innerText || resultsClone.textContent || '';
                text = text.trim();
                
                if (!text) {
                    throw new Error('No content to copy');
                }
                
                await copyToClipboard(text);
                showCopyFeedback(copyResultsBtn, true);
                console.log('Results copied to clipboard successfully');
            } catch (error) {
                console.error('Failed to copy results:', error);
                showCopyFeedback(copyResultsBtn, false);
            }
        });
    }
    
    if (copyReasoningBtn) {
        copyReasoningBtn.addEventListener('click', async () => {
            try {
                // Get clean text content
                let text = reasoningContent ? (reasoningContent.innerText || reasoningContent.textContent || '') : '';
                text = text.trim();
                
                if (!text) {
                    throw new Error('No reasoning content to copy');
                }
                
                await copyToClipboard(text);
                showCopyFeedback(copyReasoningBtn, true);
                console.log('Reasoning copied to clipboard successfully');
            } catch (error) {
                console.error('Failed to copy reasoning:', error);
                showCopyFeedback(copyReasoningBtn, false);
            }
        });
    }

    // --- Keyboard Shortcuts ---
    document.addEventListener('keydown', (event) => {
        // Ctrl+C or Cmd+C to copy results (when not in input field)
        if ((event.ctrlKey || event.metaKey) && event.key === 'c' && 
            !['INPUT', 'TEXTAREA'].includes(event.target.tagName) &&
            resultsContainer.style.display !== 'none' &&
            resultsContainer.innerHTML.trim() !== '') {
            
            event.preventDefault();
            if (copyResultsBtn) {
                copyResultsBtn.click();
            }
        }
    });

    // Show copy button when content is available
    function updateCopyButtonVisibility() {
        if (copyResultsBtn) {
            const hasContent = resultsContainer && 
                              resultsContainer.style.display !== 'none' && 
                              resultsContainer.innerHTML.trim() !== '' &&
                              !resultsContainer.querySelector('.placeholder-text');
            
            if (hasContent) {
                copyResultsBtn.style.display = 'flex';
                copyResultsBtn.style.opacity = '0.8';
            } else {
                copyResultsBtn.style.display = 'none';
            }
        }
    }

    // Also update visibility on new search
    const originalInitializeNewSearch = initializeNewSearch;
    initializeNewSearch = function() {
        originalInitializeNewSearch();
        updateCopyButtonVisibility();
    };

    function clearWebSearchSources() {
        // Clear web search sources container
        const sourcesContainer = document.getElementById('web-search-sources');
        if (sourcesContainer) {
            sourcesContainer.remove();
        }
        
        // Clear web search progress indicator
        const progressIndicator = document.getElementById('web-search-progress');
        if (progressIndicator) {
            progressIndicator.remove();
        }
        
        // Reset web search results state
        webSearchResults = null;
        webSearchInProgress = false;
    }

    function displayWebSearchSources(searchResults) {
        if (!searchResults || !searchResults.results || searchResults.results.length === 0) {
            console.log("No web search results to display");
            return;
        }

        console.log(`Frontend received ${searchResults.results.length} web search sources:`, searchResults.results.map(r => r.title));

        // Check if sources container already exists
        let sourcesContainer = document.getElementById('web-search-sources');
        if (!sourcesContainer) {
            // Create sources container
            sourcesContainer = document.createElement('div');
            sourcesContainer.id = 'web-search-sources';
            sourcesContainer.className = 'web-search-sources';
            
            // Insert it before the results container
            const resultsArea = document.querySelector('.results-area');
            const resultsContainer = document.getElementById('results-container');
            if (resultsArea && resultsContainer) {
                resultsArea.insertBefore(sourcesContainer, resultsContainer);
            }
        }

        // Clear existing content
        sourcesContainer.innerHTML = '';

        // Create simple header like reasoning container
        const header = document.createElement('div');
        header.className = 'sources-header';
        header.innerHTML = `
            <h4>
                <i class="fas fa-globe"></i> Web Sources
                <span class="sources-count">(${searchResults.results.length})</span>
            </h4>
            <button class="toggle-btn" id="toggle-sources-btn" title="Toggle sources">
                <i class="fas fa-chevron-up"></i>
            </button>
        `;
        sourcesContainer.appendChild(header);

        // Create sources content container
        const sourcesContent = document.createElement('div');
        sourcesContent.className = 'sources-content';
        sourcesContent.id = 'sources-content';

        // Add quick answer if available
        if (searchResults.answer && searchResults.answer.trim()) {
            const quickAnswer = document.createElement('div');
            quickAnswer.className = 'quick-answer';
            quickAnswer.innerHTML = `
                <div class="quick-answer-label">
                    <i class="fas fa-lightbulb"></i> Quick Answer
                </div>
                <div class="quick-answer-content">${searchResults.answer}</div>
            `;
            sourcesContent.appendChild(quickAnswer);
        }

        // Create simple sources list
        const sourcesList = document.createElement('div');
        sourcesList.className = 'sources-list';

        searchResults.results.forEach((result, index) => {
            const sourceItem = document.createElement('div');
            sourceItem.className = 'source-item';
            
            // Create source link
            const sourceLink = document.createElement('a');
            sourceLink.href = result.url;
            sourceLink.target = '_blank';
            sourceLink.rel = 'noopener noreferrer';
            sourceLink.className = 'source-link';
            sourceLink.setAttribute('aria-label', `Source ${index + 1}: ${result.title}`);
            
            // Extract domain from URL
            let domain = '';
            try {
                const url = new URL(result.url);
                domain = url.hostname.replace('www.', '');
            } catch (e) {
                domain = result.url.split('/')[0] || 'Unknown source';
            }
            
            sourceLink.innerHTML = `
                <span class="source-number">${index + 1}</span>
                <span class="source-title">${result.title}</span>
                <span class="source-domain">${domain}</span>
            `;
            
            sourceItem.appendChild(sourceLink);
            sourcesList.appendChild(sourceItem);
        });

        sourcesContent.appendChild(sourcesList);
        sourcesContainer.appendChild(sourcesContent);

        // Add toggle functionality like reasoning container
        const toggleBtn = header.querySelector('#toggle-sources-btn');
        let isSourcesCollapsed = false;
        
        function toggleSources() {
            isSourcesCollapsed = !isSourcesCollapsed;
            
            if (isSourcesCollapsed) {
                sourcesContent.classList.add('collapsed');
                toggleBtn.classList.add('collapsed');
                toggleBtn.innerHTML = '<i class="fas fa-chevron-down"></i>';
                toggleBtn.title = 'Expand sources';
            } else {
                sourcesContent.classList.remove('collapsed');
                toggleBtn.classList.remove('collapsed');
                toggleBtn.innerHTML = '<i class="fas fa-chevron-up"></i>';
                toggleBtn.title = 'Collapse sources';
            }
        }
        
        // Add click event to toggle button and header
        toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleSources();
        });
        
        header.addEventListener('click', () => {
            toggleSources();
        });
        
        // Add fade-in animation
        try {
            sourcesContainer.classList.add('fade-in');
        } catch (e) {
            console.warn('Animation not supported:', e);
        }
        
        // Log successful source display
        console.log(`Displayed ${searchResults.results.length} web search sources with simple collapsible interface`);
    }

    // Function to show web search progress
    function showWebSearchProgress() {
        if (!webSearchEnabled) return;
        
        webSearchInProgress = true;
        
        // Create or update progress indicator
        let progressIndicator = document.getElementById('web-search-progress');
        if (!progressIndicator) {
            progressIndicator = document.createElement('div');
            progressIndicator.id = 'web-search-progress';
            progressIndicator.className = 'web-search-progress';
            
            // Insert before results container
            const resultsArea = document.querySelector('.results-area');
            const resultsContainer = document.getElementById('results-container');
            if (resultsArea && resultsContainer) {
                resultsArea.insertBefore(progressIndicator, resultsContainer);
            }
        }
        
        progressIndicator.innerHTML = `
            <div class="progress-content">
                <div class="progress-icon">
                    <i class="fas fa-globe fa-spin"></i>
                </div>
                <div class="progress-text">
                    <div class="progress-title">Searching the web...</div>
                    <div class="progress-subtitle">Finding the most relevant and recent sources</div>
                </div>
            </div>
        `;
        
        progressIndicator.style.display = 'block';
    }

    // Function to hide web search progress
    function hideWebSearchProgress() {
        webSearchInProgress = false;
        const progressIndicator = document.getElementById('web-search-progress');
        if (progressIndicator) {
            progressIndicator.style.display = 'none';
        }
    }

    // Function to update web search progress with status
    function updateWebSearchProgress(status, details = '') {
        if (!webSearchInProgress) return;
        
        const progressIndicator = document.getElementById('web-search-progress');
        if (!progressIndicator) return;
        
        const progressTitle = progressIndicator.querySelector('.progress-title');
        const progressSubtitle = progressIndicator.querySelector('.progress-subtitle');
        
        if (progressTitle && progressSubtitle) {
            progressTitle.textContent = status;
            progressSubtitle.textContent = details;
        }
    }

    // Function to show web search error
    function showWebSearchError(errorMessage) {
        if (!webSearchInProgress) return;
        
        const progressIndicator = document.getElementById('web-search-progress');
        if (!progressIndicator) return;
        
        progressIndicator.innerHTML = `
            <div class="progress-content error">
                <div class="progress-icon error">
                    <i class="fas fa-exclamation-triangle"></i>
                </div>
                <div class="progress-text">
                    <div class="progress-title">Web search failed</div>
                    <div class="progress-subtitle">${errorMessage}</div>
                </div>
                <button class="retry-search-btn" title="Retry search">
                    <i class="fas fa-redo"></i>
                </button>
            </div>
        `;
        
        // Add retry functionality
        const retryBtn = progressIndicator.querySelector('.retry-search-btn');
        if (retryBtn) {
            retryBtn.addEventListener('click', () => {
                hideWebSearchProgress();
                // Could trigger a new search here if needed
            });
        }
        
        // Auto-hide error after 5 seconds
        setTimeout(() => {
            hideWebSearchProgress();
        }, 5000);
    }

}); 