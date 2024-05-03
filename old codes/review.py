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
user_reviews_db = mongo.db.reviews

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
    return response.status_code


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

def save_question_to_database_and_spreadsheet(phone_number, questions, worksheet):
    # Assuming you have a collection named 'questions' in your MongoDB
    questions_collection = mongo.db.questions

    try:
        starting_id = 10000
        starting_id = get_latest_question_id() + 1

        for question_text in questions:
            # # Generate a five-digit question ID
            # question_id = str(current_id).zfill(5)
            
            starting_id = get_latest_question_id() + 1
            question_id = starting_id
            # Save to the database
            question_doc = {
                "_id": ObjectId(),
                "created_By": phone_number,
                "question_id": question_id,
                "question_text": question_text,
            }
            result = questions_collection.insert_one(question_doc)
    
            if result.inserted_id:
                print(f"Question saved to the 'questions' collection for phone number: {phone_number}")
                starting_id += 1  # Increment the current ID for the next question
            else:
                print(f"Failed to save question to the 'questions' collection for phone number: {phone_number}")

            # Save to the spreadsheet
            # spreadsheet = client.open('Daily_Questions')
            # worksheet = spreadsheet.worksheet('Sheet2')
            combined_question = f"{question_id}. {question_text}"
            worksheet.append_row([combined_question])
            # worksheet.append_row([question_id, question_text])
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
        questions = worksheet.col_values(1)
        return questions
        # return questions[:10]
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
                        send_questions_to_contact(phone_number, questions)
                        send_message(phone_number, f"Please provide your answers in the following format: 1. Answer")
                        print(f"Questions sent for branch {branch} phone number {phone_number}")
                        db.update_one({"_id": staff["_id"]}, {"$set": {"status": "sent"}})

                        if alternate_phone_number and alternate_phone_number != phone_number:
                            print("Sending to alternate phone number:", alternate_phone_number)
                            send_image_message(alternate_phone_number, image_path, caption)
                            print(f"Image sent for branch {branch} to alternate phone number {alternate_phone_number}")
                            send_questions_to_contact(alternate_phone_number, questions)
                            send_message(alternate_phone_number, f"Please provide your answers in the following format: 1. Answer")
                            print(f"Questions sent for branch {branch} to alternate phone number {alternate_phone_number}")
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
review_mode = {}


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

# def handle_review():
#     global review_mode
#     print("Executing Review Questions function.....")
#     # Get all staff members with an empty review_status
#     staff_members = db.find({"review_status": ""})

#     for staff_member in staff_members:
#         phone_number = staff_member["phone_number"]
#         print("Phone Number:", phone_number)
        
#         # Adding phone number to review_mode
#         review_mode[phone_number] = True
#         print("Review mode for", phone_number, "set to True")

#         # Sending the review question
#         send_reply_button(phone_number, "Have you done marketing today?\n", marketing_buttons)
        
#         # Update review_status to indicate that the question has been sent
#         db.update_one({"_id": staff_member["_id"]}, {"$set": {"review_status": "sent"}})


def handle_review():
    global review_mode
    print("Executing Review Questions function.....")
    # Get all staff members with an empty review_status
    staff_members = db.find({"review_status": ""})

    for staff_member in staff_members:
        phone_number = staff_member["phone_number"]
        print("Phone Number:", phone_number)
        
        # Check if the question already exists
        existing_question = user_reviews_db.find_one({"question_text": "Have you done marketing today?"})
        if existing_question:
            question_id = existing_question["_id"]
        else:
            # Insert the question into the questions collection
            question_id = user_reviews_db.insert_one({"question_text": "Have you done marketing today?"}).inserted_id

        # Adding phone number to review_mode
        review_mode[phone_number] = {"question_id": question_id}
        print("Review mode for", phone_number, "set to True")

        # Sending the review question
        send_reply_button(phone_number, "Have you done marketing today?\n", marketing_buttons)
        
        # Update review_status to indicate that the question has been sent
        db.update_one({"_id": staff_member["_id"]}, {"$set": {"review_status": "sent"}})
scheduler.add_job(handle_review, trigger=CronTrigger(hour=11, minute=30))

