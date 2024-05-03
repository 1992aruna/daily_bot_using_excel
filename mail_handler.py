import pymongo
import os
import requests
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
# from messages import send_message

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
API_URL=os.getenv("API_URL")
ACCESS_TOKEN=os.getenv("ACCESS_TOKEN")
# Initialize MongoDB client
client = pymongo.MongoClient(MONGO_URI)

# Access the desired database
db = client["sbi"]
staff_db = db["staff"]
suggestion_db = db["suggestions"]  # Assuming "suggestions" is the name of the collection


mail_mode = {}

def send_email_with_attachment(to_email, subject, message, attachment_path):
    from_email = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_PASSWORD")

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(message, 'plain'))

    filename = os.path.basename(attachment_path)
    attachment = open(attachment_path, "rb")
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(attachment.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f"attachment; filename= {filename}")
    msg.attach(part)

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, app_password)  
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        server.quit()
        print("Email sent successfully.")
    except Exception as e:
        print(f"Error sending email: {str(e)}")

def send_document(email, branch):
    dir = "E:/NewProject/Python/Corprate App/Question&AnswerBot/After Modification/Latest/daily_bot_using_excel/documents"
    allowed_extensions = ["pdf", "docx"]
    document_path = None

    # Loop through the allowed extensions and find the first matching document
    for extension in allowed_extensions:
        possible_document_path = f"{dir}/{branch}.{extension}"
        if os.path.exists(possible_document_path):
            document_path = possible_document_path
            break

    if document_path:
        subject = f"Your document for {branch} branch"
        message = "Please find the attached document."
        send_email_with_attachment(email, subject, message, document_path)
    else:
        print(f"No matching document found for {branch}")

def send_message(contact_number, message):
	headers = {
					'Authorization': ACCESS_TOKEN,
				}
	payload={'messageText': message}

	url = f"{API_URL}/api/v1/sendSessionMessage/"+ f'{contact_number}'
	response = requests.post(url=url, headers=headers,data=payload)
	return response.status_code
# Define the function to handle mail-related tasks
def handle_mail(phone_number):
    mail_mode[phone_number] = True
    # if mail_mode.get(phone_number, False):
    staff_data = staff_db.find_one({"phone_number": phone_number})

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
