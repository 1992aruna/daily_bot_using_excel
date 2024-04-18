from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import os
import requests
import re
import pandas as pd
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv
from messages import *
from utils import retrieve_user_answers, send_excel_file
from data import *
from google.oauth2 import service_account
import gspread
import logging
import uuid
import datetime
import time
import openai
# from openai.error import RateLimitError
from bson import ObjectId
import pymongo

# allowed_extensions=["png", "jpg", "jpeg", "mp4", "mp3", "pdf"]

# def allowed_file(filename):
#   ext=filename.split(".")[-1]
#   if ext in allowed_extensions:
#       return True
processed_message_ids = set()
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'mp4', 'mp3'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Specify the path to your service account JSON key file
keyfile_path = 'google_cloud.json'

# Authenticate using the service account JSON key file
credentials = service_account.Credentials.from_service_account_file(
    keyfile_path, 
    # scopes=['https://www.googleapis.com/auth/spreadsheets']
    scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
)

# Authorize with gspread using the credentials
client = gspread.authorize(credentials)

# Load environment variables
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
API_URL = os.getenv("API_URL")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)

openai.api_key = OPENAI_API_KEY
app.config["MONGO_URI"] = MONGO_URI
mongo = PyMongo(app)
db = mongo.db.staff

questions_db = mongo.db.questions
answers_db = mongo.db.answers
suggestion_db = mongo.db.suggestion
feedback_db = mongo.db.feedback
chatgpt_db = mongo.db.chatgpt
form_db = mongo.db.form_data
user_queries_db = mongo.db.user_queries

if chatgpt_db is None:
    mongo.db.create_collection("chatgpt")

# Initialize Wati API endpoint
WATI_API_ENDPOINT = f"{API_URL}/api/v1/sendSessionMessage"

scheduler = BackgroundScheduler()
questions = {}
active_sheets = {}

# Function to send image message
def send_image_message(phone_number,image, caption):
    url = f"{API_URL}/api/v1/sendSessionFile/{phone_number}?caption={caption}"

    payload = {}
    files=[
    ('file',('file',open(image,'rb'),'image/jpeg'))
    ]
    headers = {
    'Authorization': ACCESS_TOKEN
    }

    response = requests.post(url, headers=headers, json=payload, files=files)
    print(response)
    print(response.json())
    
def get_media(filename):
    url = f"{API_URL}/api/v1/getMedia"

    payload = {'fileName': filename}
    
    headers = {
    'Authorization': ACCESS_TOKEN
    }

    response = requests.get(url, headers=headers, data=payload)
    return response

def upload_image(filename, loc):
    response= get_media(filename)
    filename=filename.split("/")[-1]
    if response.status_code==200:
        #file=fs.put(response.content, filename=filename)
        
        with open(f'{loc}/{filename}', "wb") as f:
                f.write(response.content)
       
        #print(file)
        print("Upload Complete")
        return f"{loc}/{filename}"
    
    return False

def send_question_message(contact_number, message):
	headers = {
					'Authorization': ACCESS_TOKEN,
				}
	payload={'messageText': message}

	url = f"{API_URL}/api/v1/sendSessionMessage/"+ f'{contact_number}'
	response = requests.post(url=url, headers=headers,data=payload)
	pending_questions[contact_number] = message

def send_reply_button(contact_number, message, buttons):
    payload = {
        "body": message,
        "buttons": buttons
    }

    url = f"{API_URL}/api/v1/sendInteractiveButtonsMessage?whatsappNumber="+f"{contact_number}"
    headers = {
        'Authorization': ACCESS_TOKEN,
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, json=payload)
    print("Reply response", response)
    print("Reply Payload", payload)
    pending_questions[contact_number] = message
    # Return the message/question for further processing
    # return message

def send_reply_button1(contact_number, message, buttons):
    payload = {
    
    "body": message,
    "buttons": buttons
    }

    url = f"{API_URL}/api/v1/sendInteractiveButtonsMessage?whatsappNumber="+f"{contact_number}"
    headers = {
                'Authorization': ACCESS_TOKEN,
                'Content-Type': 'application/json'
            }
    response = requests.request("POST", url, headers=headers, json=payload)
    return response.status_code

def send_list(contact_number, message, sections):
    url = f"{API_URL}/api/v1/sendInteractiveListMessage?whatsappNumber={contact_number}"
    payload = {
         "body": message,
         "buttonText": "Select",
         "sections": sections
    }

    headers = {
                'Authorization': ACCESS_TOKEN,
                'Content-Type': 'application/json'
            }
    response = requests.request("POST", url, headers=headers, json=payload)
    print(response)
    print(response.json())

#-------------------------------------------------------------------------------------------------------#
def open_spreadsheet():
    # Open the 'Daily_Questions' spreadsheet
    spreadsheet = client.open('Questions')
    
    # Create a unique worksheet name based on the current timestamp
    worksheet_name = f"Sheet_{int(time.time())}"

    # Create a new worksheet
    worksheet = spreadsheet.add_worksheet(worksheet_name, rows=1000, cols=20)  # Adjust rows and cols as needed

    return spreadsheet, worksheet, worksheet_name


def get_latest_question_id():
    # Assuming you have a collection named 'questions' in your MongoDB
    questions_collection = mongo.db.questions
    # Get the latest question from the database
    latest_question = questions_collection.find_one({}, sort=[("question_id", pymongo.DESCENDING)])
    return latest_question["question_id"] if latest_question else 00000

