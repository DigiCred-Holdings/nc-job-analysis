import json
import boto3
from rapidfuzz import process, fuzz
from openai import OpenAI
import os
import re

### SKILL AND RETRIEVAL RELATED ###

def load_skills_dataset():
    # s3 = boto3.client('s3')
    # bucket_name = "storage"
    # file_key = "data/sd.json"
    # response = s3.get_object(Bucket=bucket_name, Key=file_key)
    # content = response['Body'].read().decode('utf-8')
    # return json.loads(content)

    with open(r"C:\\Users\\artio\\OneDrive\\Desktop\\backbone\\staging_registry.json", "r", encoding="utf-8") as file:
        return json.load(file)


_SPACE_RE = re.compile(r"\s+")

def normalize_code(code):
    s = str(code or "")
    s = s.replace("-", " ")
    s = _SPACE_RE.sub(" ", s).strip()
    return s

def normalized_label(title, code):
    t = _SPACE_RE.sub(" ", str(title or "").strip())
    c = normalize_code(code)
    return f"{t} {c}".casefold()

def rf_best_index(match):
    if isinstance(match, tuple) and len(match) >= 3:
        return match[2]
    if hasattr(match, "index") and not callable(getattr(match, "index")):
        return match.index
    raise TypeError(f"Unexpected RapidFuzz.extractOne() result type: {type(match)} -> {match}")

def standardize_courses(courses_list, source, sd):
    university_courses_candidates = []
    university_courses_ids = []

    for course in sd["C"]:
        candidate_label = normalized_label(course["data"]["title"], course["data"]["code"])
        university_courses_candidates.append(candidate_label)
        university_courses_ids.append(course["id"])

    if not university_courses_candidates:
        raise ValueError("No courses available in the skills dataset (sd['C'] is empty).")

    matched_ids = []
    grades_by_id = {}

    for entry in courses_list:
        if len(entry) < 2:
            raise ValueError(f"Each course must be [title, code] or [title, code, grade], got: {entry}")

        title, code = entry[0], entry[1]
        grade = entry[2] if len(entry) >= 3 else None

        normalized_code = normalize_code(code)

        query = normalized_label(title, normalized_code)

        match = process.extractOne(query, university_courses_candidates, scorer=fuzz.WRatio)
        if match is None:
            raise ValueError(f"Could not match course: {entry}")

        best_i = rf_best_index(match)
        course_id = university_courses_ids[best_i]
        matched_ids.append(course_id)

        if grade is not None:
            grades_by_id[course_id] = grade

    return matched_ids, grades_by_id

def retrieve_course_skill_data(target_ids, sd, grades_by_id=None):
    by_id = {c["id"]: c for c in sd["C"]}
    course_skill_data = []

    for target_id in target_ids:
        c = by_id.get(target_id)
        if not c:
            continue
        course_skill_data.append({
            "id": target_id,
            "title": c["data"]["title"],
            "code": c["data"]["code"],
            "description": c["data"]["desc"],
            "skills": c["dse"]["skills"],
            "skill_groups": c["dse"]["skill_groups"][0][0],
            "grade": (grades_by_id.get(target_id) if grades_by_id else None),
        })

    return course_skill_data

def sum_skill_groups(skill_groups):
    summed_skill_groups = {}
    for d in skill_groups:
        for key, value in d.items():
            summed_skill_groups[key] = summed_skill_groups.get(key, 0) + value
    return summed_skill_groups


### DOMAIN ANALYSIS ###

_SUBJECT_RE = re.compile(r"([A-Za-z]+)")

def subject_prefix_from_code(code):
    if not code:
        return None
    m = _SUBJECT_RE.match(str(code))
    return m.group(1).upper() if m else None

