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
suggestion_db = db["suggestion"]  # Assuming "suggestions" is the name of the collection
staff_db = db["staff"]

suggestion_mode = {}
suggestion_counter = 0
def send_message(contact_number, message):
	headers = {
					'Authorization': ACCESS_TOKEN,
				}
	payload={'messageText': message}

	url = f"{API_URL}/api/v1/sendSessionMessage/"+ f'{contact_number}'
	response = requests.post(url=url, headers=headers,data=payload)
	return response.status_code

def start_suggestion_mode(phone_number):
    """
    Start suggestion mode for the given phone number.
    """
    suggestion_mode[phone_number] = True
    response = "You are now in suggestion mode. Send your suggestion."
    send_message(phone_number, response)

def process_suggestion(phone_number, data_2):
    """
    Process suggestion received from the user.
    """
    try:
        number = data_2['waId']
        print(number)

        if data_2['type'] == 'text':
            received_message = data_2['text']
            print(received_message)
            
            staff_data = staff_db.find_one({"phone_number": number})

            if staff_data:
                    last_suggestion = suggestion_db.find_one({"phone_number": number}, sort=[("suggestion_no", -1)])
                    last_suggestion_no = last_suggestion["suggestion_no"] if last_suggestion else "1000000"

                    # # Increment the last suggestion number and generate the new suggestion number
                    # new_suggestion_no = str(int(last_suggestion_no) + 1)

                    # Extract the number part from last_suggestion_no and convert it to an integer
                    if last_suggestion_no.startswith("S_"):
                        last_suggestion_number = int(last_suggestion_no.split("_")[1])
                    else:
                        last_suggestion_number = int(last_suggestion_no)

                    # If it's the first suggestion, start with 10000001
                    if last_suggestion_number < 1000001:
                        new_suggestion_number = 1000001
                    else:
                        # Increment the suggestion number
                        new_suggestion_number = last_suggestion_number + 1

                    # Construct the new suggestion number with the "S_" prefix
                    new_suggestion_no = f"S_{new_suggestion_number}"

                    # Create the suggestion data
                    suggestion_data = {
                        "suggestion_no": new_suggestion_no,
                        "name": staff_data.get("name", ""),
                        "position": staff_data.get("position", ""),                         
                        "branch": staff_data.get("branch", ""),                       
                        "phone_number": staff_data.get("phone_number", ""),
                        "suggestion": received_message
                    }
                    suggestion_db.insert_one(suggestion_data)
                    send_message(phone_number, "Thank you for your Suggestion.")

            # suggestion_counter += 1
            suggestion_mode[phone_number] = False
            send_message(phone_number, "Suggestion mode ended.")
    except Exception as e:
        print(e)
        print("Error in suggestion mode")