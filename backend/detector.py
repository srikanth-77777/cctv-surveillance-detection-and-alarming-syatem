import cv2
import numpy as np
import os
from time import time
from backend.database import SessionLocal, AlertLog
from backend.notifier import notifier

CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat",
           "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
           "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
           "sofa", "train", "tvmonitor"]

COLORS = np.random.uniform(0, 255, size=(len(CLASSES), 3))

PROTOTXT = os.path.join(os.path.dirname(__file__), "..", "MobileNetSSD_deploy.prototxt")
MODEL = os.path.join(os.path.dirname(__file__), "..", "MobileNetSSD_deploy.caffemodel")

# Temporary folder for frontend to serve images from
ALERT_FOLDER = os.path.join(os.path.dirname(__file__), "..", "alerts")
os.makedirs(ALERT_FOLDER, exist_ok=True)

class ObjectDetector:
    def __init__(self, video_source, source_name="Live Feed"):
        self.net = cv2.dnn.readNetFromCaffe(PROTOTXT, MODEL)
        self.video_source = video_source
        self.source_name = source_name
        self.cap = cv2.VideoCapture(self.video_source)
        
        # Configuration
        self.target_objects = ["person", "car"] # Default tracking
        self.confidence_threshold = 0.5
        self.cooldown_period = 5 # seconds between saving alerts for the SAME object
        self.last_alert_time = {}
        
    def set_config(self, targets, threshold, email_enabled):
        self.target_objects = targets
        self.confidence_threshold = threshold
        notifier.enabled = email_enabled
        
    def generate_frames(self):
        # Allow automatic reconnection if video ends
        if not self.cap.isOpened():
             self.cap = cv2.VideoCapture(self.video_source)
             
        while True:
            if not self.cap or not self.cap.isOpened():
                break

            try:
                ret, frame = self.cap.read()
            except cv2.error as e:
                print(f"[STREAM] OpenCV read error, reconnecting: {e}")
                try:
                    self.cap.release()
                    self.cap = cv2.VideoCapture(self.video_source)
                    ret, frame = self.cap.read()
                except Exception:
                    break
            except Exception as e:
                print(f"[STREAM] Unexpected read error: {e}")
                break

            if not ret or frame is None:
                # Video file reached the end — loop it seamlessly
                try:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = self.cap.read()
                    if not ret or frame is None:
                        self.cap.release()
                        self.cap = cv2.VideoCapture(self.video_source)
                        ret, frame = self.cap.read()
                        if not ret or frame is None:
                            break
                except Exception as e:
                    print(f"[STREAM] Error resetting loop: {e}")
                    break


            (h, w) = frame.shape[:2]
            blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)),
                                         0.007843, (300, 300), 127.5)

            self.net.setInput(blob)
            detections = self.net.forward()

            detected_this_frame = False

            for i in np.arange(0, detections.shape[2]):
                confidence = detections[0, 0, i, 2]

                if confidence > self.confidence_threshold:
                    idx = int(detections[0, 0, i, 1])
                    object_class = CLASSES[idx]
                    
                    # FILTER: Check if the detected object is in our target list
                    if object_class in self.target_objects:
                        detected_this_frame = True
                        box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                        (startX, startY, endX, endY) = box.astype("int")

                        # Draw bounding box
                        label = f"{object_class}: {confidence * 100:.2f}%"
                        cv2.rectangle(frame, (startX, startY), (endX, endY), COLORS[idx], 2)
                        y = startY - 15 if startY - 15 > 15 else startY + 15
                        cv2.putText(frame, label, (startX, y),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLORS[idx], 2)
                                    
                        # Handle alerts
                        current_time = time()
                        last_time = self.last_alert_time.get(object_class, 0)
                        
                        if current_time - last_time > self.cooldown_period:
                            self.last_alert_time[object_class] = current_time
                            self._trigger_alert(frame, object_class, confidence * 100)
                            
            # Visual Alert flash on frame
            if detected_this_frame:
                cv2.rectangle(frame, (10, 10), (300, 60), (0, 0, 255), -1)
                cv2.putText(frame, "ALERT: OBJECT DETECTED", (20, 45),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            # Encode frame for HTTP streaming
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                   
    def _trigger_alert(self, frame, obj_class, conf):
        timestamp_str = str(int(time()))
        filename = f"alert_{obj_class}_{timestamp_str}.jpg"
        filepath = os.path.join(ALERT_FOLDER, filename)
        
        # Save image
        cv2.imwrite(filepath, frame)
        print(f"[ALERT] Recorded Alert: {obj_class} at {filepath}")
        
        # Trigger Email
        notifier.send_alert(obj_class, conf, filepath)
        
        # Save to DB
        db = SessionLocal()
        try:
            log_entry = AlertLog(
                object_class=obj_class,
                confidence=conf,
                image_path=filename,
                source_video=self.source_name
            )
            db.add(log_entry)
            db.commit()
        except Exception as e:
            print("DB Error:", e)
        finally:
            db.close()
            
    def release(self):
        if self.cap:
             self.cap.release()