def infer_primary_domains(courses_skill_data):
    counts = {}
    for c in courses_skill_data:
        pref = subject_prefix_from_code(c.get("code"))
        if pref:
            counts[pref] = counts.get(pref, 0) + 1

    if not counts:
        return {
            "primary_subjects": [],
            "coverage": {},
            "primary_courses": [],
            "primary_skills": [],
            "primary_skill_groups": {}
        }

    total = sum(counts.values())
    sorted_subjects = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

    primary = [sorted_subjects[0][0]]
    top_cov = sorted_subjects[0][1] / total
    if top_cov < 0.6 and len(sorted_subjects) > 1:
        second_cov = (sorted_subjects[0][1] + sorted_subjects[1][1]) / total

        if second_cov >= 0.6 or top_cov < 0.45:
            primary.append(sorted_subjects[1][0])

    primary_courses = [c for c in courses_skill_data if subject_prefix_from_code(c.get("code")) in primary]
    primary_skills = [s for c in primary_courses for s in c.get("skills", [])]
    primary_skill_groups = sum_skill_groups([c.get("skill_groups", {}) for c in primary_courses]) if primary_courses else {}
    coverage = {k: v / total for k, v in counts.items()}

    return {
        "primary_subjects": primary,
        "coverage": coverage,
        "primary_courses": primary_courses,
        "primary_skills": primary_skills,
        "primary_skill_groups": primary_skill_groups
    }


def grade_to_gpa_like(grade):
    if grade is None:
        return None
    s = str(grade).strip().upper()

    letter_map = {
        "A+": 4.0, "A": 4.0, "A-": 3.7,
        "B+": 3.3, "B": 3.0, "B-": 2.7,
        "C+": 2.3, "C": 2.0, "C-": 1.7,
        "D+": 1.3, "D": 1.0, "D-": 0.7,
        "F": 0.0,
        "P": 3.0, "PASS": 3.0
    }
    if s in letter_map:
        return letter_map[s]

    try:
        val = float(s.rstrip("%"))
        if "%" in s or val > 5:
            return max(0.0, min(4.0, (val / 100.0) * 4.0))
        else:
            return max(0.0, min(4.0, val))
    except ValueError:
        return None


def is_poor_grade(grade, gpa_threshold=2.0, percent_threshold=70.0):
    if grade is None:
        return False
    s = str(grade).strip().upper()
    try:
        val = float(s.rstrip("%"))
        if "%" in s or val > 5:
            return val < percent_threshold
        else:
            return val < gpa_threshold
    except ValueError:
        gpa_like = grade_to_gpa_like(grade)
        return (gpa_like is not None) and (gpa_like < 2.0)


### OPENAI API RELATED ###

def init_client():
    base_dir = os.path.dirname(__file__) 
    parent_dir = os.path.abspath(os.path.join(base_dir, ".."))
    key_path = os.path.join(parent_dir, "OPENAI_KEY.txt")
    return OpenAI(api_key=open(key_path).read().strip())


def chatgpt_send_messages_json(messages, json_schema_wrapper, model, client):
    json_response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": json_schema_wrapper["name"],
                "strict": True,
                "schema": json_schema_wrapper["schema"]
            }
        }
    )
    json_response_content = json_response.choices[0].message.content
    return json.loads(json_response_content)


