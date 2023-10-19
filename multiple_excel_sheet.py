from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import os
import requests
import pandas as pd
from pymongo import MongoClient
from dotenv import load_dotenv
from messages import *
from utils import retrieve_user_answers, send_excel_file
from google.oauth2 import service_account
import gspread
import logging
import schedule
import re
import datetime
import time
import openai

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

def get_questions_from_spreadsheet(sheet_titles):
    all_questions = []  # Initialize a list to store all questions

    try:
        sheet_titles = ["Daily_Questions", "Daily_Questions1"]
        for sheet_title in sheet_titles:
            # Open the Google Sheets document by its title
            spreadsheet = client.open(sheet_title)
            worksheet = spreadsheet.worksheet('Sheet1')

            # Get the questions from the worksheet
            questions = worksheet.col_values(1)

            # Extend the list of all questions with the questions from this sheet
            all_questions.extend(questions)

        return all_questions
    except Exception as e:
        print(f"Error fetching questions from the Google Spreadsheet: {str(e)}")
        return []

# Modify send_questions_to_contact to include the department name
def send_questions_to_contact(contact_number, questions):
    question_count = 0  # Initialize the question count to 0

    for question in questions:
        send_message(contact_number, question)
        question_count += 1  # Increment the question count for each sent question

    # Update the user's document in the staff database with the question count
    db.update_one({"phone_number": contact_number}, {"$set": {"questions_sent_count": question_count}})
    
    return question_count  # Return the total question count


def send_questions_with_():
    try:
        print("Executing send_questions_with_ function")

        # Specify the titles of your Excel sheets
        sheet_titles = ["Daily_Questions", "Daily_Questions1"]

        for sheet_title in sheet_titles:
            # Get questions and  from the sheet
            questions = get_questions_from_spreadsheet(sheet_title)


            for staff in db.find({}):
                if 'phone_number' in staff:
                    phone_number = staff['phone_number']
                    questions_sent_count = staff.get("questions_sent_count", 0)

                    # Calculate the number of new questions
                    new_questions_count = len(questions) - questions_sent_count

                    if new_questions_count > 0:
                        new_questions = questions[questions_sent_count:questions_sent_count + new_questions_count]

                        # Send questions along with department names
                        send_questions_to_contact(phone_number, new_questions)
                        print(f"Sent {new_questions_count} new questions to {phone_number} from department {[0]}")

                        # Update the questions_sent_count in the database
                        db.update_one(
                            {"_id": staff["_id"]},
                            {"$set": {"questions_sent_count": questions_sent_count + new_questions_count}}
                        )

        print("Execution of send_questions_with_ function completed")

    except Exception as e:
        print(f"An error occurred: {str(e)}")

# # Schedule the task to send questions with 
# scheduler.add_job(send_questions_with_, trigger=IntervalTrigger(minutes=2))

# scheduler.start()

    
def send_branch_images():
    try:
        sheet_titles = ["Daily_Questions", "Daily_Questions1"]

        for sheet_title in sheet_titles:
            # Get questions from the sheet
            questions = get_questions_from_spreadsheet(sheet_title)

            for staff in db.find({"status": ""}):
                if 'branch' in staff and 'phone_number' in staff:
                    branch = staff['branch']
                    phone_number = staff['phone_number']
                    alternate_phone_number = staff.get('alternate_phone_number')

                    print(f"Processing branch: {branch}, Primary Phone: {phone_number}, Alternate Phone: {alternate_phone_number}")

                    image_extensions = ['.png', '.jpg']
                    image_found = False

                    for ext in image_extensions:
                        image_path = f'E:\\NewProject\\Python\\daily_bot_using_excel\\branch_images\\{branch}{ext}'
                                        
                        if os.path.isfile(image_path):
                            image_found = True
                            print("Image exists. Sending to", phone_number)
                            caption = f'Here is your image for branch {branch}'
                            send_image_message(phone_number, image_path, caption)
                            print(f"Image sent for branch {branch} with extension {ext}")

                            # Send the worksheet name as a message
                            send_message(phone_number, sheet_title)

                            # Send questions
                            send_questions_to_contact(phone_number, questions)
                            print(f"Questions sent for branch {branch} phone number {phone_number}")
                            db.update_one({"_id": staff["_id"]}, {"$set": {"status": "sent"}})

                            if alternate_phone_number and alternate_phone_number != phone_number:
                                print("Sending to alternate phone number:", alternate_phone_number)
                                send_image_message(alternate_phone_number, image_path, caption)
                                print(f"Image sent for branch {branch} to alternate phone number {alternate_phone_number}")

                                # Send the worksheet name as a message to the alternate phone
                                send_message(alternate_phone_number, sheet_title)

                                # Send questions to the alternate phone
                                send_questions_to_contact(alternate_phone_number, questions)
                                print(f"Questions sent for branch {branch} to alternate phone number {alternate_phone_number}")
                                db.update_one({"_id": staff["_id"]}, {"$set": {"status": "sent"}})

                    if not image_found:
                        print(f"No image found for branch {branch}")
                    db.update_one({"_id": staff["_id"]}, {"$set": {"status": "sent"}})
                else:
                    print("Missing 'branch' or 'phone_number' field in the document.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")



def process_message(phone_number, message):
    
        spreadsheet = client.open('Daily_Questions')
        worksheet = spreadsheet.worksheet('Sheet1')

        questions = get_questions_from_spreadsheet(worksheet)

        print(f"Received message: {message} from phone_number: {phone_number}")
        
        question_number = extract_question_number(message)
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
            print(f"Updated responses in database for phone number: {phone_number}")
        else:
            # If no document exists, create a new one
            answers_received = {
                'phone_number': phone_number,
                f'question_{question_number}': question,
                f'answer_{question_number}': response_text,
            }
            result = mongo.db.answers_received.insert_one(answers_received)
            print(f"Inserted responses into database, received ID: {result.inserted_id}")

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
        
        print(f"Received POST request with JSON: {request.json}")
        message = request.json.get('text')
        phone_number = request.json.get('waId')

        print(f"Received POST request with message: {message} and phone number: {phone_number}")

        # Process the message and save the response
        process_message(phone_number, message)
        
        return jsonify({'message': 'Webhook executed successfully'}), 200
        
    except Exception as e:
        logging.exception("An error occurred: %s", e)
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    send_branch_images()
    app.run(debug=True)

