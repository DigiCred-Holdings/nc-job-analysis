import json
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))  # Adjust the path to include the parent directory
import lambda_function
from unittest.mock import patch, MagicMock

def test_lambda_handler():
    event = {
        "coursesList": [
            ["Prin of Financial Accounting", "ACC 120"],
            ["Prin of Financial Acct II", "ACC 122"],
            ["Accounting Software Appl", "ACC 150"]
        ],
        "source": "Cape Fear Community College"
    }
    context = {}

    # mock_response = {'vectors': ['mocked_vector']}
    # with patch('boto3.client') as mock_client:
    #     mock_s3vector = MagicMock()
    #     mock_s3vector.get_vectors.return_value = mock_response
    #     mock_client.return_value = mock_s3vector

    # Patch the init_client function to return a mock OpenAI client
    with patch('lambda_function.init_client') as mock_init_client:
        mock_client = MagicMock()
        mock_init_client.return_value = mock_client

        mock_response = {
            'choices': [{
                'message': {
                    'content': {
                        "summary": "Mocked summary of skills",
                    }
                }
            }],
            'status': 200
        }
        # convert mock response to the expected format
        mock_response = json.dumps(mock_response)
        mock_client.chat.completions.create.return_value = mock_response

        response = lambda_function.lambda_handler(event, context)

    assert response['status'] == 200
    assert 'body' in response

if __name__ == "__main__":
    test_lambda_handler()