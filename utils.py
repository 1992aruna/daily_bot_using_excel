# from app import API_URL, ACCESS_TOKEN
import os
import requests
# import gridfs
from dotenv import load_dotenv
from pymongo import MongoClient



""" 
Uncomment the below line for production  for pythonanywhere production and commit  the line : load_dotenv() 
and  vice vera for localhost
"""
#load_dotenv(os.path.join("/home/anton3richards/design_bot", '.env'))

load_dotenv()


MONGO_URI = os.getenv("MONGO_URI")  # Replace with your MongoDB URI
MONGO_DB = 'sbi'  # Replace with your database name
ANSWER_COLLECTION = 'answers_received'


API_URL=os.getenv("API_URL")
ACCESS_TOKEN=os.getenv("ACCESS_TOKEN")


#----------------------------------------Export to Excel----------------------------------------------------#

def retrieve_user_answers():
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    answer_collection = db[ANSWER_COLLECTION]
    user_answers = list(answer_collection.find())
    return user_answers

# --------------------------------------------SEND EXCEL------------------------------------------------------#
# def send_excel_to_phone_number(phone_number, file_path):
#     try:
#         # Send the Excel file to the specified phone number
#         message = client.messages.create(
#             to=f"whatsapp:{phone_number}",
#             from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
#             media_url=[f"file://{file_path}"],
#         )

#         print(f"Excel file sent to {phone_number}")
#         return True
#     except Exception as e:
#         print(f"Error sending Excel file: {str(e)}")
#         return False
def send_excel_file(phone_number, file_path, caption):
    url = f"{API_URL}/api/v1/sendSessionFile/{phone_number}?caption={caption}"

    payload = {}
    file_name = file_path.split('/')[-1]  # Extract the file name from the file path
    files = [
        ('file', (file_name, open(file_path, 'rb'), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))
    ]
    headers = {
        'Authorization': ACCESS_TOKEN
    }

    response = requests.post(url, headers=headers, json=payload, files=files)
    print(response)
    print(response.json())
