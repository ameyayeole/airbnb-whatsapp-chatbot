import os
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.environ["WHATSAPP_TOKEN"]
PHONE_NUMBER_ID = os.environ["PHONE_NUMBER_ID"]
VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
TRANSPORT_CONTACT = os.getenv("TRANSPORT_CONTACT", "Contact transport agency directly.")
PORT = int(os.getenv("PORT", 5000))
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")
