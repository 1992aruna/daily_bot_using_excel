import pymongo
import os
import requests
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
API_URL = os.getenv("API_URL")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

# Initialize MongoDB client
client = pymongo.MongoClient(MONGO_URI)

# Access the desired database
db = client["sbi"]
feedback_db = db["feedback"]
staff_db = db["staff"]


feedback_mode = {}

def send_message(contact_number, message):
    headers = {
        'Authorization': ACCESS_TOKEN,
    }
    payload = {'messageText': message}
    url = f"{API_URL}/api/v1/sendSessionMessage/{contact_number}"
    response = requests.post(url=url, headers=headers, data=payload)
    return response.status_code

def start_feedback_mode(phone_number):
    feedback_mode[phone_number] = True
    response = "You are now in Feedback mode. Send your Feedback."
    send_message(phone_number, response)

def process_feedback(phone_number, data_2):
    try:
        number = data_2['waId']
        print(number)

        if data_2['type'] == 'text':
            received_message = data_2['text']
            print(received_message)
            
            staff_data = staff_db.find_one({"phone_number": number})

            if staff_data:
                last_feedback = feedback_db.find_one({}, sort=[("feedback_no", -1)])
                last_feedback_no = last_feedback["feedback_no"] if last_feedback else "F_1000000"

                # Extract the number part from last_feedback_no and convert it to an integer
                if last_feedback_no.startswith("F_"):
                    last_feedback_number = int(last_feedback_no.split("_")[1])
                else:
                    last_feedback_number = int(last_feedback_no)

                # If it's the first feedback, start with 1000001
                if last_feedback_number < 1000001:
                    new_feedback_number = 1000001
                else:
                    # Increment the feedback number
                    new_feedback_number = last_feedback_number + 1

                # Construct the new feedback number with the "F_" prefix
                new_feedback_no = f"F_{new_feedback_number}"

                # Create the feedback data
                feedback_data = {
                    "feedback_no": new_feedback_no,
                    "name": staff_data.get("name", ""),
                    "position": staff_data.get("position", ""),                         
                    "branch": staff_data.get("branch", ""),                       
                    "phone_number": staff_data.get("phone_number", ""),
                    "feedback": received_message
                }
                feedback_db.insert_one(feedback_data)
                send_message(phone_number, f"Thank you for your Feedback.")

            else:
                # If no staff data is found, insert a feedback without staff details
                new_feedback_number = 1000001
                new_feedback_no = f"F_{new_feedback_number}"
                feedback_data = {
                    "feedback_no": new_feedback_no,
                    "name": staff_data.get("name", ""),
                    "position": staff_data.get("position", ""),                         
                    "branch": staff_data.get("branch", ""), 
                    "phone_number": number,
                    "feedback": received_message
                }
                feedback_db.insert_one(feedback_data)
                send_message(phone_number, f"Thank you for your Feedback.")

            feedback_mode[phone_number] = False
            send_message(phone_number, "Feedback mode ended.")
    except Exception as e:
        print(e)
        print("Error in feedback mode")