def save_question_to_database_and_spreadsheet(phone_number, question_type, questions, worksheet):
    # Assuming you have a collection named 'questions' in your MongoDB
    questions_collection = mongo.db.questions

    try:
        starting_id = 10000
        starting_id = get_latest_question_id() + 1

        for question_text in questions:
            starting_id = get_latest_question_id() + 1
            question_id = starting_id
            
            # Save to the database
            question_doc = {
                "_id": ObjectId(),
                "created_By": phone_number,
                "question_id": question_id,
                "question_type": question_type,  # Add the question type field
                "question_text": question_text,
            }
            result = questions_collection.insert_one(question_doc)
    
            if result.inserted_id:
                print(f"Question saved to the 'questions' collection for phone number: {phone_number}")
                starting_id += 1  # Increment the current ID for the next question
            else:
                print(f"Failed to save question to the 'questions' collection for phone number: {phone_number}")

            # Save to the spreadsheet
            combined_question = f"{question_id}. {question_text}"
            worksheet.append_row([combined_question, question_type])  # Save both question and type
            print(f"Question saved to the spreadsheet for phone number: {phone_number}")

            if not user_in_question_creation_mode.get(phone_number, False):
                # If not, clear the active sheet for this user
                if phone_number in active_sheets:
                    active_sheets.pop(phone_number)

    except Exception as e:
        print(f"An error occurred while saving questions to the database and spreadsheet: {str(e)}")


def reset_question_count_and_status():
    try:
        # Update the question count and status for all users
        db.update_many({}, {"$set": {"questions_sent_count": 0, "status": ""}})
        print("Question count and status reset for all users.")
    except Exception as e:
        print(f"An error occurred while resetting question count and status: {str(e)}")

# scheduler.add_job(reset_question_count_and_status, trigger=CronTrigger(hour=12, minute=35))

def get_questions_from_spreadsheet(worksheet):
    try:
        questions = worksheet.col_values(1)  # Assuming questions are in the first column
        question_types = worksheet.col_values(2)  # Assuming question types are in the second column
        return list(zip(questions, question_types))
    except Exception as e:
        print(f"Error fetching questions from the Google Spreadsheet: {str(e)}")
        return []

def find_staff_with_unanswered_questions():
    staff_with_unanswered_questions = []

    # Get all staff members from the database
    staff_members = db.find({})

    for staff in staff_members:
        phone_number = staff.get('phone_number')
        if not phone_number:
            continue

        # Check if there are answers for this staff member in the answers database
        answers = mongo.db.answers.find_one({'phone_number': phone_number})

        if not answers:
            staff_with_unanswered_questions.append(staff)
        else:
            # Get the total question count from the staff collection
            total_questions = staff.get('questions_sent_count', 0)

            # Check how many questions have been answered
            answered_question_count = sum(1 for key in answers if key.startswith('answer_'))

            if answered_question_count < total_questions:
                staff_with_unanswered_questions.append(staff)

    return staff_with_unanswered_questions

def count_answered_questions(phone_number):
    # Query your answers database to count the answered questions for the given phone number
    answered_questions_count = 0

    # Assuming you have a collection named "answers" for storing answers
    answers = mongo.db.answers.find_one({'phone_number': phone_number})

    if answers:
        # Iterate through the answers document and count answered questions
        for key in answers:
            if key.startswith("answer_"):
                answered_questions_count += 1

    return answered_questions_count

def send_reminder_to_staff_with_unanswered_questions():
    try:
        print("Executing send_reminder_to_staff_with_unanswered_questions function")

        # Find staff members with unanswered questions
        staff_with_unanswered_questions = find_staff_with_unanswered_questions()

        if not staff_with_unanswered_questions:
            print("No staff members found with unanswered questions.")
            return

        for staff in staff_with_unanswered_questions:
            phone_number = staff.get('phone_number')
            # Calculate the unanswered questions count
            total_questions_count = staff.get('questions_sent_count', 0)  # Total questions sent to the staff
            answered_questions_count = count_answered_questions(phone_number)  # Implement a function to count answered questions

            unanswered_count = total_questions_count - answered_questions_count

            # Construct and send the reminder message
            reminder_message = f"Reminder: You have {unanswered_count} unanswered question(s). Please provide answers for the remaining {unanswered_count} question(s)."

            # Send the reminder message to the staff member (implement the send_message function)
            send_message(phone_number, reminder_message)

        print("Execution of send_reminder_to_staff_with_unanswered_questions function completed")
    except Exception as e:
        print(f"An error occurred: {str(e)}")

scheduler.add_job(send_reminder_to_staff_with_unanswered_questions, trigger=CronTrigger(hour=16, minute=41))


def send_questions_to_contact(contact_number, questions):
    question_count = 0  # Initialize the question count to 0

    for question in questions:
        send_message(contact_number, question)
        question_count += 1  # Increment the question count for each sent question

    # Update the user's document in the staff database with the question count
    db.update_one({"phone_number": contact_number}, {"$set": {"questions_sent_count": question_count}})
    
    return question_count  # Return the total question count


