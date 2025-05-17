from typing import List

class ResumeDB:
    def __init__(self, collection):
        self.collection = collection

    def save(self, unique_id: str, resume_text: str = None, questions: List[str] = None, job_description: str = ""):
        doc = self.collection.find_one({"user_id": unique_id})

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
                "job_description": job_description,
                "satisfactory_till_now": True,
                "current_subquestion": ""
            }
            self.collection.insert_one(doc)
        else:
            update_fields = {}
            if resume_text:
                update_fields["resume"] = resume_text
            if questions:
                update_fields["questions_list"] = questions
            if update_fields:
                self.collection.update_one({"user_id": unique_id}, {"$set": update_fields})


class UserDatabase:
    def __init__(self, collection):
        self.collection = collection

    def get_user(self, user_id):
        return self.collection.find_one({"user_id": user_id})

    def update_user(self, user_id, update_fields):
        self.collection.update_one({"user_id": user_id}, {"$set": update_fields})
