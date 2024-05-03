import pymongo
import os
import requests
from dotenv import load_dotenv
# from messages import send_message

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
API_URL=os.getenv("API_URL")
ACCESS_TOKEN=os.getenv("ACCESS_TOKEN")
# Initialize MongoDB client
client = pymongo.MongoClient(MONGO_URI)

# Access the desired database
db = client["sbi"]
feedback_db = db["feedbacks"]  # Assuming "feedbacks" is the name of the collection

feedback_mode = {}
feedback_counter = 0
def send_message(contact_number, message):
	headers = {
					'Authorization': ACCESS_TOKEN,
				}
	payload={'messageText': message}

	url = f"{API_URL}/api/v1/sendSessionMessage/"+ f'{contact_number}'
	response = requests.post(url=url, headers=headers,data=payload)
	return response.status_code

def start_feedback_mode(phone_number):
    """
    Start feedback mode for the given phone number.
    """
    feedback_mode[phone_number] = True
    response = "You are now in feedback mode. Send your feedback."
    send_message(phone_number, response)

def process_feedback(phone_number, data_2):
    """
    Process feedback received from the user.
    """
    try:
        number = data_2['waId']
        print(number)

        if data_2['type'] == 'text':
            received_message = data_2['text']
            print(received_message)
            
            staff_data = feedback_db.find_one({"phone_number": number})

            if staff_data:
                    last_feedback = feedback_db.find_one({"phone_number": number}, sort=[("feedback_no", -1)])
                    last_feedback_no = last_feedback["feedback_no"] if last_feedback else "1000000"

                    # # Increment the last feedback number and generate the new feedback number
                    # new_feedback_no = str(int(last_feedback_no) + 1)

                    # Extract the number part from last_feedback_no and convert it to an integer
                    if last_feedback_no.startswith("S_"):
                        last_feedback_number = int(last_feedback_no.split("_")[1])
                    else:
                        last_feedback_number = int(last_feedback_no)

                    # If it's the first feedback, start with 10000001
                    if last_feedback_number < 1000001:
                        new_feedback_number = 1000001
                    else:
                        # Increment the feedback number
                        new_feedback_number = last_feedback_number + 1

                    # Construct the new feedback number with the "S_" prefix
                    new_feedback_no = f"S_{new_feedback_number}"

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

            # feedback_counter += 1
            feedback_mode[phone_number] = False
            send_message(phone_number, "feedback mode ended.")
    except Exception as e:
        print(e)
        print("Error in feedback mode")