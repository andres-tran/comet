#!/usr/bin/env python3
"""
Example client for using the background mode API with OpenRouter models.
This demonstrates how to:
1. Start a background task
2. Poll for status
3. Stream results as they arrive
4. Cancel a task
"""

import requests
import json
import time
import sys
from datetime import datetime

BASE_URL = "http://localhost:8080"

def start_background_task(query, model="perplexity/sonar-deep-research"):
    """Start a background task and return the task ID."""
    response = requests.post(
        f"{BASE_URL}/search/background",
        json={
            "query": query,
            "model": model,
            "web_search_enabled": True
        }
    )
    
    if response.status_code != 200:
        print(f"Error starting task: {response.text}")
        return None
    
    data = response.json()
    print(f"Started task {data['id']} with model {data['model']}")
    print(f"Status: {data['status']}")
    print(f"Created at: {data['created_at']}")
    return data['id']

def poll_task_status(task_id, interval=2):
    """Poll task status until completion."""
    print(f"\nPolling task {task_id}...")
    
    while True:
        response = requests.get(f"{BASE_URL}/tasks/{task_id}")
        
        if response.status_code != 200:
            print(f"Error getting task status: {response.text}")
            return None
        
        data = response.json()
        status = data['status']
        progress = data.get('progress', 0)
        
        # Print progress bar
        bar_length = 40
        filled_length = int(bar_length * progress / 100)
        bar = '█' * filled_length + '-' * (bar_length - filled_length)
        print(f"\r[{bar}] {progress}% - Status: {status}", end='', flush=True)
        
        if status in ['completed', 'failed', 'cancelled']:
            print()  # New line after progress bar
            return data
        
        time.sleep(interval)

def stream_task_results(task_id):
    """Stream results as they become available."""
    print(f"\nStreaming results for task {task_id}...")
    
    response = requests.get(
        f"{BASE_URL}/tasks/{task_id}/stream",
        stream=True
    )
    
    if response.status_code != 200:
        print(f"Error streaming results: {response.text}")
        return
    
    content = ""
    for line in response.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                try:
                    data = json.loads(line[6:])
                    
                    # Handle different data types
                    if 'chunk' in data:
                        content += data['chunk']
                        print(data['chunk'], end='', flush=True)
                    elif 'status' in data and 'progress' in data:
                        # Status update (could show in UI)
                        pass
                    elif data.get('end_of_stream'):
                        print(f"\n\nStream ended with status: {data.get('status')}")
                        break
                        
                except json.JSONDecodeError:
                    pass
    
    return content

def cancel_task(task_id):
    """Cancel a running task."""
    response = requests.delete(f"{BASE_URL}/tasks/{task_id}")
    
    if response.status_code != 200:
        print(f"Error cancelling task: {response.text}")
        return False
    
    print(f"Task {task_id} cancellation requested")
    return True

def list_recent_tasks(limit=10):
    """List recent tasks."""
    response = requests.get(f"{BASE_URL}/tasks?limit={limit}")
    
    if response.status_code != 200:
        print(f"Error listing tasks: {response.text}")
        return
    
    data = response.json()
    tasks = data['tasks']
    
    print(f"\nRecent tasks (showing {len(tasks)} of {data['total']}):")
    print("-" * 80)
    
    for task in tasks:
        created = datetime.fromisoformat(task['created_at'])
        print(f"ID: {task['id'][:8]}... | Model: {task['model']} | Status: {task['status']}")
        print(f"   Query: {task['query']}")
        print(f"   Created: {created.strftime('%Y-%m-%d %H:%M:%S')}")
        if task['duration']:
            print(f"   Duration: {task['duration']:.2f}s")
        print()

def main():
    """Example usage of background mode."""
    print("=== OpenRouter Background Mode Example ===\n")
    
    # Example 1: Simple query with polling
    print("Example 1: Simple query with status polling")
    print("-" * 40)
    
    query = "Write a comprehensive analysis of the economic impact of climate change on global supply chains"
    task_id = start_background_task(query)
    
    if task_id:
        # Poll for completion
        result = poll_task_status(task_id)
        
        if result and result['status'] == 'completed':
            print(f"\nTask completed successfully!")
            print(f"Total chunks: {result.get('chunks_count', 0)}")
            print(f"Duration: {result.get('duration', 0):.2f}s")
            
            # Show summary
            if result.get('result'):
                print(f"\nSummary: {result['result'].get('summary', '')[:200]}...")
    
    # Example 2: Streaming results
    print("\n\nExample 2: Streaming results as they arrive")
    print("-" * 40)
    
    query2 = "Explain quantum computing in simple terms"
    task_id2 = start_background_task(query2, model="openai/gpt-4.5-preview")
    
    if task_id2:
        # Stream results instead of polling
        content = stream_task_results(task_id2)
    
    # Example 3: List recent tasks
    print("\n\nExample 3: List recent tasks")
    print("-" * 40)
    list_recent_tasks(5)
    
    # Example 4: Cancel a long-running task
    print("\n\nExample 4: Cancel a long-running task")
    print("-" * 40)
    
    query3 = "Write a 50,000 word novel about space exploration"
    task_id3 = start_background_task(query3)
    
    if task_id3:
        print("Waiting 5 seconds before cancelling...")
        time.sleep(5)
        
        if cancel_task(task_id3):
            # Check final status
            final_status = poll_task_status(task_id3)
            print(f"Final status: {final_status['status']}")

if __name__ == "__main__":
    main() 