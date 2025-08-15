import json
import boto3
from rapidfuzz import process, fuzz
from openai import OpenAI
import os


### SKILL AND RETRIEVAL RELATED ###

def load_skills_dataset():
    s3_client = boto3.client('s3')

    bucket_name = "digicred-credential-analysis"
    file_key = "dev/staging_registry.json"

    response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
    content = response['Body'].read().decode('utf-8')

    return json.loads(content)

def standardize_courses(courses_list, source, sd):
    ### Standardize the source
    src_code = ""
    for code, alts in sd["lookup"]["universities"].items():
        if str.lower(source) in [str.lower(alt) for alt in alts]:
            src_code = code
            break

    ### Find all courses from specified source
    university_courses_candidates = []
    university_courses_ids = []

    for course in sd["C"]:
        if course["data"]["src"] == src_code:
            university_courses_candidates.append(str.lower(course["data"]["to_query"]))
            university_courses_ids.append(course["id"])

    ### Match student's courses to courses from specified soruce (simply concatinates code and title)
    matched_ids = []

    for query_course in courses_list:
        query = str.lower(query_course[0] + " " + query_course[1])
        best_i = process.extractOne(query, university_courses_candidates, scorer=fuzz.WRatio)[2]
        matched_ids.append(university_courses_ids[best_i])

    return matched_ids

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
    # Get OpenAI key from aws secrets manager or environment variable
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set.")
    # Initialize OpenAI client with the API key
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

    sd = load_skills_dataset()
    standerdized_course_ids = standardize_courses(event["coursesList"], event["source"], sd)
    courses_skill_data = retrieve_course_skill_data(standerdized_course_ids, sd)
    student_skills = [skill for course in courses_skill_data for skill in course["skills"]]
    student_skill_groups = sum_skill_groups([course["skill_groups"] for course in courses_skill_data])
    summary = chatgpt_summary(student_skills, student_skill_groups, [(course["title"], course["description"]) for course in courses_skill_data], summary_gpt_model)

    response = {
        'status': 200,
        'body': {
            "summary": summary,
            "student_skill_list": student_skills,
            "student_skill_groups": student_skill_groups,
            "course_id_list": standerdized_course_ids
        }
    }
    return response