import json
import time
import boto3
from openai import OpenAI
import os
import re


def build_query(course_title_code_list, school_code):
    # Build the SQL query to fetch course data based on course titles and codes
    query = f"""
    SELECT id, data_title, data_code, data_desc, dse_skills
    FROM courses
    WHERE data_src = '{school_code}'
        AND data_code IN ({', '.join(['?']*len(course_title_code_list))})
    """
    return query

# Helper function to extract VarCharValue from Athena query result
def get_var_char_values(d):
    return [obj['VarCharValue'] for obj in d['Data']]

def get_course_data_from_db(course_title_code_list, school_name):
    client = boto3.client('athena')   # create athena client
    
    school_name_code_lookup = {
        "university of wyoming": "UWYO",
    }
    school_code = school_name_code_lookup.get(school_name.lower())
    
    query = build_query(course_title_code_list, school_code)
    
    print("Executing query on school code:", school_code)
    # Start the Athena query execution
    start_query_response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            'Database': os.environ['ATHENA_DATABASE']
        },
        ResultConfiguration={
            'OutputLocation': os.environ['ATHENA_OUTPUT_S3']
        },
        ExecutionParameters=[code for _, code in course_title_code_list]
    )
    print("Query execution started:", start_query_response)

    query_execution_id = start_query_response['QueryExecutionId']
    
    # Poll the query status until it completes
    while True:
        status_response = client.get_query_execution(QueryExecutionId=query_execution_id)
        state = status_response['QueryExecution']['Status']['State']
        reason = status_response['QueryExecution']
        
        if state == 'SUCCEEDED':
            break
        elif state in ['FAILED', 'CANCELLED']:
            raise Exception(f"Query {state}: {reason}")
        
        time.sleep(0.2)  # Poll every 0.2 seconds
        
    results_response = client.get_query_results(QueryExecutionId=query_execution_id)
    
    if not results_response or 'ResultSet' not in results_response or 'Rows' not in results_response['ResultSet']:
        return []
 
    # Unpack the results into a list of dictionaries, using the header row as keys
    header, *rows = results_response['ResultSet']['Rows']
    header = get_var_char_values(header)
    unpacked_results = [dict(zip(header, get_var_char_values(row))) for row in rows]    
    return unpacked_results

def get_course_data(course_title_code_list, school_name):
    db_courses = get_course_data_from_db(course_title_code_list, school_name)
    course_skill_data = []
    
    for _, course_code in course_title_code_list:
        code_matches = [course for course in db_courses if course['data_code'] == course_code]
        if code_matches:
            course = code_matches[0]  # Take the first match if multiple
            course_skill_data.append({
                "id": course['id'],
                "title": course['data_title'],
                "code": course['data_code'],
                "description": course['data_desc'],
                "skills": course['dse_skills'].strip("[]").split(", ") if course['dse_skills'] else []
            })
    
    print(f"Fetched {len(course_skill_data)} courses with skills from DB.")
    
    if len(course_skill_data) < len(course_title_code_list):
        missing_count = len(course_title_code_list) - len(course_skill_data)
        missing_codes = set(code for _, code in course_title_code_list) - set(course['code'] for course in course_skill_data)
        print(f"Warning: {missing_count} courses were not found in the database. Missing codes: {missing_codes}")
    
    return course_skill_data

### OPENAI API RELATED ###

def init_client():
    # Get OpenAI key from aws secrets manager and return OpenAI client
    secrets_client = boto3.client('secretsmanager')
    secret_response = secrets_client.get_secret_value(SecretId=os.environ['OPENAI_API_KEY_SECRET'])
    secret_string = secret_response['SecretString']
    api_key = json.loads(secret_string).get('OPENAI_API_KEY')
    return OpenAI(api_key=api_key)

def chatgpt_send_messages_json(messages, json_schema_wrapper, client):
    json_response = client.chat.completions.create(
        model=os.environ.get('OPENAI_GPT_MODEL', 'gpt-4.1-nano'),
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": json_schema_wrapper["name"],
                "strict": True,
                "schema": json_schema_wrapper["schema"]
            }
        }
    )
    # Access the content directly from the response object
    json_response_content = json_response.choices[0].message.content
    return json.loads(json_response_content)


