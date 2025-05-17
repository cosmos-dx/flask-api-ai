from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber
import uuid
import json
import re
import os
import google.generativeai as genai
from typing import List, Optional
from pydantic import BaseModel, Field, ValidationError




app = Flask(__name__)
CORS(app) 

def extract_data_from_pdf(pdf_file):
    all_text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                all_text += text + "\n"
    return all_text

def generate_unique_id():
    return str(uuid.uuid4())

def save_to_db(unique_id, resume_text=None, questions=None, db_path='test_db.json'):
    if os.path.exists(db_path):
        with open(db_path, 'r') as f:
            try:
                db = json.load(f)
            except json.JSONDecodeError:
                db = {}
    else:
        db = {}

    if unique_id not in db:
        db[unique_id] = {
            "resume": resume_text or "",
            "questions": {},
            "solutions": [],
            "question_index": 0,
            "subquestion_index": -1,
            "current_answer": [],
            "answers": [],
            "question_asked": "",
            "job_description":""
        }

    if resume_text:
        db[unique_id]["resume"] = resume_text
    if questions:
        db[unique_id]["questions"] = [q.model_dump() for q in questions]

    with open(db_path, 'w') as f:
        json.dump(db, f, indent=4)




class InterviewQuestion(BaseModel):
    question: str = Field(..., description="The main interview question.")
    subquestions: List[str] = Field(
        default_factory=list,
        description="A list of 1-2 subquestions related to the main question."
    )

class InterviewQuestionsList(BaseModel):
    questions: List[InterviewQuestion] = Field(
        ...,
        description="A list containing exactly 5 interview questions (1 intro, 4 technical)."
    )

try:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY environment variable not set.")
    genai.configure(api_key=GOOGLE_API_KEY)
except ValueError as e:
    print(f"Error: {e}")
    print("Please set the GOOGLE_API_KEY environment variable before running the script.")


