import json
import boto3
from openai import OpenAI
import os


### SKILL AND RETRIEVAL RELATED ###

def load_skills_dataset():
    s3_client = boto3.client('s3')
    # Get bucket key from environment variable S3 URI e.g. s3://digicred-credential-analysis/dev/staging_registry.json
    registry_uri = os.environ['REGISTRY_S3_URI']
    bucket, key = registry_uri.replace("s3://", "").split("/", 1)
    response = s3_client.get_object(Bucket=bucket, Key=key)
    if response['ResponseMetadata']['HTTPStatusCode'] != 200:
        raise Exception(f"Failed to retrieve data from S3: {response['ResponseMetadata']['HTTPStatusCode']}")
    content = response['Body'].read().decode('utf-8')

    return json.loads(content)

def course_codes_match(code1, code2):
    return str.lower(code1.strip()) == str.lower(code2.strip())

def standardize_courses(courses_list, source, sd):
    # Find the source abbreviation in the skills dataset
    for code, alts in sd["lookup"]["universities"].items():
        if str.lower(source) in [str.lower(alt) for alt in alts]:
            src_code = code
            break
    
    # Filter the courses based on the source code
    all_courses = [course for course in sd["C"] if course["data"]["src"] == src_code]
    matches = []
    for course in courses_list:
        # Use the second element in the course list element as the course code
        course_code = str.lower(course[1])
        code_matches = [course for course in all_courses if course_codes_match(course["data"]["code"], course_code)]
        if code_matches:
            # If a match is found, return the course ID
            matches.append(code_matches[0]["id"])
        
    return matches

def retrieve_course_skill_data(target_ids, sd):
    course_skill_data = []
    
    for target_id in target_ids:
        for course in sd["C"]:
            if course["id"] == target_id: 
                course_skill_data.append({
                    "id": target_id,
                    "title": course["data"]["title"],
                    "code": course["data"]["code"],
                    "description": course["data"]["desc"],
                    "skills": course["dse"]["skills"],
                    "skill_groups":  course["dse"]["skill_groups"][0][0]
                })
    return course_skill_data

def sum_skill_groups(skill_groups):
    summed_skill_groups = {}

    for d in skill_groups:
        for key, value in d.items():
            summed_skill_groups[key] = summed_skill_groups.get(key, 0) + value

    return summed_skill_groups


### OPENAI API RELATED ###

def init_client():
    # Get OpenAI key from aws secrets manager and return OpenAI client
    secrets_client = boto3.client('secretsmanager')
    secret_response = secrets_client.get_secret_value(SecretId=os.environ['OPENAI_API_KEY_SECRET'])
    secret_string = secret_response['SecretString']
    api_key = json.loads(secret_string).get('OPENAI_API_KEY')
    return OpenAI(api_key=api_key)

def chatgpt_send_messages_json(messages, json_schema_wrapper, model, client):
    json_response = client.chat.completions.create(
        model=model,
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


def get_prompt_plus_schema(skills, skill_groups, course_descriptions): # Could be saved seperetely or in s3?
    prompt = [
        {"role": "system", "content": '''
            You are summarizing a university-level student's abilities and skills.
            You will receive:
            1) A list of individual skills the student has mastered
            2) A list of skill groups with their counts as an object
            3) A list of completed courses with descriptions

            Your task:
            - Write a short summary (max 3 sentences) of the student’s strengths.
            - Mention at least one notable skill group they excel in.
            - Highlight at least one specific skill learned in a course (referencing course context).
            - Keep the tone positive, in the style of: "You excel greatly in ..., most notably your accounting class taught you ..."
            - Avoid lists; keep it narrative and concise.

            Output only the 3-sentence summary.
            
            Example output:
            "You excel greatly in business, administration, and law, most notably your accounting courses taught you to analyze and interpret financial information effectively. Your strength in applying accounting systems and software, such as general ledger and payroll software, stands out. The 'Accounting Software Applications' course specifically enhanced your ability to use accounting packages to solve complex problems efficiently."
        '''},
        {"role": "user", "content": f'''
            1) {skills}
            2) {skill_groups}
            3) {course_descriptions}
        '''}
    ]

    json_schema = {
        "name": "student_summary",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "A short positive narrative summary of the student's strengths, maximum 3 sentences (~170 tokens).",
                    "maxLength": 1200,
                    "pattern": r"^([^.!?]*[.!?]){1,3}$"
                }
            },
            "required": ["summary"],
            "additionalProperties": False
        }
    }

    return prompt, json_schema


def chatgpt_summary(skills, skill_groups, course_descriptions, model):
    prompt, json_schema = get_prompt_plus_schema(skills, skill_groups, course_descriptions)
    summary = chatgpt_send_messages_json(prompt, json_schema, model, init_client())
    return summary["summary"]

from time import perf_counter
def _timeit(f):
    def wrap(*a, **kw):
        t=perf_counter(); r=f(*a, **kw)
        print(f"{f.__name__} took {(perf_counter()-t)*1000:.3f} ms")
        return r
    return wrap

@_timeit
def lambda_handler(event, context):
    summary_gpt_model = "gpt-4.1-nano"

    if type(event["body"]) is str:
        body = json.loads(event["body"])
    else:
        body = event["body"]
    if not body:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid input: body cannot be empty.'})
        }
    
    ()
    if "coursesList" not in body or "source" not in body:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid input: coursesList and source are required.'})
        }


    sd = load_skills_dataset()
    standerdized_course_ids = standardize_courses(body["coursesList"], body["source"], sd)
    if not standerdized_course_ids:
        return {
            'statusCode': 404,
            'body': json.dumps({'error': 'No matching courses found.'})
        }

    courses_skill_data = retrieve_course_skill_data(standerdized_course_ids, sd)
    student_skills = [skill for course in courses_skill_data for skill in course["skills"]]
    student_skill_groups = sum_skill_groups([course["skill_groups"] for course in courses_skill_data])
    summary = chatgpt_summary(student_skills, student_skill_groups, [(course["title"], course["description"]) for course in courses_skill_data], summary_gpt_model)

    response = {
        'status': 200,
        'body': json.dumps({
            "summary": summary,
            "student_skill_list": student_skills,
            "student_skill_groups": student_skill_groups,
            "course_id_list": standerdized_course_ids
        })
    }
    return response