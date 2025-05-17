import json
import uuid
import pdfplumber
from typing import List, Tuple
import google.generativeai as genai
from pydantic import ValidationError
import random
import re

# -------------------- PDF Handler --------------------
# extract pdf
class PDFHandler:
    @staticmethod
    def extract_text_from_pdf(pdf_file) -> str:
        all_text = ""
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    all_text += text + "\n"
        return all_text


# -------------------- ID Generator --------------------
# Generates random ID
class IDGenerator:
    @staticmethod
    def generate_unique_id() -> str:
        return str(uuid.uuid4())

# -------------------- Database Manager --------------------
# Handles DB related tasks


class QuestionGenerator:
    def __init__(self, model_name: str = "gemini-1.5-flash-latest"):
        generation_config = genai.types.GenerationConfig(
            response_mime_type="application/json"
        )
        self.model = genai.GenerativeModel(model_name, generation_config=generation_config)

    def generate_questions(self, resume_text: str, job_description: str) -> List[str] | None:
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
            print(f"Sending request to Gemini model...")
            response = self.model.generate_content(prompt)
            response_text = response.text
            data = json.loads(response_text)

            if not isinstance(data, list) and "questions" in data:
                data = data["questions"]

            return data
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"JSON Decode Error or Validation Error: {e}")
            print(f"Raw response:\n{response.text}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None

class AIAnswerEvaluator:
    def __init__(self, model_name: str = "gemini-1.5-flash-latest"):
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name, generation_config=genai.types.GenerationConfig(
            response_mime_type="text/plain"
        ))

    def evaluate(self, question: str, resume: str, user_answer: str, subquestion_count: int) -> Tuple[bool, str, bool]:
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
            response = self.model.generate_content(prompt)
            raw_text = response.text.strip()
            cleaned_text = re.sub(r"```(?:json)?", "", raw_text).strip()
            evaluation = json.loads(cleaned_text)

            is_adequate = evaluation.get("isAdequate", False)
            feedback = evaluation.get("feedback", "").strip()
            subquestion = evaluation.get("subquestion", False)

            return is_adequate, feedback, subquestion

        except Exception as e:
            print(f"Error during AI evaluation: {e}")
            return False, "An error occurred during evaluation.", False

class AcknowledgementService:
    @staticmethod
    def get_message():
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