def generate_questions_from_resume(
    resume_text: str,
    job_description: str,
    model_name: str = "gemini-1.5-flash-latest", # Or "gemini-1.5-pro-latest" for potentially higher quality
) -> Optional[List[InterviewQuestion]]:
    """
    Generates technical interview questions from resume text using a Gemini model.

    Args:
        resume_text: The full text of the candidate's resume.
        model_name: The Gemini model to use.

    Returns:
        A list of InterviewQuestion objects if successful, None otherwise.
    """
    if not GOOGLE_API_KEY:
        print("API key not configured. Cannot proceed.")
        return None
    generation_config = genai.types.GenerationConfig(
        response_mime_type="application/json"
    )
    model = genai.GenerativeModel(model_name, generation_config=generation_config)

  
    prompt = f"""
    You are an expert Technical interviewer. Your task is to analyze the provided resume text and generate exactly 6 interview questions:
    1. One introductory question: This should be a general question to start the interview and allow the candidate to introduce themselves or their resume.

    2. Next Five technical questions: These MUST be directly derived from the skills, experiences, projects, or technologies mentioned in the resume. The questions should test the candidate’s understanding and practical experience and should be medium level—somewhat tricky but accessible.

    Return a valid JSON object, where:
    - Each key is a stringified number from "1" to "6".
    - The value for each key is an object with:
    - "question": a string (the main question).
    - "answer": an empty string.

    The output format must look like this:

    {{
    "1": {{
        "question": "Can you briefly walk me through your resume and highlight your key experiences?",
        "answer": ""
    }},
    "2": {{
        "question": "Your resume mentions experience with Python. Can you describe a project where Python was central to the solution?",
        "answer": ""
    }}
    // ... up to "6"
    }}

    Resume Text:
    ---
    {resume_text}
    ---

    Now, generate the questions based on the resume above in the specified JSON object format.
    Do NOT include any text or explanation before or after the JSON.

    """

    try:
        print(f"Sending request to Gemini model ({model_name})...")
        response = model.generate_content(prompt)
        response_json_text = response.text

        parsed_output = InterviewQuestionsList.model_validate_json(response_json_text)
        
        if len(parsed_output.questions) != 6:
            print(f"Warning: Gemini returned {len(parsed_output.questions)} questions instead of 6. Please check the prompt or model behavior.")

        return parsed_output.questions

    except genai.types.generation_types.BlockedPromptException as e:
        print(f"Error: The prompt was blocked. {e}")
        return None
    except genai.types.generation_types.StopCandidateException as e:
        print(f"Error: Generation stopped unexpectedly. {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Failed to decode JSON response from Gemini: {e}")
        print(f"Problematic Gemini Response Text:\n{response_json_text}")
        return None
    except ValidationError as e:
        print(f"Error: Gemini response did not match the expected Pydantic model structure: {e}")
        print(f"Problematic Gemini Response Text (that caused validation error):\n{response_json_text}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

@app.route('/upload_resume', methods=['POST'])
def upload_resume():
    if 'resume' not in request.files:
        return jsonify({"error": "No resume file part"}), 400

    resume_file = request.files['resume']
    if resume_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    job_description = request.form.get('job_description', None)

    try:
        resume_text = extract_data_from_pdf(resume_file)
        unique_id = generate_unique_id()
        generated_questions = generate_questions_from_resume(resume_text,job_description)
        if generated_questions:
            print("\n--- Successfully Generated Interview Questions ---")
            save_to_db(unique_id,resume_text, questions=generated_questions)


        else:
            print("\n--- Failed to Generate Interview Questions ---")
        return jsonify({"user_id": unique_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/ask_question', methods=['GET'])
def get_next_question():
    with open("test_db.json", "r") as file:
        data = json.load(file)
    user_id = request.form.get('id')
    user_data = data[user_id]
    question_index = user_data["question_index"]
    subquestion_index = user_data["subquestion_index"]
    questions = user_data["questions"]

    #edge case for last question handle later
    if question_index == len(questions) and subquestion_index == len(questions[question_index][subquestions]):
         return jsonify({"user_id": user_id, "message": "All questions have been asked"})

    current_question = questions[question_index]
    subquestions = current_question.get("subquestions", [])

    if subquestion_index == -1:
        next_question = current_question["question"]
        if subquestions:
            user_data["subquestion_index"] = 0
        else:
            user_data["question_index"] += 1
            user_data["subquestion_index"] = -1
    elif subquestion_index < len(subquestions):

        next_question = subquestions[subquestion_index]
        user_data["subquestion_index"] += 1

        if user_data["subquestion_index"] >= len(subquestions):
            user_data["question_index"] += 1
            user_data["subquestion_index"] = -1
    else:
        user_data["question_index"] += 1
        user_data["subquestion_index"] = -1
        return get_next_question(data, user_id)
   
    user_data['question_asked']=next_question #to check what is the current question asked
    with open("test_db.json", "w") as file:
        json.dump(data, file, indent=4)
    return jsonify({"user_id": user_id, "question": next_question})



def evaluate_answer(question: str, resume: str, user_answer: str, model_name="gemini-1.5-flash-latest") -> tuple[bool, str]:
    prompt = f"""
    You are an AI Technical Interview Evaluator. The question below was generated earlier based on the user's resume. Evaluate if the candidate's answer is relevant and technically sufficient.

    Resume:
    ---
    {resume}
    ---

    Question:
    "{question}"

    Candidate's Answer:
    "{user_answer}"

    Now, evaluate the candidate's answer. Be respectful and respond like a normal interviewer giving concise, constructive feedback.

    Your response must be in the following JSON format:
    {{
        "result": "Adequate" or "Inadequate",
        "feedback": "Short, friendly, and slightly technical comment acknowledging the answer. For example: 'Ok! Going great, let's move on to the next question.'"
    }}
    
    The feedback should be based on the quality and relevance of the answer. Be encouraging but also professional. Keep it brief, to the point, and relevant to the topic.

    Only return the JSON. Do not add any explanation or extra commentary outside the JSON format.
    Do not write anything like ``` json ``` anything instead of final result
    """

    try:
        generation_config = genai.types.GenerationConfig(response_mime_type="text/plain")
        model = genai.GenerativeModel(model_name, generation_config=generation_config)
        response = model.generate_content(prompt)

        raw_text = response.text.strip()
        cleaned_text = re.sub(r"```(?:json)?", "", raw_text).strip()
        evaluation = json.loads(cleaned_text)

        result = evaluation.get("result", "").strip().lower() == "adequate"
        feedback = evaluation.get("feedback", "").strip()
        if result:
            return (True, feedback)
        else:
            return (False, feedback)

    except Exception as e:
        print(f"Error during AI evaluation: {e}")
        return False, "An error occurred during evaluation."

@app.route('/give_answer', methods=['POST'])
def update_user_response():
    req_data = request.get_json()
    user_id = req_data.get('id')
    user_answer = req_data.get('answer')
    with open("test_db.json", "r") as f:
        data = json.load(f)

    user_data = data.get(user_id)
    if not user_data:
        print(f"No data found for user_id: {user_id}")
        return

    question = user_data['question_asked']
    resume = user_data['resume']
    is_satisfactory, feedback = evaluate_answer(question, resume, user_answer)
    user_data["satisfactory_till_now"] = is_satisfactory
    user_data['answers'].append(user_answer)

    with open('test_db.json', "w") as f:
        json.dump(data, f, indent=4)
    return jsonify({"user_id": user_id, "feedback": feedback})




@app.route('/provide_report', methods=['POST'])
def provide_report():
    user_id = request.form.get('id')  
    
    with open("test_db.json", "r") as f:
        data = json.load(f)

    req_data = data.get(user_id)
    if not req_data:
        return jsonify({"error": "User ID not found"}), 404

    questions = req_data.get('questions', [])
    answers = req_data.get('answers', [])

    result = []
    answer_index = 0

    for q in questions:
        entry = {
            "question": q["question"],
            "answer": answers[answer_index] if answer_index < len(answers) else "",
            "subquestions": []
        }
        answer_index += 1

        for sub in q.get("subquestions", []):
            entry["subquestions"].append({
                "subquestion": sub,
                "answer": answers[answer_index] if answer_index < len(answers) else ""
            })
            answer_index += 1

        result.append(entry)

    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)
