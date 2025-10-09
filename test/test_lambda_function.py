import json
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))  # Adjust the path to include the parent directory
import lambda_function
from unittest.mock import patch, MagicMock

def test_lambda_handler():
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/path/to/resource",
        "rawQueryString": "parameter1=value1&parameter1=value2&parameter2=value",
        "cookies": [
        "cookie1",
        "cookie2"
        ],
        "headers": {
        "Header1": "value1",
        "Header2": "value1,value2"
        },
        "queryStringParameters": {
        "parameter1": "value1,value2",
        "parameter2": "value"
        },
        "requestContext": {
        "accountId": "123456789012",
        "apiId": "api-id",
        "authentication": {
        "clientCert": {
        "clientCertPem": "CERT_CONTENT",
        "subjectDN": "www.example.com",
        "issuerDN": "Example issuer",
        "serialNumber": "a1:a1:a1:a1:a1:a1:a1:a1:a1:a1:a1:a1:a1:a1:a1:a1",
        "validity": {
        "notBefore": "May 28 12:30:02 2019 GMT",
        "notAfter": "Aug  5 09:36:04 2021 GMT"
        }
        }
        },
        "authorizer": {
        "jwt": {
        "claims": {
        "claim1": "value1",
        "claim2": "value2"
        },
        "scopes": [
        "scope1",
        "scope2"
        ]
        }
        },
        "domainName": "id.execute-api.us-east-1.amazonaws.com",
        "domainPrefix": "id",
        "http": {
        "method": "POST",
        "path": "/path/to/resource",
        "protocol": "HTTP/1.1",
        "sourceIp": "192.168.0.1/32",
        "userAgent": "agent"
        },
        "requestId": "id",
        "routeKey": "$default",
        "stage": "$default",
        "time": "12/Mar/2020:19:03:58 +0000",
        "timeEpoch": 1583348638390
        },
        "body": {
        "coursesList": [
        [
        "College Composition I",
        "ENGL 1010"
        ],
        [
        "College Algebra",
        "MATH 1400"
        ],
        [
        "U.S. & Wyoming History",
        "HIST 1251"
        ],
        [
        "Principles of Biology",
        "BIOL 1000"
        ],
        [
        "College Composition II",
        "ENGL 2020"
        ],
        [
        "Fundamentals of Statistics",
        "STAT 2050"
        ],
        [
        "American & Wyoming Government",
        "POLS 1000"
        ],
        [
        "Introductory Chemistry",
        "CHEM 1000"
        ],
        [
        "General Psychology",
        "PSYC 1000"
        ],
        [
        "Public Speaking",
        "COJO 1010"
        ],
        [
        "Introduction to Criminal Justice",
        "CRMJ 1001"
        ],
        [
        "Criminal Law",
        "CRMJ 2210"
        ],
        [
        "Criminology",
        "CRMJ 2400"
        ],
        [
        "Research Methods",
        "CRMJ 2465"
        ],
        [
        "Criminal Courts & Processes",
        "CRMJ 3110"
        ],
        [
        "Correctional Theory & Practice",
        "CRMJ 3350"
        ],
        [
        "Issues in Policing",
        "CRMJ 3490"
        ],
        [
        "Ethics in Administration of Justice",
        "CRMJ 4200"
        ],
        [
        "Juvenile Delinquency",
        "CRMJ 3250"
        ],
        [
        "Deviant Behavior",
        "CRMJ 3400"
        ],
        [
        "Drugs & the Criminal Justice System",
        "CRMJ 3500"
        ],
        [
        "Criminal Legal Procedure",
        "CRMJ 4140"
        ],
        [
        "Community-Based Corrections",
        "CRMJ 4150"
        ],
        [
        "Gender and Crime",
        "CRMJ 4540"
        ]
        ],
        "source": "University of Wyoming"
        },
        "pathParameters": {
        "parameter1": "value1"
        },
        "isBase64Encoded": True,
        "stageVariables": {
        "stageVariable1": "value1",
        "stageVariable2": "value2"
        }
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