def send_new_questions_periodically():
    try:
        print("Executing send_new_questions_periodically function")
        spreadsheet = client.open('Daily_Questions')
        worksheet = spreadsheet.worksheet('Sheet1')

        questions = get_questions_from_spreadsheet(worksheet)

        for staff in db.find({}):
            if 'phone_number' in staff:
                phone_number = staff['phone_number']
                questions_sent_count = staff.get("questions_sent_count", 0)
                new_questions_count = len(questions) - questions_sent_count

                if new_questions_count > 0:
                    new_questions = questions[questions_sent_count:questions_sent_count + new_questions_count]
                    send_questions_to_contact(phone_number, new_questions)
                    print(f"Sent {new_questions_count} new questions to {phone_number}")

                    # Set the status to an empty string
                    db.update_one({"_id": staff["_id"]}, {"$set": {"status": ""}})

                    # Update the questions_sent_count in the database
                    db.update_one(
                        {"_id": staff["_id"]},
                        {"$set": {"questions_sent_count": questions_sent_count + new_questions_count}}
                    )

                    # Set the status to "send" after sending the questions
                    db.update_one({"_id": staff["_id"]}, {"$set": {"status": "send"}})

        print("Execution of send_new_questions_periodically function completed")

    except Exception as e:
        print(f"An error occurred: {str(e)}")

# scheduler.add_job(send_new_questions_periodically, IntervalTrigger(minutes=2))
 
# def send_branch_images(documents, questions):
#     print("Executing send_branch_images function")
    
#     try:        
#         print(f"questions: {questions}")
#         print(f"Filtered data: {list(documents)}") 
#         for staff in documents:
#             print(f"staff: {staff}")
#             # Check if 'branch' and 'phone_number' fields exist in the document
#             if 'branch' in staff and 'phone_number' in staff:
#                 branch = staff['branch']
#                 phone_number = staff['phone_number']
#                 alternate_phone_number = staff.get('alternate_phone_number')  # Get the alternate number if available

#                 print(f"Processing branch: {branch}, Primary Phone: {phone_number}, Alternate Phone: {alternate_phone_number}")

#                 # Check if an image exists for this branch with either .png or .jpg extension
#                 image_extensions = ['.png', '.jpg']
#                 image_found = False

#                 for ext in image_extensions:
#                     image_path = f'E:\\NewProject\\Python\\Corprate App\\Question&AnswerBot\\After Modification\\Latest\\daily_bot_using_excel\\branch_images\\{branch}{ext}'
                                    
#                     if os.path.isfile(image_path):
#                         image_found = True
#                         print("Image exists. Sending to", phone_number)
#                         # Provide a caption for the image message
#                         caption = f'Here is your image for branch {branch}'
#                         send_image_message(phone_number, image_path, caption)
#                         print(f"Image sent for branch {branch} with extension {ext}")

#                         # Send questions based on question type
#                         for question, question_type in questions:
#                             if question_type == "Yes or No":
#                                 # Send question with yes or no buttons
#                                 send_reply_button(phone_number, question, answer_buttons)
#                             else:
#                                 # Send regular text question
#                                 send_message(phone_number, question)
#                                 print(f"Question sent for branch {branch} phone number {phone_number}")

#                         db.update_one({"_id": staff["_id"]}, {"$set": {"status": "sent"}})

#                         if alternate_phone_number and alternate_phone_number != phone_number:
#                             print("Sending to alternate phone number:", alternate_phone_number)
#                             send_image_message(alternate_phone_number, image_path, caption)
#                             print(f"Image sent for branch {branch} to alternate phone number {alternate_phone_number}")
                            
#                             # Send questions based on question type to alternate phone number
#                             for question, question_type in questions:
#                                 if question_type == "Yes or No":
#                                     # Send question with yes or no buttons
#                                     send_reply_button(alternate_phone_number, question, answer_buttons)
#                                 else:
#                                     # Send regular text question
#                                     send_message(alternate_phone_number, question)
#                                     print(f"Question sent for branch {branch} to alternate phone number {alternate_phone_number}")

#                             db.update_one({"_id": staff["_id"]}, {"$set": {"status": "sent"}})

#                 if not image_found:
#                     print(f"No image found for branch {branch}")
#             else:
#                 print("Missing 'branch' or 'phone_number' field in the document.")

#         # Close the MongoDB connection
#         # client.close()
#     except Exception as e:
#         print(f"An error occurred: {str(e)}")
        
