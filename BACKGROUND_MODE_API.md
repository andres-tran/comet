# Background Mode API Documentation

## Overview

The Background Mode API enables asynchronous processing of long-running AI tasks using OpenRouter models. This is particularly useful for models like `perplexity/sonar-deep-research` that can take several minutes to complete complex analyses.

## Key Features

- **Asynchronous Processing**: Submit tasks and poll for results later
- **Real-time Streaming**: Stream results as they are generated
- **Task Management**: List, cancel, and monitor multiple tasks
- **Robust Error Handling**: Automatic cleanup and timeout management
- **Thread-safe**: Supports concurrent task processing

## API Endpoints

### 1. Start Background Task

**POST** `/search/background`

Start a new background task for processing.

#### Request Body
```json
{
  "query": "Your question or prompt",
  "model": "perplexity/sonar-deep-research",
  "web_search_enabled": true,
  "uploaded_file_data": "base64_encoded_file_data (optional)",
  "file_type": "image|pdf (optional)"
}
```

#### Response
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "created_at": "2025-05-26T19:30:00.000Z",
  "model": "perplexity/sonar-deep-research",
  "query_preview": "Your question or prompt..."
}
```

### 2. Get Task Status

**GET** `/tasks/{task_id}`

Retrieve the current status and results of a task.

#### Response
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "model": "perplexity/sonar-deep-research",
  "query": "Your question or prompt...",
  "status": "completed",
  "created_at": "2025-05-26T19:30:00.000Z",
  "started_at": "2025-05-26T19:30:05.000Z",
  "completed_at": "2025-05-26T19:32:30.000Z",
  "progress": 100,
  "duration": 145.5,
  "chunks_count": 150,
  "chunks": [...],  // Only included when status is completed/failed
  "result": {
    "total_chunks": 150,
    "content_length": 5000,
    "summary": "First 500 characters of response..."
  }
}
```

#### Status Values
- `queued`: Task is waiting to be processed
- `in_progress`: Task is currently being processed
- `completed`: Task finished successfully
- `failed`: Task encountered an error
- `cancelled`: Task was cancelled by user

### 3. Stream Task Results

**GET** `/tasks/{task_id}/stream`

Stream results as Server-Sent Events (SSE) as they are generated.

#### Response Format (SSE)
```
data: {"chunk": "This is part of the response..."}

data: {"status": "in_progress", "progress": 45}

data: {"reasoning": "Thinking about the problem..."}

data: {"end_of_stream": true, "status": "completed"}
```

### 4. Cancel Task

**DELETE** `/tasks/{task_id}`

Cancel a running task.

#### Response
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancel_requested",
  "message": "Task cancellation requested"
}
```

### 5. List Tasks

**GET** `/tasks`

List all background tasks with optional filtering.

#### Query Parameters
- `status`: Filter by status (queued, in_progress, completed, failed, cancelled)
- `limit`: Maximum number of tasks to return (default: 50)

#### Response
```json
{
  "tasks": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "model": "perplexity/sonar-deep-research",
      "query": "Your question...",
      "status": "completed",
      "created_at": "2025-05-26T19:30:00.000Z",
      "duration": 145.5,
      "progress": 100
    }
  ],
  "total": 1
}
```

## Usage Examples

### Python Example

```python
import requests
import time

# Start a task
response = requests.post('http://localhost:8080/search/background', json={
    'query': 'Analyze the impact of AI on healthcare',
    'model': 'perplexity/sonar-deep-research'
})
task = response.json()
task_id = task['id']

# Poll for status
while True:
    response = requests.get(f'http://localhost:8080/tasks/{task_id}')
    status = response.json()
    
    print(f"Progress: {status['progress']}% - Status: {status['status']}")
    
    if status['status'] in ['completed', 'failed', 'cancelled']:
        break
    
    time.sleep(2)

# Get final results
if status['status'] == 'completed':
    print(f"Task completed in {status['duration']}s")
    print(f"Response: {status['result']['summary']}")
```

### JavaScript Example

```javascript
// Start a task
const response = await fetch('http://localhost:8080/search/background', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        query: 'Explain quantum computing',
        model: 'openai/gpt-4.5-preview'
    })
});
const { id } = await response.json();

// Stream results
const eventSource = new EventSource(`http://localhost:8080/tasks/${id}/stream`);

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.chunk) {
        document.getElementById('output').append(data.chunk);
    } else if (data.end_of_stream) {
        eventSource.close();
        console.log('Task completed!');
    }
};

eventSource.onerror = (error) => {
    console.error('Stream error:', error);
    eventSource.close();
};
```

## Best Practices

1. **Use Background Mode for Long Tasks**: Models like `perplexity/sonar-deep-research` can take 2-5 minutes
2. **Implement Exponential Backoff**: When polling, increase intervals to reduce server load
3. **Handle Timeouts**: Tasks are cleaned up after 1 hour
4. **Stream for Real-time Updates**: Use the streaming endpoint for better UX
5. **Cancel Unneeded Tasks**: Free up resources by cancelling tasks you no longer need

## Error Handling

### Common Error Responses

```json
{
  "error": "Task not found"
}
```

```json
{
  "error": "Invalid model: unsupported-model"
}
```

```json
{
  "error": "Task already completed"
}
```

## Configuration

### Environment Variables

- `MAX_TASK_AGE`: Maximum age of tasks before cleanup (default: 3600 seconds)
- `TASK_CLEANUP_INTERVAL`: How often to clean up old tasks (default: 300 seconds)
- `TASK_EXECUTOR_WORKERS`: Number of concurrent background workers (default: 5)

## Limitations

- Tasks are stored in memory and will be lost on server restart
- Maximum task age is 1 hour
- Limited to 5 concurrent background tasks
- No persistence layer (consider adding Redis for production)

## Future Enhancements

1. **Persistence**: Add Redis or database storage for tasks
2. **Webhooks**: Support callbacks when tasks complete
3. **Batch Processing**: Submit multiple queries in one request
4. **Priority Queues**: Support task prioritization
5. **Rate Limiting**: Add per-user rate limits
6. **Progress Estimation**: Better progress tracking based on model and query complexity 