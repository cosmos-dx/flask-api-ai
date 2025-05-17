from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber
import uuid
import json
import re
import os
import google.generativeai as genai
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ValidationError, RootModel
import random
from pymongo import MongoClient

os.environ["GOOGLE_API_KEY"]="Your_API_Key"

app = Flask(__name__)
CORS(app) 


mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)

try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)
    
db = client["adzat_interview"] 
collection = db["interview_data"] 

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

def save_to_db(unique_id, resume_text=None, questions=None):
    doc = collection.find_one({"user_id": unique_id})

    if not doc:
        doc = {
            "user_id": unique_id,
            "resume": resume_text or "",
            "questions_list": questions or [],
            "solutions": [],
            "qna": [],
            "question_index": 0,
            "current_answer": "",
            "current_question": "",
            "subquestion": "",
            "subquestion_count": 2,
            "job_description": "",
            "satisfactory_till_now": True,
            "current_subquestion": ""
        }
        collection.insert_one(doc)
    else:
        update_fields = {}
        if resume_text:
            update_fields["resume"] = resume_text
        if questions:
            update_fields["questions_list"] = questions

        if update_fields:
            collection.update_one({"user_id": unique_id}, {"$set": update_fields})


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
) -> List:
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
    1.  One introductory question: This should be a general question to start the interview and allow the candidate to introduce themselves or their resume.
    2.  Next Five technical questions: These questions MUST be directly derived from the skills, experiences, projects, or technologies mentioned in the resume and job_description provided. They should probe the candidate's understanding and practical experience and these questions should be on medium level little tricky and little easy.

    Job Description is  {job_description}
    
    The output MUST be a valid JSON object that strictly adheres to the following structure:
    A main JSON object with a single key "questions".
    The value of "questions" should be an array of 6 strings.
    Each String is a question itself.


    Example of the exact JSON structure required:
    [
        Introduction Question,
        Technical Question,
        Technical Question,
        ...
    ]

    Do NOT include any text, explanations, or markdown formatting before or after the JSON object.
    The entire response should be ONLY the JSON object described.

    Resume Text:
    ---
    {resume_text}
    ---
    Now, generate the questions based on the resume above in the specified JSON format.
    """

    try:
        print(f"Sending request to Gemini model ({model_name})...")
        response = model.generate_content(prompt)
        response_json_text = response.text
        data = json.loads(response_json_text)
        # print(data)
        print(type(data['questions']))
        

        # if len(parsed_output) != 6:
        #     print(f"Warning: Gemini returned {len(parsed_output.questions)} questions instead of 6. Please check the prompt or model behavior.")

        return data['questions']

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
    user_id = request.form.get('id') 

    if not user_id:
        return jsonify({"error": "Missing user ID"}), 400

    user_data = collection.find_one({"user_id": user_id})

    if not user_data:
        return jsonify({"error": "User not found"}), 404

    questions = user_data.get("questions_list", [])
    question_index = user_data.get("question_index", 0)
    subquestion = user_data.get("subquestion", "").strip()
    subquestion_count = user_data.get("subquestion_count", 0)

    # If a subquestion is pending
    if subquestion and subquestion_count > 0:
        collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "current_subquestion": subquestion,
                    "current_question": subquestion,
                    "subquestion": "",
                },
                "$inc": {"subquestion_count": -1}
            }
        )
        return jsonify({
            "user_id": user_id,
            "question": subquestion
        })

    # No more questions
    if question_index >= len(questions):
        collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "current_question": "",
                    "current_answer": "",
                    "subquestion": "",
                    "current_subquestion": ""
                }
            }
        )
        return jsonify({
            "user_id": user_id,
            "message": "All questions have been asked"
        })

    next_question = questions[question_index]

    collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "current_question": next_question,
                "current_subquestion": "",
                "subquestion": "",
                "subquestion_count": 2
            },
            "$inc": {
                "question_index": 1
            }
        }
    )

    return jsonify({
        "user_id": user_id,
        "question": next_question
    })
def evaluate_answer(question: str, resume: str, user_answer: str, subquestion_count: int, model_name="gemini-1.5-flash-latest") -> tuple[bool, str, bool]:
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
    - isAdequate is a boolean (true/false) indicating whether the answer is polite and abuses free.
    - subquestion is a boolean (true/false) indicating wheather the answer is on-topic, technical or not. If true, it means you want to ask a follow-up technical question for clarification or depth.
    - feedback should be a short, friendly, slightly technical comment. If subquestion is true, the feedback should be the follow-up question. If subquestion is false, it should acknowledge and appreciate the candidate’s answer.

    You can ask a follow-up question only if {subquestion_count} is not 0.
    And if {subquestion_count} is 0. Then feedback should be 'Ok! Going great, let's move on to the next question.' this kind of acknowledgement
    Return your response in this exact format:
    {{
        "isAdequate": True,
        "subquestion": True,
        "feedback": "Ok! Going great, let's move on to the next question."
    }}

    Only return the JSON. Do not add any explanation or extra commentary outside the JSON format.
    """


    try:
        generation_config = genai.types.GenerationConfig(response_mime_type="text/plain")
        model = genai.GenerativeModel(model_name, generation_config=generation_config)
        response = model.generate_content(prompt)

        raw_text = response.text.strip()
        cleaned_text = re.sub(r"```(?:json)?", "", raw_text).strip()
        evaluation = json.loads(cleaned_text)

        result = evaluation.get("isAdequate", "")
        feedback = evaluation.get("feedback", "").strip()
        subquestion = evaluation.get("subquestion", "")
        if result:
            return (True, feedback, subquestion)
        else:
            return (False, feedback, False)

    except Exception as e:
        print(f"Error during AI evaluation: {e}")
        return False, "An error occurred during evaluation.", False