def send_branch_images(documents, questions):
    print("Executing send_branch_images function")
    
    try:        
        print(f"questions: {questions}")
        print(f"Filtered data: {list(documents)}") 
        for staff in documents:
            print(f"staff: {staff}")
            # Check if 'branch' and 'phone_number' fields exist in the document
            if 'branch' in staff and 'phone_number' in staff:
                branch = staff['branch']
                phone_number = staff['phone_number']
                alternate_phone_number = staff.get('alternate_phone_number')  # Get the alternate number if available

                print(f"Processing branch: {branch}, Primary Phone: {phone_number}, Alternate Phone: {alternate_phone_number}")

                # Check if an image exists for this branch with either .png or .jpg extension
                image_extensions = ['.png', '.jpg']
                image_found = False

                for ext in image_extensions:
                    image_path = f'E:\\NewProject\\Python\\Corprate App\\Question&AnswerBot\\After Modification\\Latest\\daily_bot_using_excel\\branch_images\\{branch}{ext}'
                                    
                    if os.path.isfile(image_path):
                        image_found = True
                        print("Image exists. Sending to", phone_number)
                        # Provide a caption for the image message
                        caption = f'Here is your image for branch {branch}'
                        send_image_message(phone_number, image_path, caption)
                        print(f"Image sent for branch {branch} with extension {ext}")

                        # Ensure questions are stored as a dictionary
                        # if phone_number not in questions:
                        #     questions[phone_number] = []

                        # Send questions based on question type
                        # Send questions based on question type
                        for question_tuple in questions:
                            question, question_type = question_tuple
                            if question_type == "Yes or No":
                                if question is None:
                                    # Get question text from send_reply_button function
                                    question = send_reply_button(phone_number, None, answer_buttons)
                                # Send question with yes or no buttons
                                send_reply_button(phone_number, question, answer_buttons)

                            elif question_type == "Image Upload":
                                # Send regular text question
                                send_question_message(phone_number, question)
                                print(f"Question sent for branch {branch} phone number {phone_number}")

                            elif question_type == "Text":
                                # Send regular text question
                                send_question_message(phone_number, question)
                                print(f"Question sent for branch {branch} phone number {phone_number}")

                            else:
                                # Send regular text question
                                send_question_message(phone_number, question)
                                print(f"Question sent for branch {branch} phone number {phone_number}")

                        db.update_one({"_id": staff["_id"]}, {"$set": {"status": "sent"}})

                        if alternate_phone_number and alternate_phone_number != phone_number:
                            print("Sending to alternate phone number:", alternate_phone_number)
                            send_image_message(alternate_phone_number, image_path, caption)
                            print(f"Image sent for branch {branch} to alternate phone number {alternate_phone_number}")
                            
                            # Ensure questions are stored as a dictionary for alternate phone number
                            if alternate_phone_number not in questions:
                                questions[alternate_phone_number] = []

                            # Send questions based on question type to alternate phone number
                            for question, question_type in questions[alternate_phone_number]:
                                if question_type == "Yes or No":
                                    if question is None:
                                        # Get question text from send_reply_button function
                                        question = send_reply_button(alternate_phone_number, None, answer_buttons)
                                    # Send question with yes or no buttons
                                    send_reply_button(alternate_phone_number, question, answer_buttons)

                                elif question_type == "Image Upload":
                                    # Send regular text question
                                    send_question_message(alternate_phone_number, question)
                                    print(f"Question sent for branch {branch} phone number {alternate_phone_number}")

                                else:
                                    # Send regular text question
                                    send_question_message(alternate_phone_number, question)
                                    print(f"Question sent for branch {branch} to alternate phone number {alternate_phone_number}")

                            db.update_one({"_id": staff["_id"]}, {"$set": {"status": "sent"}})

                if not image_found:
                    print(f"No image found for branch {branch}")
            else:
                print("Missing 'branch' or 'phone_number' field in the document.")

        # Close the MongoDB connection
        # client.close()
    except Exception as e:
        print(f"An error occurred: {str(e)}")

def search_for_answer(user_question, worksheet):
    # Read data from the worksheet
    data = worksheet.get_all_records()

    for col in data:
        if 'Question' in col and 'Answer' in col:
            if col['Question'].lower() in user_question.lower():
                return col['Answer']
    return "I couldn't find an answer to your question."



user_in_question_mode = {}
suggestion_mode = {}
feedback_mode = {}
complaint_mode = {}
mail_mode = {}
form_mode = {}
form_data = {}
user_in_question_creation_mode = {}
pending_questions = {}


def search_for_question_answer(question_number, worksheet):
    # Assuming the question numbers are in column A, questions in column B and answers in column C
    question_number_cells = worksheet.col_values(1)
    question_cells = worksheet.col_values(2)
    answer_cells = worksheet.col_values(3)

    for i, q_num in enumerate(question_number_cells):
        if str(q_num) == str(question_number):
            return question_cells[i], answer_cells[i]

    return "I'm sorry, I couldn't find a question with that number."
# user_in_code_mode = {}

def chat_with_gpt(question):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": question}
        ]
    )
    gpt_response = response['choices'][0]['message']['content']
    return gpt_response
help_requested = False
def handle_form_command(phone_number):
    # Send the first question
    send_message(phone_number, "What is your name?")
    
def handle_form_message(phone_number, message):
    if "name" not in form_mode[phone_number]:
        # Save the name and send the next question
        form_mode[phone_number]["name"] = message
        send_message(phone_number, "What is your age?")
    elif "age" not in form_mode[phone_number]:
        # Save the age and send the next question or process form completion
        form_mode[phone_number]["age"] = message
        send_message(phone_number, "What is your qualification?")
    elif "qualification" not in form_mode[phone_number]:
        # Save the qualification and process form completion
        form_mode[phone_number]["qualification"] = message
        # Now you have all the form data, you can process it further
        save_form_data(phone_number, form_mode[phone_number])

# Function to save form data
def save_form_data(phone_number, form_data):
    form_db.insert_one({"phone_number": phone_number, "name": form_data["name"], "age": form_data["age"], "qualification": form_data["qualification"]})
    # Once the data is saved, you can proceed with converting it to PDF and sending it

