from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import os
import requests
import pandas as pd
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv
from messages import *
from utils import retrieve_user_answers, send_excel_file
from google.oauth2 import service_account
import gspread
import logging
import uuid
import datetime
import time
import openai
from openai.error import RateLimitError
from bson import ObjectId
import pymongo

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

# Open the Google Sheets document by its title
# spreadsheet = client.open('Daily_Questions')

# # Select the worksheet where you want to export data (if it exists)
# question_worksheet = spreadsheet.worksheet('Sheet1')  # Replace 'Sheet1' with your sheet name


# Load environment variables
load_dotenv()

# Replace with your MongoDB URI
# MONGO_DB = 'sbi'  # Replace with your database name
# STAFF_COLLECTION = 'staff'
# ANSWERS_COLLECTION = 'answers'

MONGO_URI = os.getenv("MONGO_URI")
API_URL = os.getenv("API_URL")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)

openai.api_key = OPENAI_API_KEY
app.config["MONGO_URI"] = MONGO_URI
mongo = PyMongo(app)
db = mongo.db.staff
answers_db = mongo.db.answers
# fs = gridfs.GridFS(mongo.db, collection="files")

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
# def filter_data_by_position(position):
#     try:
#         # Assuming 'position' is one of ["Clerical", "Officer", "BM"]
#         filtered_data = db.find({"position": position, "status": ""})

#         # for staff in filtered_data:
#         #     primary_phone_number = staff['phone_number']
#         #     alternate_phone_number = staff.get('alternate_phone_number')
#         #     questions = get_questions_from_spreadsheet(worksheet)  # Assuming you have a function to get questions

#         #     # Call the function to send branch images
#         #     send_branch_images(position, primary_phone_number, alternate_phone_number, questions)
            
#     except Exception as e:
#         print(f"An error occurred while filtering data: {str(e)}")

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

        # Check if there are answers for this staff member in the answers_received database
        answers = mongo.db.answers_received.find_one({'phone_number': phone_number})

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

    # Assuming you have a collection named "answers_received" for storing answers
    answers_received = mongo.db.answers_received.find_one({'phone_number': phone_number})

    if answers_received:
        # Iterate through the answers_received document and count answered questions
        for key in answers_received:
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
                    image_path = f'E:\\NewProject\\Python\\\Corprate App\\Question&AnswerBot\\After Modification\\Latest\\daily_bot_using_excel\\branch_images\\{branch}{ext}'
                                    
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
user_in_question_creation_mode = {}


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

def process_message(phone_number, message):
    
    global help_requested, questions
    # global global_questions
    questions = {}    

    if message.startswith("/create"):
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

            # Clear the active sheet for this user
            # if phone_number in active_sheets:
            #     active_sheets.pop(phone_number)
            
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
        # If the user sends "/help," let's use ChatGPT to provide assistance
        # gpt_response = chat_with_gpt("I need help with something.")
        # send_message(phone_number, gpt_response)
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
        except RateLimitError as e:
            print(f"Rate limit error: {str(e)}")
            send_message(phone_number, "/help is not available at the moment due to rate limit. Please try again later.")
            help_requested = False
        # except Exception as e:
        #     print(f"An error occurred: {str(e)}")
        #     send_message(phone_number, f"/help is not available at the moment. Please try again later.")
        #     help_requested = False
    elif help_requested:
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
        help_requested = False

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
            
            if not answer:
                answer = "I'm sorry, I couldn't find a question with that number."

            response = f"Question: {question}\nAnswer: {answer}"
        else:
            if not message.endswith('?'):
                message += '?'
            # User provided a regular question, let's search for the answer as usual
            answer = search_for_answer(message, worksheet)
            if not answer:
                response = "I couldn't find an answer to your question."
            else:
                response = answer
        send_message(phone_number, response)
        user_in_question_mode[phone_number] = False

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
            try:
                question_number = extract_question_number(message)
                if question_number is not None:
                    print(f"Extracted question number: {question_number}")

                    # Get the corresponding question
                    question = questions[question_number - 1]  # Subtract 1 because list indices start at 0
                
                    # Extract only the response text from the message
                    response_text = message.split('.', 1)[1].strip() if '.' in message else message

                    # Check if a document for this phone number already exists
                    answers_received = mongo.db.answers_received.find_one({'phone_number': phone_number})

                    if answers_received:
                        # If a document exists, update it with the new response
                        mongo.db.answers_received.update_one(
                            {'phone_number': phone_number},
                            {'$set': {f'question_{question_number}': question, f'answer_{question_number}': response_text}}
                        )
                        print(f"Updated responses in the database for phone number: {phone_number}")
                    else:
                        # If no document exists, create a new one
                        answers_received = {
                            'phone_number': phone_number,
                            f'question_{question_number}': question,
                            f'answer_{question_number}': response_text,
                        }
                        result = mongo.db.answers_received.insert_one(answers_received)
                        print(f"Inserted responses into the database, received ID: {result.inserted_id}")
    
            except Exception as e:
                print(f"An error occurred: {e}")

    

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

    mongo.db.answers_received.delete_many({})

    phone_number = "917892409211"
    print(f"Sending file to: {phone_number}")
    send_file(phone_number)
  

# # schedule.every().day.at("17:51").do(generate_report)
# # Schedule the generate_report function to run daily at 17:51
# scheduler.add_job(generate_report, trigger=CronTrigger(hour=12, minute=24))

# # Start the scheduler
# scheduler.start()

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
        # Extract message details from request
        # generate_report()
        print(f"Received POST request with JSON: {request.json}")
        message = request.json.get('text')
        phone_number = request.json.get('waId')

        print(f"Received POST request with message: {message} and phone number: {phone_number}")

        # Process the message and save the response
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
    # scheduler.add_job(generate_report, trigger=CronTrigger(hour=15, minute=32))

    # Schedule the task to send new questions periodically
    # scheduler.add_job(send_new_questions_periodically, IntervalTrigger(minutes=2))

    # scheduler.add_job(send_reminder_to_staff_with_no_answers, trigger=CronTrigger(hour=15, minute=16))

    # Start the schedulers
    scheduler.start()
    app.run(debug=True)

