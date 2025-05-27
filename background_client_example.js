#!/usr/bin/env node
/**
 * JavaScript/Node.js client example for background mode API
 * 
 * Usage:
 *   npm install axios
 *   node background_client_example.js
 */

const axios = require('axios');

const BASE_URL = 'http://localhost:8080';

// Helper function to sleep
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Start a background task
 */
async function startBackgroundTask(query, model = 'perplexity/sonar-deep-research') {
    try {
        const response = await axios.post(`${BASE_URL}/search/background`, {
            query,
            model,
            web_search_enabled: true
        });

        const data = response.data;
        console.log(`Started task ${data.id} with model ${data.model}`);
        console.log(`Status: ${data.status}`);
        console.log(`Created at: ${data.created_at}`);
        
        return data.id;
    } catch (error) {
        console.error('Error starting task:', error.response?.data || error.message);
        return null;
    }
}

/**
 * Poll task status until completion
 */
async function pollTaskStatus(taskId, interval = 2000) {
    console.log(`\nPolling task ${taskId}...`);
    
    while (true) {
        try {
            const response = await axios.get(`${BASE_URL}/tasks/${taskId}`);
            const data = response.data;
            const status = data.status;
            const progress = data.progress || 0;
            
            // Show progress
            const barLength = 40;
            const filledLength = Math.floor(barLength * progress / 100);
            const bar = '█'.repeat(filledLength) + '-'.repeat(barLength - filledLength);
            process.stdout.write(`\r[${bar}] ${progress}% - Status: ${status}`);
            
            if (['completed', 'failed', 'cancelled'].includes(status)) {
                console.log(); // New line after progress
                return data;
            }
            
            await sleep(interval);
        } catch (error) {
            console.error('\nError getting task status:', error.response?.data || error.message);
            return null;
        }
    }
}

/**
 * Stream task results as they arrive
 */
async function streamTaskResults(taskId) {
    console.log(`\nStreaming results for task ${taskId}...`);
    
    return new Promise((resolve, reject) => {
        let content = '';
        
        // Using fetch for SSE support (requires Node.js 18+)
        // For older versions, use EventSource library
        const controller = new AbortController();
        
        fetch(`${BASE_URL}/tasks/${taskId}/stream`, {
            signal: controller.signal
        })
        .then(response => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            
            function processText(text) {
                const lines = text.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            
                            if (data.chunk) {
                                content += data.chunk;
                                process.stdout.write(data.chunk);
                            } else if (data.end_of_stream) {
                                console.log(`\n\nStream ended with status: ${data.status}`);
                                resolve(content);
                                return true;
                            }
                        } catch (e) {
                            // Ignore JSON parse errors
                        }
                    }
                }
                return false;
            }
            
            function pump() {
                return reader.read().then(({ done, value }) => {
                    if (done) {
                        resolve(content);
                        return;
                    }
                    
                    buffer += decoder.decode(value, { stream: true });
                    
                    // Process complete lines
                    const lines = buffer.split('\n\n');
                    buffer = lines.pop() || '';
                    
                    for (const chunk of lines) {
                        if (processText(chunk)) {
                            controller.abort();
                            return;
                        }
                    }
                    
                    return pump();
                });
            }
            
            return pump();
        })
        .catch(error => {
            console.error('Error streaming results:', error.message);
            reject(error);
        });
    });
}

/**
 * Cancel a running task
 */
async function cancelTask(taskId) {
    try {
        const response = await axios.delete(`${BASE_URL}/tasks/${taskId}`);
        console.log(`Task ${taskId} cancellation requested`);
        return true;
    } catch (error) {
        console.error('Error cancelling task:', error.response?.data || error.message);
        return false;
    }
}

/**
 * List recent tasks
 */
async function listRecentTasks(limit = 10) {
    try {
        const response = await axios.get(`${BASE_URL}/tasks`, {
            params: { limit }
        });
        
        const { tasks, total } = response.data;
        
        console.log(`\nRecent tasks (showing ${tasks.length} of ${total}):`);
        console.log('-'.repeat(80));
        
        for (const task of tasks) {
            const created = new Date(task.created_at);
            console.log(`ID: ${task.id.substring(0, 8)}... | Model: ${task.model} | Status: ${task.status}`);
            console.log(`   Query: ${task.query}`);
            console.log(`   Created: ${created.toLocaleString()}`);
            if (task.duration) {
                console.log(`   Duration: ${task.duration.toFixed(2)}s`);
            }
            console.log();
        }
    } catch (error) {
        console.error('Error listing tasks:', error.response?.data || error.message);
    }
}

/**
 * Main example
 */
async function main() {
    console.log('=== OpenRouter Background Mode Example (JavaScript) ===\n');
    
    // Example 1: Simple query with polling
    console.log('Example 1: Simple query with status polling');
    console.log('-'.repeat(40));
    
    const query1 = 'Write a comprehensive analysis of renewable energy technologies';
    const taskId1 = await startBackgroundTask(query1);
    
    if (taskId1) {
        const result = await pollTaskStatus(taskId1);
        
        if (result && result.status === 'completed') {
            console.log('\nTask completed successfully!');
            console.log(`Total chunks: ${result.chunks_count || 0}`);
            console.log(`Duration: ${result.duration?.toFixed(2) || 0}s`);
            
            if (result.result?.summary) {
                console.log(`\nSummary: ${result.result.summary.substring(0, 200)}...`);
            }
        }
    }
    
    // Example 2: Streaming results
    console.log('\n\nExample 2: Streaming results as they arrive');
    console.log('-'.repeat(40));
    
    const query2 = 'Explain machine learning in simple terms';
    const taskId2 = await startBackgroundTask(query2, 'openai/gpt-4.5-preview');
    
    if (taskId2) {
        try {
            await streamTaskResults(taskId2);
        } catch (e) {
            console.error('Streaming error:', e.message);
        }
    }
    
    // Example 3: List recent tasks
    console.log('\n\nExample 3: List recent tasks');
    console.log('-'.repeat(40));
    await listRecentTasks(5);
    
    // Example 4: Cancel a long-running task
    console.log('\n\nExample 4: Cancel a long-running task');
    console.log('-'.repeat(40));
    
    const query3 = 'Write a detailed 10,000 word essay about the history of computing';
    const taskId3 = await startBackgroundTask(query3);
    
    if (taskId3) {
        console.log('Waiting 3 seconds before cancelling...');
        await sleep(3000);
        
        if (await cancelTask(taskId3)) {
            const finalStatus = await pollTaskStatus(taskId3);
            console.log(`Final status: ${finalStatus.status}`);
        }
    }
}

// Run the example
if (require.main === module) {
    main().catch(console.error);
} 