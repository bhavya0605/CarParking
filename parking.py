import tkinter as tk
from tkinter import messagebox
import sqlite3
import requests
import cv2 # OpenCV for camera
import datetime
import os
import io
from dotenv import load_dotenv
API_TOKEN = os.getenv('API_KEY')
# --- Configuration ---
# IMPORTANT: Replace with your actual token
DB_FILE = 'parking_system.db'
TOTAL_SLOTS = 5
COST_PER_SECOND = 0.05 # For demo purposes

# ==============================================================================
# 1. DATABASE SETUP AND MANAGEMENT
# ==============================================================================

def setup_database():
    """Creates the database and tables if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Vehicles Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Vehicles (
            VehicleID INTEGER PRIMARY KEY AUTOINCREMENT,
            PlateNumber TEXT UNIQUE NOT NULL
        )
    ''')
    
    # ParkingSlots Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ParkingSlots (
            SlotID INTEGER PRIMARY KEY AUTOINCREMENT,
            Status TEXT NOT NULL DEFAULT 'Available' CHECK(Status IN ('Available', 'Occupied'))
        )
    ''')
    
    # ParkingSessions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ParkingSessions (
            SessionID INTEGER PRIMARY KEY AUTOINCREMENT,
            VehicleID INTEGER NOT NULL,
            SlotID INTEGER NOT NULL,
            EntryTime TEXT NOT NULL,
            ExitTime TEXT,
            Status TEXT NOT NULL DEFAULT 'Active' CHECK(Status IN ('Active', 'Completed')),
            Fee REAL,
            FOREIGN KEY (VehicleID) REFERENCES Vehicles(VehicleID),
            FOREIGN KEY (SlotID) REFERENCES ParkingSlots(SlotID)
        )
    ''')
    
    # Populate slots if the table is empty
    cursor.execute('SELECT COUNT(*) FROM ParkingSlots')
    if cursor.fetchone()[0] == 0:
        for _ in range(TOTAL_SLOTS):
            cursor.execute("INSERT INTO ParkingSlots (Status) VALUES ('Available')")

    conn.commit()
    conn.close()

# Database helper functions
def execute_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    """A generic function to handle database operations."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(query, params)
    
    result = None
    if commit:
        conn.commit()
        result = cursor.lastrowid
    elif fetchone:
        result = cursor.fetchone()
    elif fetchall:
        result = cursor.fetchall()
        
    conn.close()
    return result

# ==============================================================================
# 2. CORE LOGIC (PLATE RECOGNITION, PARKING MANAGEMENT)
# ==============================================================================

def capture_and_recognize_plate():
    """Captures an image from the webcam and calls the Plate Recognizer API."""
    # 1. Capture image
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        messagebox.showerror("Error", "Could not open webcam.")
        return None
    
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        messagebox.showerror("Error", "Failed to capture image.")
        return None
        
    image_path = "capture.jpg"
    cv2.imwrite(image_path, frame)
    
    # 2. Recognize plate
    api_url = 'https://api.platerecognizer.com/v1/plate-reader/'
    try:
        with open(image_path, 'rb') as fp:
            response = requests.post(
                api_url,
                files={'upload': fp},
                headers={'Authorization': f'Token {API_TOKEN}'}
            )
        response.raise_for_status()
        data = response.json()
        
        if data.get('results') and len(data['results']) > 0:
            plate = data['results'][0]['plate']
            return plate.upper()
        else:
            messagebox.showinfo("Info", "No plate found in the captured image.")
            return None
    except requests.exceptions.RequestException as e:
        messagebox.showerror("API Error", f"Failed to call API: {e}")
        return None
    finally:
        if os.path.exists(image_path):
            os.remove(image_path)

# ==============================================================================
# 3. GUI APPLICATION
# ==============================================================================

class ParkingSystemApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Automated Parking System")
        self.geometry("800x600")

        self.slot_frames = {}
        self.slot_labels = {}

        # Main layout
        control_frame = tk.Frame(self, bd=2, relief=tk.SUNKEN)
        control_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)

        dashboard_frame = tk.Frame(self)
        dashboard_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Control buttons
        tk.Label(control_frame, text="Controls", font=("Helvetica", 16)).pack(pady=10)
        tk.Button(control_frame, text="Vehicle at Entrance", command=self.handle_entry, width=20, height=2).pack(pady=10)
        tk.Button(control_frame, text="Vehicle at Exit", command=self.handle_exit, width=20, height=2).pack(pady=10)
        
        # Dashboard slots
        tk.Label(dashboard_frame, text="Parking Dashboard", font=("Helvetica", 16)).pack(pady=10)
        slots_container = tk.Frame(dashboard_frame)
        slots_container.pack(fill=tk.BOTH, expand=True)

        for i in range(TOTAL_SLOTS):
            slot_id = i + 1
            frame = tk.Frame(slots_container, borderwidth=2, relief="solid", width=150, height=100)
            frame.grid(row=i // 3, column=i % 3, padx=15, pady=15)
            frame.pack_propagate(False)
            
            label = tk.Label(frame, text=f"Slot {slot_id}\nAvailable", font=("Helvetica", 12))
            label.pack(expand=True)
            
            self.slot_frames[slot_id] = frame
            self.slot_labels[slot_id] = label
            
        self.update_dashboard()

    def update_dashboard(self):
        """Fetches slot statuses from DB and updates the GUI colors."""
        statuses = execute_query("SELECT SlotID, Status FROM ParkingSlots", fetchall=True)
        for slot_id, status in statuses:
            if status == 'Occupied':
                self.slot_frames[slot_id].config(bg='salmon')
                self.slot_labels[slot_id].config(text=f"Slot {slot_id}\nOccupied", bg='salmon')
            else:
                self.slot_frames[slot_id].config(bg='lightgreen')
                self.slot_labels[slot_id].config(text=f"Slot {slot_id}\nAvailable", bg='lightgreen')

    def handle_entry(self):
        """Manages the entire vehicle entry process."""
        plate_number = capture_and_recognize_plate()
        if not plate_number:
            return

        # Check if car is already parked
        active_session = execute_query(
            """SELECT s.SessionID FROM ParkingSessions s
               JOIN Vehicles v ON s.VehicleID = v.VehicleID
               WHERE v.PlateNumber = ? AND s.Status = 'Active'""",
            (plate_number,), fetchone=True
        )
        if active_session:
            messagebox.showwarning("Warning", f"Vehicle {plate_number} is already parked.")
            return

        # Find an available slot
        available_slot = execute_query("SELECT SlotID FROM ParkingSlots WHERE Status = 'Available' LIMIT 1", fetchone=True)
        if not available_slot:
            messagebox.showinfo("Info", "Sorry, the parking lot is full.")
            return
        
        slot_id = available_slot[0]
        
        # Add vehicle if not exists, get ID
        vehicle = execute_query("SELECT VehicleID FROM Vehicles WHERE PlateNumber = ?", (plate_number,), fetchone=True)
        if vehicle:
            vehicle_id = vehicle[0]
        else:
            vehicle_id = execute_query("INSERT INTO Vehicles (PlateNumber) VALUES (?)", (plate_number,), commit=True)

        # Start a new session
        entry_time = datetime.datetime.now().isoformat()
        session_id = execute_query(
            "INSERT INTO ParkingSessions (VehicleID, SlotID, EntryTime) VALUES (?, ?, ?)",
            (vehicle_id, slot_id, entry_time), commit=True
        )
        
        # Update slot status
        execute_query("UPDATE ParkingSlots SET Status = 'Occupied' WHERE SlotID = ?", (slot_id,), commit=True)
        
        messagebox.showinfo("Success", f"Welcome, {plate_number}! Please proceed to Slot {slot_id}.")
        self.update_dashboard()

    def handle_exit(self):
        """Manages vehicle exit, calculates fee, and simulates payment."""
        plate_number = capture_and_recognize_plate()
        if not plate_number:
            return

        # Find active session for this vehicle
        session_data = execute_query(
            """SELECT s.SessionID, s.EntryTime, s.SlotID FROM ParkingSessions s
               JOIN Vehicles v ON s.VehicleID = v.VehicleID
               WHERE v.PlateNumber = ? AND s.Status = 'Active'""",
            (plate_number,), fetchone=True
        )

        if not session_data:
            messagebox.showerror("Error", f"No active session found for vehicle {plate_number}.")
            return

        session_id, entry_time_str, slot_id = session_data
        entry_time = datetime.datetime.fromisoformat(entry_time_str)
        exit_time = datetime.datetime.now()
        
        # Calculate duration for display and fee
        duration = exit_time - entry_time
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_str = f"{hours}h {minutes}m {seconds}s"

        fee = round(duration.total_seconds() * COST_PER_SECOND, 2)

        # Show fee and ask for payment confirmation
        payment_confirmed = messagebox.askyesno(
            "Payment Due",
            f"Vehicle: {plate_number}\n"
            f"Duration: {duration_str}\n\n"
            f"Amount Due: ${fee:.2f}\n\n"
            "Confirm payment to complete exit?"
        )

        # If user clicks 'Yes', simulate payment and update DB
        if payment_confirmed:
            exit_time_iso = exit_time.isoformat()
            execute_query(
                "UPDATE ParkingSessions SET ExitTime = ?, Status = 'Completed', Fee = ? WHERE SessionID = ?",
                (exit_time_iso, fee, session_id), commit=True
            )
            execute_query("UPDATE ParkingSlots SET Status = 'Available' WHERE SlotID = ?", (slot_id,), commit=True)
            
            messagebox.showinfo("Success", "Payment confirmed! Slot is now available.")
            self.update_dashboard()
        else:
            messagebox.showinfo("Info", "Payment cancelled. Vehicle remains in the parking lot.")


if __name__ == "__main__":
    setup_database()
    app = ParkingSystemApp()
    app.mainloop()

