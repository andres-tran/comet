document.addEventListener('DOMContentLoaded', () => {
    // Register Service Worker with better caching
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/static/sw.js') 
                .then(registration => {
                    console.log('ServiceWorker registration successful with scope: ', registration.scope);
                })
                .catch(error => {
                    console.log('ServiceWorker registration failed: ', error);
                });
        });
    }

    // Enhanced UI Elements
    const form = document.getElementById('search-form');
    const input = document.getElementById('search-input');
    const modelSelect = document.getElementById('model-select');
    const resultsContainer = document.getElementById('results-container');
    const errorContainer = document.getElementById('error-container');
    const thinkingIndicator = document.querySelector('.thinking-indicator');
    const thinkingText = document.getElementById('thinking-text');
    const downloadArea = document.getElementById('download-area');
    const themeToggleButton = document.getElementById('theme-toggle-button');
    const body = document.body;
    const metaThemeColor = document.getElementById('theme-color-meta');
    const newSearchButton = document.getElementById('new-search-button');
    const fileInput = document.getElementById('file-input');
    const attachFileButton = document.getElementById('attach-file-button');
    const webSearchButton = document.getElementById('web-search-button');
    const reasoningContainer = document.getElementById('reasoning-container');
    const reasoningContent = document.getElementById('reasoning-content');
    const toggleReasoningBtn = document.getElementById('toggle-reasoning-btn');
    const reasoningHeader = document.querySelector('.reasoning-header');

    // Enhanced State Management
    let uploadedFileBase64 = null;
    let uploadedFileType = null;
    let uploadedFileName = null;
    let webSearchEnabled = false;
    let webSearchInProgress = false;
    let isReasoningCollapsed = false;
    let currentSearch = null;
    let searchHistory = [];
    let thinkingMessages = [
        "Analyzing your question...",
        "Searching for relevant information...",
        "Processing multiple sources...",
        "Synthesizing insights...",
        "Formulating comprehensive response...",
        "Adding final touches..."
    ];
    let thinkingMessageIndex = 0;
    let thinkingInterval = null;

    // Enhanced Theme Handling with System Detection
    function detectSystemTheme() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }

    function applyTheme(theme) {
        if (theme === 'dark') {
            body.classList.add('dark-mode');
            themeToggleButton.innerHTML = '<i class="fas fa-sun"></i>';
            localStorage.setItem('theme', 'dark');
            if (metaThemeColor) metaThemeColor.setAttribute('content', '#0f0f0f');
        } else {
            body.classList.remove('dark-mode');
            themeToggleButton.innerHTML = '<i class="fas fa-moon"></i>';
            localStorage.setItem('theme', 'light');
            if (metaThemeColor) metaThemeColor.setAttribute('content', '#ffffff');
        }
    }

    // Initialize theme
    const savedTheme = localStorage.getItem('theme');
    const systemTheme = detectSystemTheme();
    applyTheme(savedTheme || systemTheme);

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!localStorage.getItem('theme')) {
            applyTheme(e.matches ? 'dark' : 'light');
        }
    });

    themeToggleButton.addEventListener('click', () => {
        const newTheme = body.classList.contains('dark-mode') ? 'light' : 'dark';
        applyTheme(newTheme);
    });

    // Enhanced Auto-resize textarea with debouncing
    let resizeTimeout;
    function autoResizeTextarea() {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            input.style.height = 'auto';
            const newHeight = Math.min(input.scrollHeight, 150);
            input.style.height = newHeight + 'px';
        }, 10);
    }

    input.addEventListener('input', autoResizeTextarea);
    input.addEventListener('paste', () => setTimeout(autoResizeTextarea, 50));

    // Enhanced Reasoning Toggle with Animation
    function toggleReasoning() {
        isReasoningCollapsed = !isReasoningCollapsed;
        
        if (isReasoningCollapsed) {
            reasoningContent.classList.add('collapsed');
            toggleReasoningBtn.classList.add('collapsed');
            localStorage.setItem('reasoning-collapsed', 'true');
        } else {
                reasoningContent.classList.remove('collapsed');
                toggleReasoningBtn.classList.remove('collapsed');
            localStorage.setItem('reasoning-collapsed', 'false');
        }
    }

    // Initialize reasoning state from localStorage
    if (localStorage.getItem('reasoning-collapsed') === 'true') {
        isReasoningCollapsed = true;
        reasoningContent.classList.add('collapsed');
        toggleReasoningBtn.classList.add('collapsed');
    }

    if (toggleReasoningBtn) {
        toggleReasoningBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleReasoning();
        });
    }

    if (reasoningHeader) {
        reasoningHeader.addEventListener('click', toggleReasoning);
    }

    // Enhanced File Handling with Preview
    function handleFileUpload(file) {
        if (!file) return;
        
        const maxSize = 10 * 1024 * 1024; // 10MB limit
        if (file.size > maxSize) {
            displayError("File size exceeds 10MB limit. Please choose a smaller file.");
            return;
        }

                const reader = new FileReader();
                reader.onload = (e) => {
                    uploadedFileBase64 = e.target.result;
                    uploadedFileType = file.type;
                    uploadedFileName = file.name;
            
            // Update button appearance
            attachFileButton.innerHTML = '<i class="fas fa-check-circle"></i>';
                    attachFileButton.title = `Attached: ${uploadedFileName}`;
                    attachFileButton.classList.add('file-attached');
            
            // Show file preview (optional enhancement)
            showFilePreview(file);
                };
        reader.onerror = () => {
                    displayError("Error reading file. Please try again.");
                    clearAttachedFile();
                };
                reader.readAsDataURL(file);
            }

    function showFilePreview(file) {
        // Optional: Add a small preview of the attached file
        console.log(`File attached: ${file.name} (${(file.size / 1024).toFixed(2)}KB)`);
    }

    if (attachFileButton && fileInput) {
        attachFileButton.addEventListener('click', () => {
            fileInput.click();
        });
        
        fileInput.addEventListener('change', (event) => {
            const file = event.target.files[0];
            if (file) handleFileUpload(file);
        });
        
        // Drag and drop support
        const dropZone = document.querySelector('.search-form-perplexity');
        
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, preventDefaults, false);
        });
        
        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => {
                dropZone.classList.add('drag-hover');
            }, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => {
                dropZone.classList.remove('drag-hover');
            }, false);
        });
        
        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length > 0) {
                handleFileUpload(files[0]);
            }
        }, false);
    }

    // Enhanced Web Search with Visual Feedback
    if (webSearchButton) {
        webSearchButton.addEventListener('click', () => {
            webSearchEnabled = !webSearchEnabled;
            
            if (webSearchEnabled) {
                webSearchButton.classList.add('web-search-enabled');
                webSearchButton.innerHTML = '<i class="fas fa-globe"></i>';
                webSearchButton.title = 'Web Search Enabled - Click to disable';
                
                // Add pulse animation
                webSearchButton.style.animation = 'pulse 2s infinite';
            } else {
                webSearchButton.classList.remove('web-search-enabled');
                webSearchButton.innerHTML = '<i class="fas fa-globe"></i>';
                webSearchButton.title = 'Enable Web Search';
                webSearchButton.style.animation = '';
            }
            
            // Save preference
            localStorage.setItem('web-search-enabled', webSearchEnabled);
        });
        
        // Restore web search preference
        if (localStorage.getItem('web-search-enabled') === 'true') {
            webSearchEnabled = true;
            webSearchButton.classList.add('web-search-enabled');
            webSearchButton.title = 'Web Search Enabled - Click to disable';
        }
    }

    // Clear attached file
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

    // Enhanced Markdown Rendering with Syntax Highlighting
    function renderAndUpdateTables(container, markdownContent) {
        // Configure marked options for better rendering
        marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: true,
            mangle: false,
            sanitize: false
        });

        const rawHtml = marked.parse(markdownContent);
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = rawHtml;

        // Wrap tables for responsive scrolling
        const tables = tempDiv.querySelectorAll('table');
        tables.forEach(table => {
            if (!table.parentElement || !table.parentElement.classList.contains('table-wrapper')) {
                const wrapper = document.createElement('div');
                wrapper.className = 'table-wrapper';
                table.parentNode.insertBefore(wrapper, table);
                wrapper.appendChild(table);
            }
        });

        // Add syntax highlighting to code blocks
        const codeBlocks = tempDiv.querySelectorAll('pre code');
        codeBlocks.forEach(block => {
            // Add line numbers
            const lines = block.textContent.split('\n');
            if (lines.length > 1) {
                block.classList.add('has-line-numbers');
            }
        });

        container.innerHTML = tempDiv.innerHTML;
        
        // Add interactive elements
        addSourceHoverTooltips(container);
        addCopyCodeButtons(container);
        
        updateCopyButtonVisibility();
    }

    // Add copy buttons to code blocks
    function addCopyCodeButtons(container) {
        const codeBlocks = container.querySelectorAll('pre');
        codeBlocks.forEach(block => {
            const copyButton = document.createElement('button');
            copyButton.className = 'code-copy-btn';
            copyButton.innerHTML = '<i class="fas fa-copy"></i>';
            copyButton.title = 'Copy code';
            
            copyButton.addEventListener('click', () => {
                const code = block.querySelector('code');
                if (code) {
                    copyToClipboard(code.textContent);
                    copyButton.innerHTML = '<i class="fas fa-check"></i>';
                    setTimeout(() => {
                        copyButton.innerHTML = '<i class="fas fa-copy"></i>';
                    }, 2000);
                }
            });
            
            block.style.position = 'relative';
            block.appendChild(copyButton);
        });
    }

    // Enhanced source tooltips with better positioning
    function addSourceHoverTooltips(container) {
        const citations = container.querySelectorAll('a[href^="http"]');
        
        citations.forEach((citation, index) => {
            if (citation.hasAttribute('data-tooltip-added')) return;
            
            citation.setAttribute('data-tooltip-added', 'true');
                citation.classList.add('source-citation');
            
            // Extract information
            let domain = '';
            let title = citation.textContent || 'External Link';
            let url = citation.href;
            
                try {
                const urlObj = new URL(url);
                    domain = urlObj.hostname.replace('www.', '');
                } catch (e) {
                    domain = 'External source';
                }
            
            // Create enhanced tooltip
            const tooltip = createEnhancedTooltip(index + 1, domain, title, url);
            citation._tooltip = tooltip;
            
            // Advanced positioning logic
            citation.addEventListener('mouseenter', (e) => {
                positionTooltip(e, tooltip);
                tooltip.classList.add('visible');
            });
            
            citation.addEventListener('mouseleave', () => {
                tooltip.classList.remove('visible');
            });
            
            // Touch support
            citation.addEventListener('touchstart', (e) => {
                e.preventDefault();
                positionTooltip(e, tooltip);
                tooltip.classList.add('visible');
                
                setTimeout(() => {
                    tooltip.classList.remove('visible');
                }, 3000);
            });
        });
    }

    function createEnhancedTooltip(index, domain, title, url) {
            const tooltip = document.createElement('div');
            tooltip.className = 'source-tooltip';
            
        tooltip.innerHTML = `
                <div class="tooltip-header">
                    <i class="fas fa-external-link-alt"></i>
                <span class="tooltip-title">Source ${index}</span>
                </div>
                <div class="tooltip-content">
                    <div class="tooltip-domain">${domain}</div>
                    <div class="tooltip-text">${title}</div>
                    <div class="tooltip-url">${url}</div>
                    <div class="tooltip-action">Click to open in new tab</div>
                </div>
            `;
            
            document.body.appendChild(tooltip);
        return tooltip;
    }

    function positionTooltip(event, tooltip) {
        const link = event.currentTarget;
        const linkRect = link.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        
        let left = linkRect.left;
        let top = linkRect.bottom + 5;
        
        // Horizontal positioning
        if (left + tooltipRect.width > viewportWidth - 20) {
            left = viewportWidth - tooltipRect.width - 20;
        }
        if (left < 20) {
            left = 20;
        }
        
        // Vertical positioning
        if (top + tooltipRect.height > viewportHeight - 20) {
            top = linkRect.top - tooltipRect.height - 5;
        }
        
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
    }

    function cleanupSourceTooltips() {
        const tooltips = document.querySelectorAll('.source-tooltip');
        tooltips.forEach(tooltip => tooltip.remove());
    }

    // Enhanced search initialization
    let currentEventSource = null;
    let currentResultsWrapper = null;
    let markdownBuffer = "";
    let reasoningBuffer = "";
    let chartInstance = null;
    let webSearchResults = null;

        function initializeNewSearch() {
        markdownBuffer = "";
        reasoningBuffer = "";
        webSearchResults = null;
        
        if (currentResultsWrapper) {
            currentResultsWrapper.innerHTML = '';
        }
        
        clearWebSearchSources();
        cleanupSourceTooltips();
        hideWebSearchProgress();
        
        const chartContainer = document.getElementById('chart-container');
        if (chartInstance) {
            chartInstance.destroy();
            chartInstance = null;
        }
        if (chartContainer) chartContainer.style.display = 'none';

        currentResultsWrapper = document.createElement('div');
        currentResultsWrapper.className = 'response-item';
        resultsContainer.appendChild(currentResultsWrapper);
        
        const placeholder = resultsContainer.querySelector('.placeholder-text');
        if (placeholder) placeholder.style.display = 'none';

        if (reasoningContainer) {
            reasoningContainer.style.display = 'none';
            reasoningContainer.classList.remove('fade-in');
        }
        if (reasoningContent) {
            reasoningContent.innerHTML = '';
            if (!isReasoningCollapsed) {
                reasoningContent.classList.remove('collapsed');
        }
        }
        if (toggleReasoningBtn && !isReasoningCollapsed) {
            toggleReasoningBtn.classList.remove('collapsed');
        }

        if (webSearchEnabled) {
            showWebSearchProgress();
        }

        thinkingIndicator.style.display = 'flex';
        errorContainer.textContent = '';
        errorContainer.style.display = 'none';
        downloadArea.style.display = 'none';
        if (downloadArea.firstChild) downloadArea.firstChild.remove();

        // Start animated thinking messages
        thinkingMessageIndex = 0;
        updateThinkingMessage();
        thinkingInterval = setInterval(updateThinkingMessage, 3000);
    }

    function updateThinkingMessage() {
        if (thinkingText && thinkingMessages.length > 0) {
            thinkingText.textContent = thinkingMessages[thinkingMessageIndex];
            thinkingMessageIndex = (thinkingMessageIndex + 1) % thinkingMessages.length;
        }
    }

    // Enhanced New Search button with better UX
    if (newSearchButton) {
        newSearchButton.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Add visual feedback
            newSearchButton.classList.add('clearing');
            setTimeout(() => {
                newSearchButton.classList.remove('clearing');
            }, 600);
            
            // Clear everything
            clearSearch();
            
            // Focus on input with slight delay for better UX
            setTimeout(() => {
                input.focus();
            }, 100);
            
            console.log('New search initiated - all content cleared');
        });
    }

    function clearSearch() {
        // Clear input
        input.value = '';
        input.style.height = '';
        
        // Clear results
        resultsContainer.innerHTML = '';
        resultsContainer.style.display = 'none';
        
        // Clear reasoning
        if (reasoningContainer) {
            reasoningContainer.style.display = 'none';
            reasoningContainer.classList.remove('fade-in');
        }
        if (reasoningContent) {
            reasoningContent.innerHTML = '';
        }
        
        // Clear error
        errorContainer.style.display = 'none';
        errorContainer.textContent = '';

        // Clear downloads
        downloadArea.style.display = 'none';
        downloadArea.innerHTML = '';
        
        // Clear chart
        if (chartInstance) {
            chartInstance.destroy();
            chartInstance = null;
        }
        const chartContainer = document.getElementById('chart-container');
        if (chartContainer) {
            chartContainer.style.display = 'none';
        }
        
        // Clear file
        clearAttachedFile();
        
        // Clear web search
        clearWebSearchSources();
        cleanupSourceTooltips();
        
        // Clear thinking
        if (thinkingIndicator) {
                thinkingIndicator.style.display = 'none';
        }
        
        // Clear intervals
        if (thinkingInterval) {
            clearInterval(thinkingInterval);
            thinkingInterval = null;
        }
        
        // Update UI
        updateCopyButtonVisibility();
    }

    // Enhanced form submission with better error handling
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const query = input.value.trim();
        if (!query) {
            displayError('Please enter a search query.');
            return;
        }

        // Save to history
        searchHistory.unshift({
            query: query,
            model: modelSelect.value,
            timestamp: new Date().toISOString(),
            webSearchEnabled: webSearchEnabled
        });
        
        // Keep only last 50 searches
        if (searchHistory.length > 50) {
            searchHistory = searchHistory.slice(0, 50);
        }
        
        // Save to localStorage
        localStorage.setItem('search-history', JSON.stringify(searchHistory));

        // Disable form during search
        input.disabled = true;
        modelSelect.disabled = true;
        newSearchButton.disabled = true;
        if (attachFileButton) attachFileButton.disabled = true;
        if (webSearchButton) webSearchButton.disabled = true;

        // Close any existing stream
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
        }

        initializeNewSearch();

        try {
            // For the image model, use standard fetch
            if (modelSelect.value === 'gpt-image-1') {
                await handleImageGeneration(query);
                return;
            }

            // For other models, use SSE streaming
            await handleStreamingSearch(query);

            } catch (error) {
            displayError('An unexpected error occurred. Please try again.');
            console.error('Search error:', error);
            } finally {
            // Re-enable form
            input.disabled = false;
            modelSelect.disabled = false;
            newSearchButton.disabled = false;
            if (attachFileButton) attachFileButton.disabled = false;
            if (webSearchButton) webSearchButton.disabled = false;
        }
    });

    // Enhanced image generation handler
    async function handleImageGeneration(query) {
        const requestData = {
            query: query,
            model: 'gpt-image-1'
        };

        if (uploadedFileBase64 && uploadedFileType) {
            requestData.uploaded_file_data = uploadedFileBase64;
            requestData.file_type = uploadedFileType.includes('image') ? 'image' : uploadedFileType;
        }

        try {
            const response = await fetch('/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to generate/edit image');
            }

            const data = await response.json();
            
            if (data.image_base64) {
                displayGeneratedImage(data.image_base64, data.is_edit);
            } else if (data.error) {
                displayError(data.error);
            }
        } catch (error) {
            displayError(error.message || 'Failed to generate/edit image');
        } finally {
                            thinkingIndicator.style.display = 'none';
            clearInterval(thinkingInterval);
        }
    }

    // Enhanced streaming search handler
    async function handleStreamingSearch(query) {
        const requestData = {
            query: query,
            model: modelSelect.value,
            web_search_enabled: webSearchEnabled
        };

        if (uploadedFileBase64 && uploadedFileType) {
            requestData.uploaded_file_data = uploadedFileBase64;
            requestData.file_type = uploadedFileType.includes('image') ? 'image' : 
                                   uploadedFileType.includes('pdf') ? 'pdf' : uploadedFileType;
        }

        currentEventSource = new EventSource('/search?' + new URLSearchParams({
            data: JSON.stringify(requestData)
        }));

        let hasReceivedContent = false;
        let chunkBuffer = '';
        let processTimeout = null;

        // Process buffered chunks with debouncing for better performance
        function processBufferedChunks() {
            if (chunkBuffer.length > 0) {
                markdownBuffer += chunkBuffer;
                renderAndUpdateTables(currentResultsWrapper, markdownBuffer);
                chunkBuffer = '';
            }
        }

        currentEventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                                if (data.error) {
                    displayError(data.error);
                    currentEventSource.close();
                    return;
                                }

                                if (data.web_search_results) {
                                        hideWebSearchProgress();
                    displayWebSearchSources(data.web_search_results);
                    return;
                                }

                                if (data.reasoning) {
                    if (!hasReceivedContent) {
                        hasReceivedContent = true;
                        thinkingIndicator.style.display = 'none';
                        clearInterval(thinkingInterval);
                        resultsContainer.style.display = 'block';
                        
                        if (reasoningContainer) {
                            reasoningContainer.style.display = 'block';
                                            reasoningContainer.classList.add('fade-in');
                                        }
                                    }
                    
                    reasoningBuffer += data.reasoning;
                    if (reasoningContent) {
                        renderAndUpdateTables(reasoningContent, reasoningBuffer);
                    }
                    return;
                                }

                                if (data.chunk) {
                    if (!hasReceivedContent) {
                        hasReceivedContent = true;
                        thinkingIndicator.style.display = 'none';
                        clearInterval(thinkingInterval);
                        resultsContainer.style.display = 'block';
                    }
                    
                    // Buffer chunks for performance
                    chunkBuffer += data.chunk;
                    
                    // Debounce rendering
                    clearTimeout(processTimeout);
                    processTimeout = setTimeout(processBufferedChunks, 50);
                }

                if (data.chart_config) {
                                    renderChart(data.chart_config);
                                }

                if (data.end_of_stream) {
                    // Process any remaining buffered chunks
                    processBufferedChunks();
                    
                    currentEventSource.close();
                    currentEventSource = null;
                    
                    // Clean up
                    clearTimeout(processTimeout);
                    
                    // Update UI
                    updateCopyButtonVisibility();
                    
                    // Save successful search
                    if (searchHistory.length > 0) {
                        searchHistory[0].success = true;
                        localStorage.setItem('search-history', JSON.stringify(searchHistory));
                    }
                }
            } catch (error) {
                console.error('Error processing stream data:', error);
            }
        };

        currentEventSource.onerror = (error) => {
            console.error('EventSource error:', error);
            
            if (!hasReceivedContent) {
                displayError('Connection lost. Please check your internet connection and try again.');
            }
            
            if (currentEventSource) {
                currentEventSource.close();
                currentEventSource = null;
            }
            
            thinkingIndicator.style.display = 'none';
            clearInterval(thinkingInterval);
            clearTimeout(processTimeout);
        };
    }

    // Enhanced error display with retry option
    function displayError(errorInput) {
        let errorMessage = 'An error occurred. Please try again.';
        
        if (typeof errorInput === 'string') {
            errorMessage = errorInput;
        } else if (typeof errorInput === 'object' && errorInput !== null) {
            if (errorInput.message) {
                errorMessage = errorInput.message;
            } else if (errorInput.error) {
                errorMessage = errorInput.error;
            }
        }

        errorContainer.textContent = errorMessage;
        errorContainer.style.display = 'block';
        thinkingIndicator.style.display = 'none';
        clearInterval(thinkingInterval);
        
        // Add retry button
        const retryButton = document.createElement('button');
        retryButton.className = 'retry-button';
        retryButton.innerHTML = '<i class="fas fa-redo"></i> Retry';
        retryButton.addEventListener('click', () => {
            errorContainer.style.display = 'none';
            form.dispatchEvent(new Event('submit'));
        });
        
        errorContainer.appendChild(retryButton);
        
        // Auto-hide error after 10 seconds
                    setTimeout(() => {
            if (errorContainer.style.display === 'block') {
                errorContainer.style.display = 'none';
            }
        }, 10000);
    }

    // Enhanced image display
    function displayGeneratedImage(base64Data, isEdit = false) {
        thinkingIndicator.style.display = 'none';
        clearInterval(thinkingInterval);
        resultsContainer.style.display = 'block';

        const img = document.createElement('img');
        img.src = `data:image/png;base64,${base64Data}`;
        img.className = 'generated-image';
        img.alt = isEdit ? 'Edited image' : 'Generated image';
        
        // Add loading animation
        img.style.opacity = '0';
        img.onload = () => {
            img.style.transition = 'opacity 0.5s ease-in';
            img.style.opacity = '1';
        };

        currentResultsWrapper.innerHTML = '';
        currentResultsWrapper.appendChild(img);

        // Enhanced download button
        const downloadBtn = document.createElement('a');
        downloadBtn.href = img.src;
        downloadBtn.download = isEdit ? 'edited_image.png' : 'generated_image.png';
        downloadBtn.className = 'download-button';
        downloadBtn.innerHTML = '<i class="fas fa-download"></i> Download Image';
        
        downloadArea.innerHTML = '';
        downloadArea.appendChild(downloadBtn);
        downloadArea.style.display = 'block';

        // Add copy image functionality
        const copyImageBtn = document.createElement('button');
        copyImageBtn.className = 'download-button';
        copyImageBtn.style.marginLeft = '10px';
        copyImageBtn.innerHTML = '<i class="fas fa-copy"></i> Copy Image';
        copyImageBtn.addEventListener('click', async () => {
            try {
                const blob = await fetch(img.src).then(r => r.blob());
                await navigator.clipboard.write([
                    new ClipboardItem({ 'image/png': blob })
                ]);
                copyImageBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
            setTimeout(() => {
                    copyImageBtn.innerHTML = '<i class="fas fa-copy"></i> Copy Image';
                }, 2000);
            } catch (error) {
                console.error('Failed to copy image:', error);
                displayError('Failed to copy image to clipboard');
            }
        });
        
        downloadArea.appendChild(copyImageBtn);
    }

    // Enhanced chart rendering
    function renderChart(chartConfig) {
        const chartContainer = document.getElementById('chart-container');
        const ctx = document.getElementById('interactive-chart').getContext('2d');
        
        if (chartInstance) {
            chartInstance.destroy();
        }

        try {
            // Enhanced chart configuration
            chartConfig.options = chartConfig.options || {};
            chartConfig.options.responsive = true;
            chartConfig.options.maintainAspectRatio = true;
            chartConfig.options.animation = {
                duration: 1000,
                easing: 'easeInOutQuart'
            };
            
            // Add interactivity
            chartConfig.options.interaction = {
                mode: 'nearest',
                intersect: false
            };
            
            // Enhanced tooltips
            chartConfig.options.plugins = chartConfig.options.plugins || {};
            chartConfig.options.plugins.tooltip = {
                backgroundColor: 'rgba(0, 0, 0, 0.8)',
                padding: 12,
                cornerRadius: 8,
                titleFont: { size: 14, weight: 'bold' },
                bodyFont: { size: 13 }
            };

            chartInstance = new Chart(ctx, chartConfig);
            if (chartContainer) {
                chartContainer.style.display = 'block';
                chartContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        } catch (e) {
            console.error("Error rendering chart:", e);
            const errorDiv = document.createElement('div');
            errorDiv.className = 'chart-render-error';
            errorDiv.textContent = `Chart Error: ${e.message}`;
            currentResultsWrapper.appendChild(errorDiv);
        }
    }

    // Performance optimization: Lazy load search history
    function loadSearchHistory() {
        try {
            const saved = localStorage.getItem('search-history');
            if (saved) {
                searchHistory = JSON.parse(saved);
            }
            } catch (error) {
            console.error('Failed to load search history:', error);
            searchHistory = [];
        }
    }

    // Initialize on page load
    loadSearchHistory();
    
    // Auto-save draft
    let draftTimeout;
    input.addEventListener('input', () => {
        clearTimeout(draftTimeout);
        draftTimeout = setTimeout(() => {
            localStorage.setItem('draft-query', input.value);
        }, 1000);
    });

    // Restore draft on load
    const draftQuery = localStorage.getItem('draft-query');
    if (draftQuery && !input.value) {
        input.value = draftQuery;
        autoResizeTextarea();
    }

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + K to focus search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            input.focus();
            input.select();
        }
        
        // Ctrl/Cmd + Enter to submit from anywhere
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            form.dispatchEvent(new Event('submit'));
        }
        
        // Escape to clear search
        if (e.key === 'Escape' && document.activeElement === input) {
            e.preventDefault();
            input.value = '';
            autoResizeTextarea();
        }
    });

    // Add smooth scroll behavior
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // Performance monitoring
    if ('PerformanceObserver' in window) {
        const perfObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                if (entry.duration > 100) {
                    console.warn('Slow operation detected:', entry.name, entry.duration + 'ms');
                }
            }
        });
        perfObserver.observe({ entryTypes: ['measure'] });
    }

    // Clean up on page unload
    window.addEventListener('beforeunload', () => {
        if (currentEventSource) {
            currentEventSource.close();
        }
        if (thinkingInterval) {
            clearInterval(thinkingInterval);
        }
    });

    console.log('Comet AI Search initialized successfully');
}); 