def process_message(phone_number, message):
    global help_requested, questions, suggestion_counter, feedback_counter
    # global global_questions
    questions = {}    

    # if message.startswith("/create"):
    #     user = db.find_one({"phone_number": phone_number})
    #     if user and user.get("position") in ["BM", "RM"]:
    #         user_in_question_creation_mode[phone_number] = True
    #         print(f"User {phone_number} entered question creation mode.")
    #         options_message = "What type of question do you want to create?"
    #         send_list(phone_number, "Select Question Type", type_list)
    #         if phone_number not in active_sheets:
    #             spreadsheet, worksheet, worksheet_name = open_spreadsheet()
    #             active_sheets[phone_number] = {"spreadsheet": spreadsheet, "worksheet": worksheet, "worksheet_name": worksheet_name}
    #         questions[phone_number] = []  # Initialize questions for this user
    #         print(f"questions after /create: {questions}")
    #     else:
    #         send_message(phone_number, "Permission denied. You don't have the necessary position to create questions.")

    # elif user_in_question_creation_mode.get(phone_number, False):
    #     if message.strip() == "/end":
    #         send_message(phone_number, "Question creation mode ended.")
    #         user_in_question_creation_mode[phone_number] = False
    #         options_message = "To whom do you want to send the questions?\n1. Clerical\n2. Officer\n3. BM"
    #         send_message(phone_number, options_message)
    #     else:
    #         question_type = None
    #         # Check if the message is a valid option
    #         if message.strip() in ["Yes or No", "Text", "Image Upload"]:
    #             question_type =  message 
    #             print("Question Type", question_type)
    #             send_message(phone_number, "Please give your question here")
    #         else:         
    #             questions_to_save = questions.get(phone_number, [])
    #             questions_to_save.append(message)
    #             questions[phone_number] = questions_to_save
                
    #             if questions_to_save and "/end" not in questions_to_save:
    #                 save_question_to_database_and_spreadsheet(phone_number, question_type, questions_to_save, active_sheets[phone_number]["worksheet"])

    #                 send_message(phone_number, f"To end, send '/end'.")
    if message.startswith("/create"):
        user = db.find_one({"phone_number": phone_number})
        if user and user.get("position") in ["BM", "RM"]:
            user_in_question_creation_mode[phone_number] = {"question_type": None}  # Initialize question type
            user_in_question_creation_mode[phone_number]["in_creation_mode"] = True
            print(f"User {phone_number} entered question creation mode.")
            # options_message = "What type of question do you want to create?"
            send_list(phone_number, "Select Question Type", type_list)
            if phone_number not in active_sheets:
                spreadsheet, worksheet, worksheet_name = open_spreadsheet()
                active_sheets[phone_number] = {"spreadsheet": spreadsheet, "worksheet": worksheet, "worksheet_name": worksheet_name}
            questions[phone_number] = []  # Initialize questions for this user
            print(f"questions after /create: {questions}")
        else:
            send_message(phone_number, "Permission denied. You don't have the necessary position to create questions.")

    elif user_in_question_creation_mode.get(phone_number, {}).get("in_creation_mode", False):
        if message.strip() == "/end":
            send_message(phone_number, "Question creation mode ended.")
            user_in_question_creation_mode[phone_number]["in_creation_mode"] = False
            # options_message = "To whom do you want to send the questions?\n1. Clerical\n2. Officer\n3. BM"
            # send_message(phone_number, options_message)
            send_list(phone_number, "To whom you want to send\n", position_list)
        else:
            if user_in_question_creation_mode[phone_number]["question_type"] is None:
                # Check if the message is a valid option for question type
                if message.strip() in ["Yes or No", "Text", "Image Upload"]:
                    user_in_question_creation_mode[phone_number]["question_type"] = message.strip()
                    print("Question Type:", user_in_question_creation_mode[phone_number]["question_type"])
                    send_message(phone_number, "Please enter your question.")
                else:
                    send_message(phone_number, "Invalid question type. Please select a valid option.")
            else:
                # This means the user has already selected a question type, so the message is the question
                question_type = user_in_question_creation_mode[phone_number]["question_type"]
                questions_to_save = questions.get(phone_number, [])
                questions_to_save.append(message)
                questions[phone_number] = questions_to_save
                print("Question Type1:", question_type)
                print("Question:", questions_to_save)
                save_question_to_database_and_spreadsheet(phone_number, question_type, questions_to_save, active_sheets[phone_number]["worksheet"])
                send_message(phone_number, "Question saved. Please enter your next question or send '/end' to finish.")

    elif message == "/help":    
        help_requested = True
        try:

            data = request.json
            print("Webhook Payload:", data)  # Debug statement to print the entire payload

            number = data.get('waId', '')
            incoming_message = data.get('text', '').strip()  # Extract the incoming message

            print("Incoming Message:", incoming_message)  # Debug statement

            # Generate a response using GPT-3.5 Turbo with the incoming message as the user's query
            answer = chat_with_gpt(incoming_message)

            print("Generated Answer:", answer)  # Debug statement

            # Send the response via WhatsApp
            send_message(number, answer)
        except Exception as e:
            print(f"Rate limit error: {str(e)}")
            send_message(phone_number, "/help is not available at the moment due to rate limit. Please try again later.")
            help_requested = False
       
    elif help_requested:
        data = request.json
        print("Webhook Payload:", data)  # Debug statement to print the entire payload

        number = data.get('waId', '')
        incoming_message = data.get('text', '').strip()  # Extract the incoming message
        staff_data = db.find_one({"phone_number": number})

        print("Incoming Message:", incoming_message)  # Debug statement

        # Generate a response using GPT-3.5 Turbo with the incoming message as the user's query
        answer = chat_with_gpt(incoming_message)

        print("Generated Answer:", answer)  # Debug statement
        chat_data = {
            "name": staff_data.get("name", ""),
            "position": staff_data.get("position", ""),                         
            "branch": staff_data.get("branch", ""),
            'phoneNumber': number,
            'query': incoming_message,
            'response': answer,
        }
        chatgpt_db.insert_one(chat_data)
        # Send the response via WhatsApp
        send_message(number, answer)
        help_requested = False
        send_message(number, "You are now out of help mode.")
    elif message == "/ask":
        # The user wants to enter "question mode"
        user_in_question_mode[phone_number] = True
        response = "You are now in question mode. Ask your question."
        send_message(phone_number, response)

    elif user_in_question_mode.get(phone_number, False):
        # The user is in question mode
        spreadsheet = client.open('Search_Answers')
        worksheet = spreadsheet.worksheet('Sheet1')
        response = None

        if message.isdigit():
            # User provided a question number, search for the question and answer
            question, answer = search_for_question_answer(message, worksheet)
            staff_data = db.find_one({"phone_number": phone_number})

            if not answer:
                answer = "I'm sorry, I couldn't find a question with that number."

            response = f"Question: {question}\nAnswer: {answer}"

            # Save the user's question and response to MongoDB
            user_query_data = {
                "name": staff_data.get("name", ""),
                "position": staff_data.get("position", ""),                         
                "branch": staff_data.get("branch", ""),
                'phoneNumber': phone_number,
                'question': message,
                'response': response,
            }
            user_queries_db.insert_one(user_query_data)

        else:
            staff_data = db.find_one({"phone_number": phone_number})
            if not message.endswith('?'):
                message += '?'
            # User provided a regular question, let's search for the answer as usual
            answer = search_for_answer(message, worksheet)
            if not answer:
                response = "I couldn't find an answer to your question."
            else:
                response = answer

                # Save the user's question and response to MongoDB
                user_query_data = {
                    "name": staff_data.get("name", ""),
                    "position": staff_data.get("position", ""),                         
                    "branch": staff_data.get("branch", ""),
                    'phoneNumber': phone_number,
                    'question': message,
                    'response': answer,
                }
                user_queries_db.insert_one(user_query_data)

        send_message(phone_number, response)
        user_in_question_mode[phone_number] = False
        response1 = "You question mode ended."
        send_message(phone_number, response1)
    
    elif message == "/suggestion":
        suggestion_mode[phone_number] = True
        response = "You are now in suggestion mode. Send your suggestion."
        send_message(phone_number, response)
        # global suggestion_mode        

    # Assuming subsequent messages should be treated as suggestions
    elif suggestion_mode.get(phone_number, False):
        data_2 = request.json
        print(data_2)
        try:
            number = data_2['waId']
            print(number)

            if data_2['type'] == 'text':
                received_message = data_2['text']
                print(received_message)
                
                staff_data = db.find_one({"phone_number": number})

                if staff_data:
                    # Check if a suggestion with the same phone number already exists
                    existing_suggestion = suggestion_db.find_one({"phone_number": number})

                    if existing_suggestion:
                        # Update the existing suggestion
                        suggestion_db.update_one(
                            {"phone_number": number},
                            {"$set": {"suggestion_" + str(suggestion_counter): received_message}}
                        )
                    else:
                        # Insert a new suggestion
                        suggestion_data = {
                            "name": staff_data.get("name", ""),
                            "position": staff_data.get("position", ""),                         
                            "branch": staff_data.get("branch", ""),                       
                            "phone_number": staff_data.get("phone_number", ""),
                            "suggestion_" + str(suggestion_counter): received_message
                        }
                        suggestion_db.insert_one(suggestion_data)

            suggestion_counter += 1
            suggestion_mode[phone_number] = False
            send_message(phone_number, "Suggestion mode ended.")
        except Exception as e:
            print(e)
            print("Error in suggestion mode")
            
    elif message == "/feedback":
        feedback_mode[phone_number] = True
        response = "You are now in feedback mode. Send your feedback."
        send_message(phone_number, response)
        # global feedback_mode
        # feedback_mode = True

    # Assuming subsequent messages should be treated as feedback
    elif feedback_mode.get(phone_number, False):
        data_3 = request.json
        print(data_3)
        try:
            number = data_3['waId']
            print(number)

            if data_3['type'] == 'text':
                received_message_1 = data_3['text']
                print(received_message_1)
                
                staff_data = db.find_one({"phone_number": number})

                if staff_data:
                    # Check if a feedback with the same phone number already exists
                    existing_feedback = feedback_db.find_one({"phone_number": number})

                    if existing_feedback:
                        # Update the existing feedback
                        feedback_db.update_one(
                            {"phone_number": number},
                            {"$set": {"feedback_" + str(feedback_counter): received_message_1}}
                        )
                    else:
                        # Insert a new feedback
                        feedback_data = {
                            "name": staff_data.get("name", ""),
                            "position": staff_data.get("position", ""),                         
                            "branch": staff_data.get("branch", ""),                       
                            "phone_number": staff_data.get("phone_number", ""),
                            "feedback_" + str(feedback_counter): received_message_1
                        }
                        feedback_db.insert_one(feedback_data)

                    feedback_counter += 1
                    feedback_mode[phone_number] = False
                    send_message(phone_number, "Feedback mode ended.")
        except Exception as e:
            print(e)
            print("Error in feedback mode")
   
    elif message == "/complaint":
        complaint_mode[phone_number] = True
        response = "You are now in feedback mode. Send your feedback."
        send_message(phone_number, response)
        # global feedback_mode
        # feedback_mode = True

    # Assuming subsequent messages should be treated as feedback
    elif complaint_mode.get(phone_number, False):
        data_3 = request.json
        print(data_3)
        try:
            number = data_3['waId']
            print(number)

            if data_3['type'] == 'text':
                received_message_1 = data_3['text']
                print(received_message_1)
                
                staff_data = db.find_one({"phone_number": number})

                if staff_data:
                    # Check if a feedback with the same phone number already exists
                    existing_feedback = feedback_db.find_one({"phone_number": number})

                    if existing_feedback:
                        # Update the existing feedback
                        feedback_db.update_one(
                            {"phone_number": number},
                            {"$set": {"feedback_" + str(feedback_counter): received_message_1}}
                        )
                    else:
                        # Insert a new feedback
                        feedback_data = {
                            "name": staff_data.get("name", ""),
                            "position": staff_data.get("position", ""),                         
                            "branch": staff_data.get("branch", ""),                       
                            "phone_number": staff_data.get("phone_number", ""),
                            "feedback_" + str(feedback_counter): received_message_1
                        }
                        feedback_db.insert_one(feedback_data)

                    feedback_counter += 1
                    complaint_mode[phone_number] = False
                    send_message(phone_number, "Complaint mode ended.")
        except Exception as e:
            print(e)
            print("Error in complaint mode")

    elif message == "/mail":
        mail_mode[phone_number] = True
        # Get the user's data based on their phone number
    elif mail_mode.get(phone_number, False):
        staff_data = db.find_one({"phone_number": phone_number})

        if staff_data:
            branch = staff_data["branch"]
            email = staff_data["email"]
            
            # Assuming you have the 'branch' and 'email' variables available
            send_document(email, branch)
            response = "Email sent successfully."            
            send_message(phone_number, response)
            mail_mode[phone_number] = False
        else:
            response = "User data not found."
            send_message(phone_number, response)

    elif message == "/form":
        form_mode[phone_number] = True
        form_data[phone_number] = {}
        send_message(phone_number, "Please enter your name:")