def get_prompt_plus_schema(course_skills_data): # Could be saved separately or in s3?
    course_descriptions = [(course["title"], course["description"]) for course in course_skills_data]
    skills_by_course = [(course["title"], course["skills"]) for course in course_skills_data]
    prompt = [
        {"role": "system", "content": '''
            You are summarizing a university-level student's abilities and skills.
            You will receive:
            1) A list of completed courses with descriptions
            2) A list of skills associated with those courses

            Your task:
            - Write a short summary (max 3 sentences) of the student's strengths.
            - Mention at least one notable skill group they excel in.
            - Highlight at least one specific skill learned in a course (referencing course context).
            - Keep the tone positive, in the style of: "Your coursework has given you skills in ... Notably your accounting class taught you ..."
            - Avoid lists; keep it narrative and concise.

            Output only the 3-sentence summary.
        '''},
        {"role": "user", "content": f'''
            1) {course_descriptions}
            2) {skills_by_course}
        '''}
    ]

    json_schema = {
        "name": "student_summary",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "A short positive narrative summary of the student's strengths.",
                    "maxLength": 1200,
                    "pattern": r"^([^.!?]*[.!?]){1,3}$"
                }
            },
            "required": ["summary"],
            "additionalProperties": False
        }
    }

    return prompt, json_schema


def chatgpt_summary(course_skills_data):
    prompt, json_schema = get_prompt_plus_schema(course_skills_data)
    summary = chatgpt_send_messages_json(prompt, json_schema, init_client())
    return summary["summary"]

def compile_highlight(summary, course_skills_data):

    # Helper to clean skill strings of leading numbers/formatting
    def clean_skill(s):
        return re.sub(r"^\s*[\d]+[.)]\s*", "", str(s)).strip()

    # Build a list of standout skills by selecting the most common skills across courses
    skill_counts = {}
    for course in course_skills_data:
        skills = [clean_skill(s) for s in course["skills"]]
        for skill in skills:
            skill_counts[skill] = skill_counts.get(skill, 0) + 1

    # Pick the top 3 most common skills as standout skills
    sorted_skills = sorted(skill_counts.items(), key=lambda item: item[1], reverse=True)
    top_3_skills = [s[0] for s in sorted_skills[:3]]
    
    # Format standout list 
    standout_sentence = ""
    quoted = [f"'{s}'" for s in top_3_skills]
    if len(quoted) > 1:
        quoted_str = ", ".join(quoted[:-1]) + f", and {quoted[-1]}"
    else:
        quoted_str = quoted[0]
    standout_sentence = f" Some of your standout skills are {quoted_str}."

    # Final 'totals' sentence
    totals_sentence = ""
    totals_sentence = (
        f"\n\nOverall, we have analyzed {len(course_skills_data)} of your courses "
        f"and found {len(skill_counts.keys())} skills!"
    )
    totals_sentence += standout_sentence

    # Build the highlight
    highlight = f"{summary}\n\n{totals_sentence}".strip()
    return highlight

from time import perf_counter
def _timeit(f):
    def wrap(*a, **kw):
        t=perf_counter(); r=f(*a, **kw)
        print(f"{f.__name__} took {(perf_counter()-t)*1000:.3f} ms")
        return r
    return wrap

@_timeit
def lambda_handler(event, context):
    if type(event["body"]) is str:
        body = json.loads(event["body"])
    else:
        body = event["body"]
    if not body:
        return {
            'statusCode': 400,
            'body': 'Invalid input: body cannot be empty.'
        }
    
    ()
    if "coursesList" not in body or "source" not in body:
        return {
            'statusCode': 400,
            'body': 'Invalid input: coursesList and source are required.'
        }
        

    course_skills_data = get_course_data(body["coursesList"], body["source"])
    summary = chatgpt_summary(course_skills_data)
    
    highlight = compile_highlight(summary, course_skills_data)
    
    analyzed_course_ids = [course["id"] for course in course_skills_data]
    response = {
        'status': 200,
        'body': {
            "summary": summary,
            "course_ids": analyzed_course_ids,
            "highlight": highlight
        }
    }
    return response