# Function to handle user responses to questions
def process_review_response(phone_number, received_message):
    # Check if the "Have you done marketing today?" question already exists
    existing_question1 = user_reviews_db.find_one({"question_text": "Have you done marketing today?"})
    if existing_question1:
        question_id1 = existing_question1["_id"]
    else:
        # Insert the "Have you done marketing today?" question into the questions collection
        question_id1 = user_reviews_db.insert_one({"question_text": "Have you done marketing today?"}).inserted_id

    # Update the document with the corresponding question ID in the responses array for the first question
    user_reviews_db.update_one(
        {"_id": question_id1},
        {"$push": {"responses": {"answered_by": phone_number, "answer": received_message}}},
        upsert=True
    )
def process_review_response1(phone_number, received_message):
    # Check if the "How many people have you met?" question already exists
    existing_question2 = user_reviews_db.find_one({"question_text": "How many people have you met?"})
    if existing_question2:
        question_id2 = existing_question2["_id"]
    else:
        # Insert the "How many people have you met?" question into the questions collection
        question_id2 = user_reviews_db.insert_one({"question_text": "How many people have you met?"}).inserted_id

    # Update the document with the corresponding question ID in the responses array for the second question
    user_reviews_db.update_one(
        {"_id": question_id2},
        {"$push": {"responses": {"answered_by": phone_number, "answer": received_message}}},
        upsert=True
    )

def process_review_response2(phone_number, image_path):
    # Check if the "How many people have you met?" question already exists
    existing_question3 = user_reviews_db.find_one({"question_text": "Please share a photo of your marketing."})
    if existing_question3:
        question_id3 = existing_question3["_id"]
    else:
        # Insert the "How many people have you met?" question into the questions collection
        question_id3 = user_reviews_db.insert_one({"question_text": "Please share a photo of your marketing."}).inserted_id

    # Update the document with the corresponding question ID in the responses array for the second question
    user_reviews_db.update_one(
        {"_id": question_id3},
        {"$push": {"responses": {"answered_by": phone_number, "image_path": image_path}}},
        upsert=True
    )

def process_review_response3(phone_number, received_message):
    # Check if the "Have you done marketing today?" question already exists
    existing_question4 = user_reviews_db.find_one({"question_text": "Suggest me some good way to marketing ?"})
    if existing_question4:
        question_id4 = existing_question4["_id"]
    else:
        # Insert the "Have you done marketing today?" question into the questions collection
        question_id4 = user_reviews_db.insert_one({"question_text": "Suggest me some good way to marketing ?"}).inserted_id

    # Update the document with the corresponding question ID in the responses array for the first question
    user_reviews_db.update_one(
        {"_id": question_id4},
        {"$push": {"responses": {"answered_by": phone_number, "answer": received_message}}},
        upsert=True
    )


# Function to save form data
def save_form_data(phone_number, form_data):
    form_db.insert_one({"phone_number": phone_number, "name": form_data["name"], "age": form_data["age"], "qualification": form_data["qualification"]})
    # Once the data is saved, you can proceed with converting it to PDF and sending it