def acknowledgement_pool():
    sentences = [
        "Awesome, let's keep going with the next question.",
        "Perfect, moving on to the next one now.",
        "Great job! Let's tackle the next question.",
        "Sounds good! Let’s proceed to the next question.",
        "Excellent, let’s continue with the next question.",
        "Nice work! On to the next question.",
        "Alright, let’s move forward to the next question.",
        "Good stuff! Let’s check out the next question.",
        "Well done! Let's head to the next question.",
        "Fantastic, let’s go to the next question now."
    ]
    return random.choice(sentences)


@app.route('/give_answer', methods=['POST'])
def update_user_response():
    req_data = request.get_json()
    user_id = req_data.get('id')
    user_answer = req_data.get('answer')

    if not user_id or not user_answer:
        return jsonify({"error": "Missing user ID or answer"}), 400

    user_data = collection.find_one({"user_id": user_id})
    if not user_data:
        print(f"No data found for user_id: {user_id}")
        return jsonify({"error": "User not found"}), 404

    current_question = user_data.get("current_question", "").strip()
    subquestion_count = user_data.get("subquestion_count", 0)
    resume = user_data.get("resume", "")

    # Append to QnA list
    qna_entry = {
        "question": current_question,
        "answer": user_answer
    }

    updated_qna = user_data.get("qna", [])
    updated_qna.append(qna_entry)

    # Evaluate the answer
    is_satisfactory, feedback, subquestion_bool = evaluate_answer(
        current_question, resume, user_answer, subquestion_count
    )

    update_fields = {
        "current_answer": user_answer,
        "satisfactory_till_now": is_satisfactory,
        "qna": updated_qna
    }

    if subquestion_bool:
        update_fields["subquestion"] = feedback
        update_fields["current_question"] = feedback

    collection.update_one(
        {"user_id": user_id},
        {"$set": update_fields}
    )

    if subquestion_count == 0:
        return jsonify({"user_id": user_id, "feedback": acknowledgement_pool()})

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
