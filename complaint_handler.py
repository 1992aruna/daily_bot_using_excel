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
complaint_db = db["complaints"]  # Assuming "complaints" is the name of the collection

complaint_mode = {}
complaint_counter = 0
def send_message(contact_number, message):
	headers = {
					'Authorization': ACCESS_TOKEN,
				}
	payload={'messageText': message}

	url = f"{API_URL}/api/v1/sendSessionMessage/"+ f'{contact_number}'
	response = requests.post(url=url, headers=headers,data=payload)
	return response.status_code

def start_complaint_mode(phone_number):
    """
    Start complaint mode for the given phone number.
    """
    complaint_mode[phone_number] = True
    response = "You are now in complaint mode. Send your complaint."
    send_message(phone_number, response)

def process_complaint(phone_number, data_2):
    """
    Process complaint received from the user.
    """
    try:
        number = data_2['waId']
        print(number)

        if data_2['type'] == 'text':
            received_message = data_2['text']
            print(received_message)
            
            staff_data = complaint_db.find_one({"phone_number": number})

            if staff_data:
                    last_complaint = complaint_db.find_one({"phone_number": number}, sort=[("complaint_no", -1)])
                    last_complaint_no = last_complaint["complaint_no"] if last_complaint else "1000000"

                    # # Increment the last complaint number and generate the new complaint number
                    # new_complaint_no = str(int(last_complaint_no) + 1)

                    # Extract the number part from last_complaint_no and convert it to an integer
                    if last_complaint_no.startswith("S_"):
                        last_complaint_number = int(last_complaint_no.split("_")[1])
                    else:
                        last_complaint_number = int(last_complaint_no)

                    # If it's the first complaint, start with 10000001
                    if last_complaint_number < 1000001:
                        new_complaint_number = 1000001
                    else:
                        # Increment the complaint number
                        new_complaint_number = last_complaint_number + 1

                    # Construct the new complaint number with the "S_" prefix
                    new_complaint_no = f"S_{new_complaint_number}"

                    # Create the complaint data
                    complaint_data = {
                        "complaint_no": new_complaint_no,
                        "name": staff_data.get("name", ""),
                        "position": staff_data.get("position", ""),                         
                        "branch": staff_data.get("branch", ""),                       
                        "phone_number": staff_data.get("phone_number", ""),
                        "complaint": received_message
                    }
                    complaint_db.insert_one(complaint_data)

            # complaint_counter += 1
            complaint_mode[phone_number] = False
            send_message(phone_number, "complaint mode ended.")
    except Exception as e:
        print(e)
        print("Error in complaint mode")