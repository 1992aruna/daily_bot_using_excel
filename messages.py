import requests
import json
from final import API_URL, ACCESS_TOKEN
import os
import gridfs
from dotenv import load_dotenv
from pymongo import MongoClient
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pdfkit
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas



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

def send_pdf_message(contact_number,pdf, caption):
    url = f"{API_URL}/api/v1/sendSessionFile/{contact_number}?caption={caption}"

    payload = {}
    files=[
    ('file',('file',open(pdf,'rb'),'pdf/pdf'))
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


def upload_pdf(filename, fs):
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
                image_path = f'D:\\New Project\\Python\\Question&AnswerBot\\After Modification\\Latest\\daily_bot_using_excel\\branch_images\\{branch}{ext}'
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

def send_video_message(contact_number, video, caption):
    url = f"{API_URL}/api/v1/sendSessionFile/{contact_number}?caption={caption}"

    payload = {}
    files = [
        ('file', ('video.mp4', open(video, 'rb'), 'video/mp4'))
    ]
    headers = {
        'Authorization': ACCESS_TOKEN
    }

    response = requests.post(url, headers=headers, json=payload, files=files)
    print(response)
    print(response.json())
    
def send_videos(contact_number):
    dir="E:/NewProject/Python/Corprate App/Question&AnswerBot/After Modification/Latest/daily_bot_using_excel/video"
    video_path=f'{dir}/sample-5s.mp4'
    caption = "Check out this video!"
    # caption = "Check out this video! For more details visit our website.\n\n https://www.dexa.co.in/"
    send_video_message(contact_number, video_path, caption)

#---------------------------------- Audio -------------------------------------------------------------#
def send_audio_message(contact_number, audio, caption):
    url = f"{API_URL}/api/v1/sendSessionFile/{contact_number}?caption={caption}"

    # Prepare the payload and specify the file as 'audio/mpeg'
    payload = {}
    files = [
        ('file', ('audio.mp3', open(audio, 'rb'), 'audio/mpeg'))
    ]

    headers = {
        'Authorization': ACCESS_TOKEN
    }

    # Send the audio file using a POST request
    response = requests.post(url, headers=headers, json=payload, files=files)

    # Print the response and its JSON content
    print(response)
    print(response.json())
    
def send_audio(contact_number):
    dir = "E:/NewProject/Python/Corprate App/Question&AnswerBot/After Modification/Latest/daily_bot_using_excel/audio"  # Replace with the directory containing your audio file
    audio_path = f'{dir}/sound.mp3'  # Replace with the audio file name
    caption = "Check out this audio message!"
    send_audio_message(contact_number, audio_path, caption)

#-------------------------------------------- Pdf ----------------------------------------------------#

def send_pdf_message(contact_number, pdf_file, caption):
    url = f"{API_URL}/api/v1/sendSessionFile/{contact_number}?caption={caption}"

    # Prepare the payload and specify the file as 'application/pdf'
    payload = {}
    files = [
        ('file', ('file.pdf', open(pdf_file, 'rb'), 'application/pdf'))
    ]

    headers = {
        'Authorization': ACCESS_TOKEN
    }

    # Send the PDF file using a POST request
    response = requests.post(url, headers=headers, json=payload, files=files)

    # Print the response and its JSON content
    print(response)
    print(response.json())
    

def send_pdf(contact_number):
    dir = "E:/NewProject/Python/Corprate App/Question&AnswerBot/After Modification/Latest/daily_bot_using_excel/pdf"  # Replace with the directory containing your PDF file
    pdf_path = f'{dir}/MAJD_2.pdf'  # Replace with the PDF file name
    caption = "PDF File"

    # Ensure the PDF file exists
    if not os.path.isfile(pdf_path):
        print(f"PDF file '{pdf_path}' not found.")
        return

    # Call the function to send the PDF
    send_pdf_message(contact_number, pdf_path, caption)

#-------------------------------------------Mail----------------------------------------------------------#

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

#-----------------------------------------HTML FORM------------------------------------------------------#
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
    caption = "PDF File"

    # Ensure the PDF file exists
    if not os.path.isfile(pdf_output_path):
        print(f"PDF file '{pdf_output_path}' not found.")
        return

    # Call the function to send the PDF
    send_pdf_message(contact_number, pdf_output_path, caption)

# # Function to generate PDF from HTML content
# def html_to_pdf(html_content):
#     pdf = FPDF()
#     pdf.add_page()
#     pdf.set_font("Arial", size=12)
#     pdf.write_html(html_content)
#     pdf_output_path = "user_information.pdf"
#     pdf.output(pdf_output_path)
#     return pdf_output_path