def process_message(phone_number, message):
    global help_requested, review_mode, questions, suggestion_counter, feedback_counter
    # global global_questions
    questions = {} 
      
    print("Review Mode", review_mode)
    data_4 = request.json
    message_type = data_4.get('type')

    if message_type == 'image':
        # Handle image type message
        print("Received an image type message")
        # Add your image handling logic here
        if review_mode:
            print("Mode IN", review_mode)
            # Check if the message is a response to the review question
            data_2 = request.json
            print("Data", data_2)
            try:
                number = data_2['waId']
                print("Phone Number", number)

                received_message = data_2['text']  # Convert the message to lowercase for case insensitivity
                print("Received Text", received_message)

                if review_mode.get(phone_number) == "waiting_for_image":
                        data_2['type'] == 'image'
                        print("Full request data:", data_2)
                        incoming_image = data_2.get('data')
                        print("Received Incoming Image:", incoming_image)
                        filename = re.findall("data.+", data_2['data'])[0]  # Extract the filename
                        # filename = "generated_filename.jpg"
                        print("Generated image filename:", filename)
                        if not allowed_file(filename):
                            raise Exception("Invalid file type.")
                        
                        loc = "E:\\NewProject\\Python\\Corprate App\\Question&AnswerBot\\After Modification\\Latest\\daily_bot_using_excel\\Review_images"
                        image_path = upload_image(filename, loc)
                        process_review_response2(phone_number, image_path)
                        send_message(phone_number, "Suggest me some good way to marketing ?")
                        review_mode[phone_number] = "waiting_for_comment"

                else:
                    # Handle invalid responses
                    send_message(phone_number, "Please upload an image.")
            except Exception as e:
                print(e)
                print("Error processing review response")

    elif message.startswith("/create"):
        user = db.find_one({"phone_number": phone_number})
        if user and user.get("position") in ["BM", "RM"]:
            user_in_question_creation_mode[phone_number] = True
            print(f"User {phone_number} entered question creation mode.")
            send_message(phone_number, "You are now in question creation mode. Send your questions one by one.")
            
            # Check if the user has an active sheet, create one if not
            if phone_number not in active_sheets:
                spreadsheet, worksheet, worksheet_name = open_spreadsheet()
                active_sheets[phone_number] = {"spreadsheet": spreadsheet, "worksheet": worksheet, "worksheet_name": worksheet_name}

            questions[phone_number] = []  # Initialize questions for this user
            print(f"questions after /create: {questions}")

        else:
            send_message(phone_number, "Permission denied. You don't have the necessary position to create questions.")

    elif user_in_question_creation_mode.get(phone_number, False):
        if message.strip() == "/end":
            send_message(phone_number, "Question creation mode ended.")
            user_in_question_creation_mode[phone_number] = False
            
            options_message = "To whom do you want to send the questions?\n1. Clerical\n2. Officer\n3. BM"
            send_message(phone_number, options_message)

        else:
            questions_to_save = questions.get(phone_number, [])
            questions_to_save.append(message)
            questions[phone_number] = questions_to_save

            print(f"questions_to_save: {questions_to_save}")

            if questions_to_save and "/end" not in questions_to_save:
                save_question_to_database_and_spreadsheet(phone_number, questions_to_save, active_sheets[phone_number]["worksheet"])

            send_message(phone_number, f"To end, send '/end'.")

    
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

    
    # elif review_mode.get(phone_number, False):
    elif review_mode:
        print("Mode IN", review_mode)
        # Check if the message is a response to the review question
        data_2 = request.json
        print("Data", data_2)
        try:
            number = data_2['waId']
            print("Phone Number", number)

            received_message = data_2['text']  # Convert the message to lowercase for case insensitivity
            print("Received Text", received_message)

            if received_message in ["Yes", "No"]:

                process_review_response(phone_number, received_message)
                # Handle the response (you can send another question here)
                send_message(phone_number, "How many people have you met?")
                review_mode[phone_number] = "waiting_for_number"

            elif review_mode.get(phone_number) == "waiting_for_number":
                try:
                    received_message = int(received_message)
                    process_review_response1(phone_number, received_message)
                    send_message(phone_number, "Please share a photo of your marketing.")
                    review_mode[phone_number] = "waiting_for_image"
                except ValueError:
                    # Handle the case where the received message is not a valid number
                    send_message(phone_number, "Please respond with a valid number.")
            
            elif review_mode.get(phone_number) == "waiting_for_comment":
                if received_message:
                    comment = received_message
                    process_review_response3(phone_number, received_message)
                    send_message(phone_number, "Thank You.")
                    review_mode[phone_number] = False
                else:
                    # Handle the case where the received message is not a valid number
                    send_message(phone_number, "Please send valid message.")

            else:
                # Handle invalid responses
                send_message(phone_number, "Please respond with 'Yes' or 'No'.")
        except Exception as e:
            print(e)
            print("Error processing review response")



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
                    print(incoming_message)

                    response_number, answer = incoming_message.split(". ", 1)
                    print(response_number)
                    print(answer)

                    question_id = int(response_number)
                    print(question_id)
                    question_data = questions_db.find_one({"question_id": question_id})

                    if question_data:
                        # Check if an entry with the same "answered_by" and "created_By" values exists
                        existing_entry = answers_db.find_one({"answered_by": number, "created_By": question_data["created_By"]})

                        if existing_entry:
                            # If the same "answered_by" and "created_By" values exist, update the existing entry
                            filter_query = {"answered_by": number, "created_By": question_data["created_By"]}
                            update_query = {
                                "$set": {
                                    "question_"+str(question_data["question_id"]): question_data["question_text"],
                                    "answer_"+str(question_data["question_id"]): answer
                                }
                            }
                            answers_db.update_one(filter_query, update_query)

                            return jsonify({"status": "success", "message": "Answer updated."}), 200
                        else:
                            # If no entry with the same "answered_by" and "created_By" values exists, insert a new one
                            answer_data = {
                                "created_By": question_data["created_By"],
                                "answered_by": number,
                                "question_"+str(question_data["question_id"]): question_data["question_text"],
                                "answer_"+str(question_data["question_id"]): answer
                            }
                            answers_db.insert_one(answer_data)

                            return jsonify({"status": "success", "message": "Answer recorded."}), 200
                    else:
                        return jsonify({"status": "error", "message": "Invalid question number. Please try again."}), 400
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
                    # caption = data_1.get('text', '')
                    # print("Received image caption:", caption)
                    # if caption and ". " in caption:
                    #     response_number = caption.split(". ", 1)
                    #     print("Response Number:", response_number)
                    #     print("Answer:", answer)
                    # else:
                    #     print("Caption is None or does not contain the delimiter '. '")
                    #     # Provide a default value for response_number or handle the situation accordingly
                    #     response_number = None  # Assigning a default value

                    # Extract the caption and remove leading/trailing whitespace
                    caption = data_1.get('text', '').strip()
                    print("Received image caption:", caption)
                    # Check if the caption contains a valid question number
                    if caption:
                        try:
                            response_number = int(caption)
                            print("Response Number:", response_number)
                        except ValueError:
                            print("Invalid question number:", caption)
                    else:
                        print("Caption is empty or None")


                    question_id = int(response_number)
                    print(question_id)
                    question_data = questions_db.find_one({"question_id": question_id})

                    if question_data:
                        # Check if an entry with the same "answered_by" and "created_By" values exists
                        existing_entry = answers_db.find_one({"answered_by": number, "created_By": question_data["created_By"]})

                        if existing_entry:
                            # If the same "answered_by" and "created_By" values exist, update the existing entry
                            filter_query = {"answered_by": number, "created_By": question_data["created_By"]}
                            update_query = {
                                "$set": {
                                    "question_"+str(question_data["question_id"]): question_data["question_text"],
                                    # "answer_"+str(question_data["question_id"]): answer,
                                    "answer_image_"+str(question_data["question_id"]): image_path
                                }
                            }
                            answers_db.update_one(filter_query, update_query)

                            return jsonify({"status": "success", "message": "Answer updated."}), 200
                        else:
                            # If no entry with the same "answered_by" and "created_By" values exists, insert a new one
                            answer_data = {
                                "created_By": question_data["created_By"],
                                "answered_by": number,
                                "question_"+str(question_data["question_id"]): question_data["question_text"],
                                # "answer_"+str(question_data["question_id"]): answer,
                                "answer_image_"+str(question_data["question_id"]): image_path
                            }
                            answers_db.insert_one(answer_data)

                            return jsonify({"status": "success", "message": "Answer recorded."}), 200
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

