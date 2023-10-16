import requests
import json
from app import API_URL, ACCESS_TOKEN
import os
import gridfs
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
STAFF_COLLECTION = 'staff'
ANSWER_COLLECTION = 'answers_received'


API_URL=os.getenv("API_URL")
ACCESS_TOKEN=os.getenv("ACCESS_TOKEN")


def send_message(contact_number, message):
	headers = {
					'Authorization': ACCESS_TOKEN,
				}
	payload={'messageText': message}

	url = f"{API_URL}/api/v1/sendSessionMessage/"+ f'{contact_number}'
	response = requests.post(url=url, headers=headers,data=payload)
	return response.status_code

def send_image_message(contact_number,image, caption):
    url = f"{API_URL}/api/v1/sendSessionFile/{contact_number}?caption={caption}"

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


##-------------------------------- Customized image message sending -----------------------------------------------------------------------------   ##

def send_images(contact_number,option):
    dir="C:/Users/jmdee/upwork/Design Chatbot/images"
    if option =="Shirt":
        image1=f'{dir}/s_image1.png'
        image2=f'{dir}/s_image2.png'
        

    else:
        image1=f'{dir}/ts_image1.jpg'
        image2=f'{dir}/ts_image2.jpg'
       
        
    send_image_message(contact_number,image1, "Image1")
    send_image_message(contact_number,image2, "Image2")

## ------------------------------------- --------------------------------------------------------------------------------------------------------##         
        

    

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


def get_media(filename):
    url = f"{API_URL}/api/v1/getMedia"

    payload = {'fileName': filename}
    
    headers = {
    'Authorization': ACCESS_TOKEN
    }

    response = requests.get(url, headers=headers, data=payload)
    return response

#----------------------------------------------------------- Image uploading on server -------------------------------------------------------#
def upload_image(filename, fs):
    response= get_media(filename)
    if response.status_code==200:
        file=fs.put(response.content, filename=filename)
        #print(file)
        print("Upload Complete")
        return file
    
    return False

# ----------------------------------------------------------------------------------------------------------------------------------- #    

def send_branch_images():
    try:
        # Connect to MongoDB
        client = MongoClient(MONGO_URI)
        db = client[MONGO_DB]
        staff_collection = db[STAFF_COLLECTION]

        # Iterate over the orders
        for staffbranch in staff_collection.find():
            branch = staffbranch['branch']
            phone_number = staffbranch['phone_no']
            
            # Check if the status is 'not sent'
            # if status == '':
                # Check if an image exists for this branch with either .png or .jpg extension
            image_extensions = ['.png', '.jpg']
            image_found = False

            for ext in image_extensions:
                image_path = f'D:\\New Project\\Python\\New_Bot\\Bot\\design_bot\\branch_images\\{branch}{ext}'
                
                
                if os.path.isfile(image_path):
                    image_found = True
                    # Provide a caption for the image message
                    caption = f'Here is your branch image {branch}'
                    #caption = 'Here is your image for order ID {branch}'
                    
                    # Send the image via Wati using a message with an image attachment
                    send_image_message(phone_number, image_path, caption)

                    print(f"Image sent for branch {branch} with extension {ext}")

            if not image_found:
                print(f"No image found for your branch {branch}")

            # else:
            #     print(f"Order ID {branch} already marked as 'sent'")

    except Exception as e:
        print(f"An error occurred: {str(e)}")

#----------------------------------------Export to Excel----------------------------------------------------#

# def retrieve_user_answers():
#     client = MongoClient(MONGO_URI)
#     db = client[MONGO_DB]
#     answer_collection = db[ANSWER_COLLECTION]
#     user_answers = list(answer_collection.find())
#     return user_answers

# # --------------------------------------------SEND EXCEL------------------------------------------------------#
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

#--------------------------------------SEND EXCEL TO RECIPIENT------------------------------------------------#

