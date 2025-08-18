import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import lambda_function
from unittest.mock import patch, MagicMock

def test_lambda_handler():
    event = {
        "coursesList": [
            ["College Composition I", "ENGL-1010", "B"],
            ["College Composition II", "ENGL-2020", "B"],
            ["College Algebra", "MATH-1400", "B"],
            ["Fundamentals of Statistics", "STAT-2050", "B"],
            ["U.S. & Wyoming History", "HIST-1251", "A"],
            ["American & Wyoming Government", "POLS-1000", "B"],
            ["Principles of Biology", "BIOL-1000", "B"],
            ["Introductory Chemistry", "CHEM-1000", "B"],
            ["Public Speaking", "COJO-1010", "A"],
            ["General Psychology", "PSYC-1000", "B"],

            ["Introduction to Criminal Justice", "CRMJ-1001", "A"],
            ["Criminal Law", "CRMJ-2210", "B"],
            ["Criminology", "CRMJ-2400", "A"],
            ["Research Methods", "CRMJ-2465", "B"],
            ["Criminal Courts & Processes", "CRMJ-3110", "B"],
            ["Correctional Theory & Practice", "CRMJ-3350", "B"],
            ["Issues in Policing", "CRMJ-3490", "A"],
            ["Ethics in Administration of Justice", "CRMJ-4200", "B"],

            ["Juvenile Delinquency", "CRMJ-3250", "A"],
            ["Deviant Behavior", "CRMJ-3400", "B"],
            ["Drugs & the Criminal Justice System", "CRMJ-3500", "B"],
            ["Criminal Legal Procedure", "CRMJ-4140", "A"],
            ["Community-Based Corrections", "CRMJ-4150", "B"],
            ["Gender and Crime", "CRMJ-4540", "B"]
        ],

        "source": "University of Wyoming"
    }
    context = {}

    # mock_response = {'vectors': ['mocked_vector']}
    # with patch('boto3.client') as mock_client:
    #     mock_s3vector = MagicMock()
    #     mock_s3vector.get_vectors.return_value = mock_response
    #     mock_client.return_value = mock_s3vector

    response = lambda_function.lambda_handler(event, context)

    assert response['status'] == 200
    assert 'body' in response

    return response

if __name__ == "__main__":
    print(test_lambda_handler())