from flask import Flask, request, jsonify
from flask_cors import CORS
import handlers, db_handlers
import os
import google.generativeai as genai
from pymongo import MongoClient

os.environ["GOOGLE_API_KEY"]="Your_API_KEy"

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


try:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY environment variable not set.")
    genai.configure(api_key=GOOGLE_API_KEY)
except ValueError as e:
    print(f"Error: {e}")
    print("Please set the GOOGLE_API_KEY environment variable before running the script.")


# -------------------- Flask Route --------------------
@app.route('/upload_resume', methods=['POST'])
def upload_resume():
    if 'resume' not in request.files:
        return jsonify({"error": "No resume file part"}), 400

    resume_file = request.files['resume']
    if resume_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    job_description = request.form.get('job_description', "")

    try:
        resume_text = handlers.PDFHandler.extract_text_from_pdf(resume_file)
        unique_id = handlers.IDGenerator.generate_unique_id()
        generator = handlers.QuestionGenerator()
        db_handler = db_handlers.ResumeDB(collection)

        generated_questions = generator.generate_questions(resume_text, job_description)

        if generated_questions:
            print("\n--- Successfully Generated Questions ---")
            db_handler.save(unique_id, resume_text, generated_questions, job_description)
        else:
            print("\n--- Failed to Generate Questions ---")

        return jsonify({"user_id": unique_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------- Flask Route --------------------
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

# -------------------- Flask Route --------------------
@app.route('/give_answer', methods=['POST'])
def update_user_response():
    req_data = request.get_json()
    user_id = req_data.get('id')
    user_answer = req_data.get('answer')

    if not user_id or not user_answer:
        return jsonify({"error": "Missing user ID or answer"}), 400

    user_db = db_handlers.UserDatabase(collection)
    evaluator = handlers.AIAnswerEvaluator()
    ack_service = handlers.AcknowledgementService()

    user_data = user_db.get_user(user_id)
    if not user_data:
        return jsonify({"error": "User not found"}), 404

    current_question = user_data.get("current_question", "").strip()
    subquestion_count = user_data.get("subquestion_count", 0)
    resume = user_data.get("resume", "")

    # Append to QnA
    updated_qna = user_data.get("qna", [])
    updated_qna.append({
        "question": current_question,
        "answer": user_answer
    })

    is_satisfactory, feedback, subquestion_bool = evaluator.evaluate(
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

    user_db.update_user(user_id, update_fields)

    if subquestion_count == 0:
        return jsonify({"user_id": user_id, "feedback": ack_service.get_message()})

    return jsonify({"user_id": user_id, "feedback": feedback})


if __name__ == '__main__':
    app.run(debug=True)