# Assuming subsequent messages should be treated as form responses
    elif form_mode.get(phone_number, False):
        data_2 = request.json
        try:
            if data_2['type'] == 'text':
                received_message = data_2['text']
                if 'name' not in form_data[phone_number]:
                    form_data[phone_number]['name'] = received_message
                    send_message(phone_number, "Please enter your age:")
                elif 'age' not in form_data[phone_number]:
                    form_data[phone_number]['age'] = received_message
                    send_message(phone_number, "Please enter your qualification:")
                elif 'qualification' not in form_data[phone_number]:
                    form_data[phone_number]['qualification'] = received_message
                    
                    form_db.insert_one({
                        "phone_number": phone_number, 
                        "name": form_data[phone_number]["name"], 
                        "age": form_data[phone_number]["age"], 
                        "qualification": form_data[phone_number]["qualification"]
                    })

                    # Once all information is collected, fill the HTML form
                    # html_content = fill_html_form(form_data[phone_number]['name'], form_data[phone_number]['age'], form_data[phone_number]['qualification'])
                    
                    # Convert HTML to PDF
                    pdf_output_path = create_pdf(form_data[phone_number],phone_number)

                    
                    # Send the PDF to the user
                    send_form_pdf(phone_number, pdf_output_path)
                    
                    # Reset form mode and data for the next form request
                    form_mode[phone_number] = False
                    del form_data[phone_number]
                    
                    # Confirmation message
                    # send_message(phone_number, "Form sent successfully.")
        except KeyError:
            pass  # Handle if 'type' or 'text' key is not present in the received data

    else:        
        print(f"Received message: {message} from phone_number: {phone_number}")
            
        if message.strip() in ["Clerical", "Officer", "BM"]:
            print("Received position from user")
            # Handle the reply to the options message
            position = message.strip()  # Get the position from the message
            print(f"Received position from user: {position}")
            # filtered_data = db.find({"position": position, "status": ""})
            if phone_number in active_sheets:
                active_sheet_info = active_sheets[phone_number]
                spreadsheet = active_sheet_info["spreadsheet"]
                worksheet = active_sheet_info["worksheet"]
                worksheet_name = active_sheet_info["worksheet_name"]

                # Retrieve questions from the active sheet
                questions = get_questions_from_spreadsheet(worksheet)
                print(f"Retrieved questions from active sheet: {questions}")
                if phone_number in active_sheets:
                    active_sheets.pop(phone_number)
                filtered_data = db.find({"position": position})
                documents = list(filtered_data)
                print(f"Documents: {documents}")
                for doc in documents:
                    print(doc)
                # Call send_branch_images function with the filtered data
                send_branch_images(documents, questions)
            else:
                print(f"No active sheet found for user {phone_number}")

        # Check if the message is a question
        else:
            data_1 = request.json
            print("Data Type", data_1)
            try:
                number = data_1['waId']
                print(number)

                message_type = data_1.get('type')
                print("Message Type:", message_type)

                if data_1['type'] == 'text':
                    incoming_message = data_1['text']
                    print("Incoming Message:", incoming_message)
                    
                    # Retrieve the pending question for this phone number
                    if phone_number in pending_questions:
                        question_text = pending_questions[phone_number]
                        print("Question Text:", question_text)
                        
                        # Construct the answer data
                        answer_data = {
                            "phone_number": phone_number,
                            "question_text": question_text,
                            "answer_text": incoming_message
                        }
                        
                        # Insert the answer data into the database
                        answers_db.insert_one(answer_data)
                        # Remove the pending question from the dictionary
                        del pending_questions[phone_number]
                    else:
                        print("No pending question found for phone number:", phone_number)
                elif data_1['type'] == 'interactive':
                    incoming_message = data_1['text']
                    print("Incoming Message:", incoming_message)
                    
                    # Retrieve the pending question for this phone number
                    if phone_number in pending_questions:
                        question_text = pending_questions[phone_number]
                        print("Question Text:", question_text)
                        
                        # Construct the answer data
                        answer_data = {
                            "phone_number": phone_number,
                            "question_text": question_text,
                            "answer_text": incoming_message
                        }
                        
                        # Insert the answer data into the database
                        answers_db.insert_one(answer_data)
                        # Remove the pending question from the dictionary
                        del pending_questions[phone_number]
                    else:
                        print("No pending question found for phone number:", phone_number)


                elif data_1['type'] == 'image' or data_1['type'] == 'document':
                    print("Full request data:", data_1)
                    incoming_image = data_1.get('data')
                    print("Received Incoming Image:", incoming_image)
                    filename = re.findall("data.+", data_1['data'])[0]  # Extract the filename
                    # filename = "generated_filename.jpg"
                    print("Generated image filename:", filename)
                    if not allowed_file(filename):
                        raise Exception("Invalid file type.")
                    
                    loc = "E:\\NewProject\\Python\\Corprate App\\Question&AnswerBot\\After Modification\\Latest\\daily_bot_using_excel\\images"
                    image_path = upload_image(filename, loc)
                    
                    # Retrieve the pending question for this phone number
                    if phone_number in pending_questions:
                        question_text = pending_questions[phone_number]
                        print("Question Text:", question_text)
                        
                        # Construct the answer data
                        answer_data = {
                            "phone_number": phone_number,
                            "question_text": question_text,
                            "answer_image": image_path
                        }
                        
                        # Insert the answer data into the database
                        answers_db.insert_one(answer_data)
                        # Remove the pending question from the dictionary
                        del pending_questions[phone_number]
                    else:
                        print("No pending question found for phone number:", phone_number)
                else:
                    return jsonify({"status": "error", "message": "Invalid question number. Please try again."}), 400


            except Exception as e:
                print(e)
                print("message sent")  

            return jsonify({"status": "error", "message": "Invalid message type."}), 400

