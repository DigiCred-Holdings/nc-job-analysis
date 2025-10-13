import json
import time
import boto3
from openai import OpenAI
import os
import re


def build_query(course_title_code_list, school_code):
    # Build the SQL query to fetch course data based on course titles and codes
    
    # TODO: Parameterize the query to prevent SQL injection
    query = f"""
    SELECT id, data_title, data_code, data_desc, dse_skills
    FROM courses
    WHERE data_src = '{school_code}'
        AND data_code IN ({', '.join([f"'{code}'" for _, code in course_title_code_list])});
    """
    
    return query

def get_course_data_from_db(course_title_code_list, school_name):
    client = boto3.client('athena')   # create athena client
    
    school_name_code_lookup = {
        "university of wyoming": "UWYO",
    }
    
    school_code = school_name_code_lookup.get(school_name.lower())
    
    query = build_query(course_title_code_list, school_code)
    
    # Start the Athena query execution
    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            'Database': os.environ['ATHENA_DATABASE'],
            'Catalog': "AwsDataCatalog"
        }
    )
    print("Query execution started:", response)

    query_execution_id = response['QueryExecutionId']
    
    while True:
        response = client.get_query_execution(QueryExecutionId=query_execution_id)
        state = response['QueryExecution']['Status']['State']
        
        if state in ['SUCCEEDED', 'FAILED', 'CANCELLED']:  # (optional) checking the status 
            break
        
        time.sleep(1)  # Poll every 1 seconds
    
    # Here, you can handle the response as per your requirement
    if state == 'SUCCEEDED':
        # Fetch the results if necessary
        result_data = client.get_query_results(QueryExecutionId=query_execution_id)
        print(result_data)
    else:
        print(f"Query failed in state: {state}")
        return []

def get_course_data(course_title_code_list, school_name):
    db_response = get_course_data_from_db(course_title_code_list, school_name)
    return db_response
    
    # for target_id in target_ids:
    #     for course in sd["C"]:
    #         if course["id"] == target_id: 
    #             course_skill_data.append({
    #                 "id": target_id,
    #                 "title": course["data"]["title"],
    #                 "code": course["data"]["code"],
    #                 "description": course["data"]["desc"],
    #                 "skills": course["dse"]["skills"],
    #                 "skill_groups":  course["dse"]["skill_groups"][0][0]
    #             })
    # return course_skill_data

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

def compile_highlight(summary, skill_groups, skills, course_ids):

    # Because there was little testing period for the initial skill extraction, some skills contain defects, like starting with "15. ", they are removed here, but this will be fixed in future staging registries. 
    def clean_skill(s):
        return re.sub(r"^\s*[\d]+[.)]\s*", "", str(s)).strip()

    def pluralize(n, word):
        return f"{n} {word if n == 1 else word + 's'}"

    def pct(part, whole, i): # Percentage calculation
        if whole <= 0:
            return "0%"
        return (
            f"{(part / whole) * 100:.0f}% of your skill base from the courses"
            if i == 1
            else f"{(part / whole) * 100:.0f}%" # Show the description, only for the first skill group
        )

    # Sort skill groups
    total_count = sum(skill_groups.values())
    top_groups = sorted(skill_groups.items(), key=lambda kv: kv[1], reverse=True)[:5]

    # Build significant skills
    group_lines = []
    for i, (group, count) in enumerate(top_groups, start=1):
        line1 = f"{i}. {group}"
        line2 = f"   -> {pluralize(count, 'skill')} ({pct(count, total_count, i)})"
        group_lines.append(f"{line1}\n{line2}\n")

    sig_skills_block = "Significant skill areas:\n" + "\n".join(group_lines).rstrip()

    # Build standout skills
    seen = set()
    standout = []
    for s in skills:
        cs = clean_skill(s)
        if cs and cs.lower() not in seen:
            seen.add(cs.lower())
            standout.append(cs)
        if len(standout) >= 5:
            break

    # Format standout list 
    standout_sentence = ""
    if standout:
        quoted = [f"'{s}'" for s in standout]
        if len(quoted) > 1:
            quoted_str = ", ".join(quoted[:-1]) + f", and {quoted[-1]}"
        else:
            quoted_str = quoted[0]
        standout_sentence = f" Some of your standout skills are {quoted_str}."

    # Final 'totals' sentence
    totals_sentence = ""
    if course_ids or skills or skill_groups:
        totals_sentence = (
            f"\n\nOverall, we have analyzed {len(course_ids)} of your courses "
            f"and found {len(skills)} skills! That's over a range of {len(skill_groups)} skill groups."
        )
        totals_sentence += standout_sentence

    # Build the highlight
    highlight = f"{summary}\n\n{sig_skills_block}{totals_sentence}".strip()
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
    summary_gpt_model = "gpt-4.1-nano"

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
        

    courses_skill_data = get_course_data(body["coursesList"], body["source"])
    student_skills = list(set([skill for course in courses_skill_data for skill in course["skills"]])) # list(set(, insures that that there are no repeated skills
    student_skill_groups = sum_skill_groups([course["skill_groups"] for course in courses_skill_data])
    summary = chatgpt_summary(student_skills, student_skill_groups, [(course["title"], course["description"]) for course in courses_skill_data], summary_gpt_model)
    
    analyzed_course_ids = [course["id"] for course in courses_skill_data]
    highlight = compile_highlight(summary, student_skill_groups, student_skills, analyzed_course_ids)

    response = {
        'status': 200,
        'body': {
            "summary": summary,
            "student_skill_list": student_skills,
            "student_skill_groups": student_skill_groups,
            "course_id_list": analyzed_course_ids,
            "highlight": highlight
        }
    }
    return response