def get_prompt_plus_schema(
    skills,
    skill_groups,
    course_descriptions_with_grades,
    low_grade_courses,
    primary_subjects,
    primary_skill_groups,
    primary_skills,
    primary_course_examples,
    primary_coverage
):
    prompt = [
        {"role": "system", "content": '''
            You are summarizing a university-level student's abilities and skills.

            You will receive:
            1) A list of individual skills the student has mastered
            2) A list of skill groups with their counts as an object
            3) A list of completed courses with descriptions and grades
            4) A list of courses with low grades (if any)
            5) The primary subject area(s) derived from the majority of courses,
               with their skill groups, representative skills, and example courses.

            Style & Voice:
            - Address the student directly in the second person ("you", "your").
            - Do NOT use third-person phrasing like "the student" or "they".
            - Output must be exactly TWO sentences separated by a full stop (no numbering or bullets).

            Task:
            - Sentence 1 (strengths): A quick sentence were you say what the student has focused on main, use words like "You have a great focus on", "Your indept study in/of", "You excel in subject x". Focus on the primary subject area(s) and groups, such as "engineering in area x". Name at least one notable skill group the student excels at.
              and one specific skill learned.
            - Sentence 2 (improvements): If the studnets grades are visibly low, recomend to retake some courses and focus on developing on missed skill to achieve x. Otherwise, be constructive and forward-looking.
                 In first option, * Only suggest retaking courses if the grades show a clear pattern of low performance
                (e.g., several Cs/Ds/Fs across courses). If you do recommend retaking, prefer classes from the primary area
                and mention at most two, using the format: "Improving or retaking the class `<TITLE> (<CODE>)` could possibly boost your skill set."
                 In second option, * If grades are mostly solid with only isolated low marks, DO NOT recommend retakes—stick to constructive next steps.     
                * Recommend *specific* personal projects, internships, research assistant roles, open-source contributions, ideas, don't be too vague, mention one, but a good idea.
                you can also mention portfolio pieces, or targeted practice in a named skill group from the primary area.
             
        '''},
        {"role": "user", "content": f'''
            OVERALL:
            - skills: {skills}
            - skill_groups: {skill_groups}
            - courses (title, code, grade, description): {course_descriptions_with_grades}
            - low_grade_courses: {low_grade_courses}

            PRIMARY FOCUS:
            - primary_subjects: {primary_subjects}
            - primary_skill_groups: {primary_skill_groups}
            - primary_skills (examples): {primary_skills[:15]}
            - primary_course_examples: {primary_course_examples}
            - primary_coverage (fraction by subject): {primary_coverage}
        '''}
    ]

    json_schema = {
        "name": "student_summary",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Exactly two sentences in second person, separated by a full stop: one for strengths, one for improvements.",
                    "maxLength": 1600
                }
            },
            "required": ["summary"],
            "additionalProperties": False
        }
    }

    return prompt, json_schema


def chatgpt_summary(
    skills,
    skill_groups,
    course_descriptions_with_grades,
    low_grade_courses,
    primary_subjects,
    primary_skill_groups,
    primary_skills,
    primary_course_examples,
    primary_coverage,
    model
):
    prompt, json_schema = get_prompt_plus_schema(
        skills,
        skill_groups,
        course_descriptions_with_grades,
        low_grade_courses,
        primary_subjects,
        primary_skill_groups,
        primary_skills,
        primary_course_examples,
        primary_coverage
    )
    summary = chatgpt_send_messages_json(prompt, json_schema, model, init_client())
    return summary["summary"]


### LAMBDA HANDLER ###

def lambda_handler(event, context):
    summary_gpt_model = "gpt-4.1-nano"

    sd = load_skills_dataset()

    standerdized_course_ids, grades_by_id = standardize_courses(event["coursesList"], event["source"], sd)
    courses_skill_data = retrieve_course_skill_data(standerdized_course_ids, sd, grades_by_id)

    student_skills = [skill for course in courses_skill_data for skill in course["skills"]]
    student_skill_groups = sum_skill_groups([course["skill_groups"] for course in courses_skill_data])
    course_descriptions_with_grades = [
        (course["title"], course["code"], course.get("grade"), course["description"])
        for course in courses_skill_data
    ]

    primary = infer_primary_domains(courses_skill_data)
    primary_subjects = primary["primary_subjects"]
    primary_course_examples = [(c["title"], c["code"]) for c in primary["primary_courses"][:4]]
    primary_skills = primary["primary_skills"]
    primary_skill_groups = primary["primary_skill_groups"]
    primary_coverage = primary["coverage"]


    low_grade_primary = [
        {"title": c["title"], "code": c["code"], "grade": c.get("grade")}
        for c in primary["primary_courses"]
        if is_poor_grade(c.get("grade"))
    ]
    low_grade_other = [
        {"title": c["title"], "code": c["code"], "grade": c.get("grade")}
        for c in courses_skill_data
        if is_poor_grade(c.get("grade")) and c not in primary["primary_courses"]
    ]
    low_grade_courses = (low_grade_primary + low_grade_other)[:2]

    summary = chatgpt_summary(
        student_skills,
        student_skill_groups,
        course_descriptions_with_grades,
        low_grade_courses,
        primary_subjects,
        primary_skill_groups,
        primary_skills,
        primary_course_examples,
        primary_coverage,
        summary_gpt_model
    )

    return {
        'status': 200,
        'body': {
            "summary": summary,
            "student_skill_list": list(set(student_skills)),
            "student_skill_groups": student_skill_groups,
            "course_id_list": standerdized_course_ids,
        }
    }