def extract_question_number(message):
    # Split the message into words
    words = message.split()
    
    for word in words:
        # Remove any trailing period
        if word.endswith('.'):
            word = word[:-1]
        
        # Check if the word is a digit
        if word.isdigit():
            return int(word)
    
    return None  # Return None if no question number was found

def create_excel_report(user_answers):
    # Create a DataFrame from the user answers
    df = pd.DataFrame(user_answers)

    # Get the current date to create a filename with just the date
    current_date = datetime.date.today()
    formatted_date = current_date.strftime("%Y-%m-%d")
    output_folder_path = "E:\\NewProject\\Python\\Corprate App\\Question&AnswerBot\\After Modification\\Latest\\daily_bot_using_excel\\Output"
    file_name = f"answer_{formatted_date}.xlsx"
    file_path = os.path.join(output_folder_path, file_name)

    # Save the Excel file using the full file path
    df.to_excel(file_path, index=False)



def generate_report():
    print("Report generation task executed at", time.ctime())
    print("generate_report function started")  # Print when the function starts
    user_answers = retrieve_user_answers()
    print(f"user_answers: {user_answers}")  # Print the user answers
    create_excel_report(user_answers)
    print("Excel report created")  # Print after the report is created

    mongo.db.answers.delete_many({})

    phone_number = "919159464023"
    print(f"Sending file to: {phone_number}")
    send_file(phone_number)
  

