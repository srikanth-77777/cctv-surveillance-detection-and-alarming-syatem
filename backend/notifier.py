import smtplib
from email.message import EmailMessage
import os

# Configure your email credentials here for actual sending
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = os.getenv("SURVEILLANCE_EMAIL", "your_email@gmail.com")
SENDER_PASSWORD = os.getenv("SURVEILLANCE_PASSWORD", "your_app_password")

class Notifier:
    def __init__(self):
        self.enabled = False # Toggle via UI
        self.receiver_email = "recipient@example.com"
        
    def send_alert(self, object_class, confidence, image_path):
        if not self.enabled:
            return
            
        print(f"[NOTIFICATION] Triggering email alert for {object_class} (Confidence: {confidence:.2f}%)")
        msg = EmailMessage()
        msg['Subject'] = f"🚨 ALERT: {object_class.upper()} Detected!"
        msg['From'] = SENDER_EMAIL
        msg['To'] = self.receiver_email
        
        msg.set_content(f"The surveillance system detected a {object_class} with confidence {confidence:.2f}%.\n\nSee the attached snapshot.")

        # Attach image if it exists
        if os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                img_data = f.read()
            msg.add_attachment(img_data, maintype='image', subtype='jpeg', filename=os.path.basename(image_path))

        # IMPORTANT: To actually send emails, you need to uncomment the following block
        # and provide valid SENDER_EMAIL and SENDER_PASSWORD (like an App Password for Gmail).
        
        '''
        try:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.send_message(msg)
                print("[NOTIFICATION] Email sent successfully.")
        except Exception as e:
            print(f"[NOTIFICATION ERROR] Failed to send email: {e}")
        '''
        print("[NOTIFICATION] (Simulated) Email would be sent here. Configure SMTP to enable.")

notifier = Notifier()