# def process_input_message(phone_number, message):
#     valid_formats = ['/create', '/help', '/ask', '/end']

#     if not any(message.startswith(format) or message.lower() == format for format in valid_formats) and not message.startswith(tuple(['/{}.'.format(i) for i in range(10)])):
#         alert_message = "Please use one of the valid formats: /create, /help, /ask, /end, {question_id}. {something}"
#         send_message(phone_number, alert_message)
#     else:
#         print("Valid input")
    
@app.route('/')
def home():
  return "Ink Pen Bot Live 1.0"

@app.route("/webhook", methods=['GET'])
def connetwebhook():
    return "running whatsapp webhook"


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Extract message details from request
        # generate_report()
        print(f"Received POST request with JSON: {request.json}")
        message = request.json.get('text')
        phone_number = request.json.get('waId')

        print(f"Received POST request with message: {message} and phone number: {phone_number}")

        # # Process the message and save the response
        # process_input_message(phone_number, message)
        
        process_message(phone_number, message)

        # generate_report()        
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
    scheduler.add_job(send_new_questions_periodically, IntervalTrigger(minutes=2))

    # scheduler.add_job(handle_review, IntervalTrigger(minutes=2))

    # scheduler.add_job(send_reminder_to_staff_with_no_answers, trigger=CronTrigger(hour=15, minute=16))

    # Start the schedulers
    scheduler.start()
    app.run(debug=True)