def send_file(phone_number):
    dir = 'E:\\NewProject\\Python\\Corprate App\\Question&AnswerBot\\After Modification\\Latest\\daily_bot_using_excel\\Output'
    # phone_number = "917892409211"
    # Get the current date to create the file name
    current_date = datetime.date.today()
    formatted_date = current_date.strftime("%Y-%m-%d")
    
    file_name = f'answer_{formatted_date}.xlsx'
    file_path = f'{dir}/{file_name}'
    caption = 'Your daily report'
    send_excel_file(phone_number, file_path, caption)

allowed_extensions=["png", "jpg", "jpeg"]
    
@app.route('/')
def home():
  return "Ink Pen Bot Live 1.0"

@app.route("/webhook", methods=['GET'])
def connetwebhook():
    return "running whatsapp webhook"


@app.route('/webhook', methods=['POST'])
def webhook():

    try:
        message_id = request.json.get('id')

        # Check if the message has already been processed
        
        if message_id in processed_message_ids:
            print(f"Message with ID {message_id} has already been processed. Skipping...")
            return jsonify({'message': 'Webhook skipped because message already processed'}), 200
        else:
            processed_message_ids.add(message_id)
        # Extract message details from request
        json_data = request.json
        print(f"Received POST request with JSON: {json_data}")

        # Extract message text and phone number
        message = json_data.get('text')
        phone_number = json_data.get('waId')

        # Check if the message is a list reply
        list_reply = json_data.get('listReply')
        if list_reply:
            message = list_reply.get('title')

        # Check if the message is an image reply
        if json_data.get('type') == 'image':
            message = json_data.get('data')  # Use the data from the image as the message

        print(f"Received POST request with message: {message} and phone number: {phone_number}")

        # Process the message and save the response
        process_message(phone_number, message)

        return jsonify({'message': 'Webhook executed successfully'}), 200

    except Exception as e:
        logging.exception("An error occurred: %s", e)
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__': 
    # Schedule the task to reset question count and status
    # scheduler.add_job(reset_question_count_and_status, trigger=CronTrigger(hour=12, minute=50))

    # Schedule the task to generate a report
    scheduler.add_job(generate_report, trigger=CronTrigger(hour=18, minute=10))

    # Schedule the task to send new questions periodically
    # scheduler.add_job(send_new_questions_periodically, IntervalTrigger(minutes=2))

    # scheduler.add_job(send_reminder_to_staff_with_no_answers, trigger=CronTrigger(hour=15, minute=16))

    # Start the schedulers
    scheduler.start()
    app.run(debug=True)

