from flask import request
import os
import requests
import pymongo
import pdfkit
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

MONGO_URI = os.getenv("MONGO_URI")
API_URL=os.getenv("API_URL")
ACCESS_TOKEN=os.getenv("ACCESS_TOKEN")
# Initialize MongoDB client
client = pymongo.MongoClient(MONGO_URI)

# Access the desired database
db = client["sbi"]
form_db = db["form_data"]

form_mode = {}
form_data = {}

def send_message(contact_number, message):
	headers = {
					'Authorization': ACCESS_TOKEN,
				}
	payload={'messageText': message}

	url = f"{API_URL}/api/v1/sendSessionMessage/"+ f'{contact_number}'
	response = requests.post(url=url, headers=headers,data=payload)
	return response.status_code

def send_pdf_message(contact_number, pdf, caption):
    url = f"{API_URL}/api/v1/sendSessionFile/{contact_number}?caption={caption}"

    payload = {}
    files = [('file', ('file', open(pdf, 'rb'), 'application/pdf'))]  # Corrected media type here

    headers = {
        'Authorization': ACCESS_TOKEN
    }

    response = requests.post(url, headers=headers, json=payload, files=files)
    print(response)
    print(response.json())


pdf_counts = {}

def create_pdf(data, phone_number, output_dir='Form_Output'):
    # If the phone number is not in the dictionary, add it
    if phone_number not in pdf_counts:
        pdf_counts[phone_number] = 1
    else:
        # If the phone number is already in the dictionary, increment the count
        pdf_counts[phone_number] += 1

    # Create the output path using the phone number and the count
    output_path = f'{output_dir}/{phone_number}_{pdf_counts[phone_number]}.pdf'
    html_content = f"""
    <html>
    <body>
    <h2>User Information</h2>
    <p><strong>Name:</strong> {data['name']}</p>
    <p><strong>Age:</strong> {data['age']}</p>
    <p><strong>Qualification:</strong> {data['qualification']}</p>
    </body>
    </html>
    """

    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica", 24)
    c.drawString(30, height - 50, "User Information")

    c.setFont("Helvetica", 16)
    c.drawString(30, height - 100, f"Name: {data['name']}")
    c.drawString(30, height - 130, f"Age: {data['age']}")
    c.drawString(30, height - 160, f"Qualification: {data['qualification']}")

    c.save()

    return output_path
def send_form_pdf(contact_number, pdf_output_path):
    dir = pdf_output_path# Replace with the PDF file name
    caption = "Please find out your form"

    # Ensure the PDF file exists
    if not os.path.isfile(pdf_output_path):
        print(f"PDF file '{pdf_output_path}' not found.")
        return

    # Call the function to send the PDF
    send_pdf_message(contact_number, pdf_output_path, caption)

def start_form_mode(phone_number):
    form_mode[phone_number] = True
    form_data[phone_number] = {}
    send_message(phone_number, "Please enter your name:")

def process_form_submission(phone_number):
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
