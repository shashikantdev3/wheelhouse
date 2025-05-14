import requests
import json

def test_infrastructure_overview():
    url = "http://localhost:5000/submit_issue"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"issue_description": "Give me the overview of our infrastructure"}
    
    try:
        response = requests.post(url, headers=headers, data=data)
        print("\n=== Testing Infrastructure Overview ===")
        print(f"Status Code: {response.status_code}")
        print("\nResponse:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {str(e)}")

def test_knowledge_query():
    url = "http://localhost:5000/submit_issue"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"issue_description": "What is the difference between Docker and Kubernetes?"}
    
    try:
        print("\n=== Testing Knowledge Query ===")
        response = requests.post(url, headers=headers, data=data)
        print(f"Status Code: {response.status_code}")
        print("\nResponse:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    test_infrastructure_overview()
    test_knowledge_query() 