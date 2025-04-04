from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
from dotenv import load_dotenv
import secrets
import sqlite3
import os
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta



load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")



ADMIN_SECRET_KEY = os.getenv('ADMIN_SECRET_KEY')
TRAINER_SECRET_KEY = os.getenv('TRAINER_SECRET_KEY')

DATABASE = 'videomeet.db'

# -------------------- DATABASE SETUP --------------------

def get_db_cursor():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn, conn.cursor()

def initialize_db():
    try:
        conn, cursor = get_db_cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id TEXT UNIQUE NOT NULL,
                meeting_name TEXT NOT NULL,
                meeting_date TEXT NOT NULL,
                meeting_time TEXT NOT NULL,
                meeting_duration TEXT NOT NULL,
                meeting_description TEXT,
                email TEXT NOT NULL,
                status TEXT DEFAULT 'scheduled'
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                reset_token TEXT NOT NULL,
                expires_at DATETIME NOT NULL
            )
        ''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database initialization error: {e}")
    finally:
        conn.close()
initialize_db()

# -------------------- ROLE-BASED ACCESS DECORATOR --------------------

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session or session['role'] not in allowed_roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# -------------------- ROUTES --------------------

@app.route('/')
def home():
    return render_template('home.html')

# -------------------- USER DASHBOARD --------------------

@app.route('/user_dashboard')
def user_dashboard():
    if 'user' in session:
        return render_template('user_dashboard.html', user=session['user_name'])
    else:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

# -------------------- CREATE MEETING --------------------
# filepath: c:\Users\Dell\OneDrive\Desktop\virtualmeet\app.py
@app.route('/join_meeting', methods=['POST'])
def join_meeting():
    meeting_id = request.form.get('meeting_id', '').strip()
    print(f"Received Meeting ID: {meeting_id}")  # Debugging log

    # Extract meeting_id if it's a full URL
    if "http" in meeting_id:
        meeting_id = meeting_id.split("/")[-1]  # Extract the last part of the URL
        print(f"Extracted Meeting ID: {meeting_id}")  # Debugging log

    if not meeting_id:
        flash('Meeting ID or link is required.', 'danger')
        return redirect(url_for('user_dashboard'))

    conn, cursor = get_db_cursor()
    try:
        cursor.execute("SELECT * FROM meetings WHERE meeting_id = ?", (meeting_id,))
        meeting = cursor.fetchone()
        print(f"Query Result: {meeting}")  # Debugging log

        if meeting:
            print(f"Meeting Found: {meeting['meeting_name']}")  # Debugging log
            return redirect(url_for('meeting_room', meeting_id=meeting_id))
        else:
            print("Meeting not found.")  # Debugging log
            flash('Meeting not found. Please check the Meeting ID or link.', 'danger')
    except sqlite3.Error as e:
        print(f"Database error: {e}")  # Debugging log
        flash('An error occurred while accessing the database.', 'danger')
    finally:
        conn.close()

    return redirect(url_for('user_dashboard'))
@app.route('/create_meeting', methods=['GET', 'POST'])
@role_required(['admin', 'trainer'])
def create_meeting():
    if request.method == 'POST':
        meeting_name = request.form.get('meeting_name', '').strip()
        meeting_date = request.form.get('meeting_date', '').strip()
        meeting_time = request.form.get('meeting_time', '').strip()
        meeting_duration = request.form.get('meeting_duration', '').strip()
        meeting_description = request.form.get('meeting_description', '').strip()

        # Validate inputs
        if not all([meeting_name, meeting_date, meeting_time, meeting_duration]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('trainer_dashboard'))

        try:
            meeting_datetime = datetime.strptime(f"{meeting_date} {meeting_time}", '%Y-%m-%d %H:%M')
            if meeting_datetime < datetime.now():
                flash('Meeting date and time cannot be in the past.', 'danger')
                return redirect(url_for('trainer_dashboard'))
        except ValueError:
            flash('Invalid date or time format.', 'danger')
            return redirect(url_for('trainer_dashboard'))

        meeting_id = secrets.token_hex(8)
        email = session.get('user')

        conn, cursor = get_db_cursor()
        try:
            cursor.execute(
                '''INSERT INTO meetings (meeting_id, meeting_name, meeting_date, meeting_time, meeting_duration, meeting_description, email)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (meeting_id, meeting_name, meeting_date, meeting_time, meeting_duration, meeting_description, email)
            )
            conn.commit()
            flash('Meeting created successfully!', 'success')
        except sqlite3.Error as e:
            flash(f"Database error: {e}", 'danger')
            conn.rollback()
        finally:
            conn.close()

        return redirect(url_for('trainer_dashboard'))

    return render_template('create_meeting.html')
@app.route('/delete_meeting/<meeting_id>', methods=['DELETE'])
@role_required(['admin', 'trainer'])
def delete_meeting(meeting_id):
    user_role = session.get('role')  # Get the role of the logged-in user
    user_email = session.get('user')  # Get the email of the logged-in user

    conn, cursor = get_db_cursor()
    try:
        if user_role == 'trainer':
            cursor.execute("SELECT * FROM meetings WHERE meeting_id = ? AND email = ?", (meeting_id, user_email))
            meeting = cursor.fetchone()
            if not meeting:
                return jsonify({'error': 'Unauthorized: Trainers can only delete their own meetings.'}), 401

        cursor.execute("DELETE FROM meetings WHERE meeting_id = ?", (meeting_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({'error': 'Meeting not found'}), 404
        return '', 204  # No Content
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({'error': 'Database error'}), 500
    finally:
        conn.close()
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', '').strip()

        if not all([name, email, password, role]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('home'))

        conn, cursor = get_db_cursor()
        try:
            cursor.execute(
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                (name, email, password, role)
            )
            conn.commit()
            flash('Signup successful! You can now log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists.', 'danger')
        finally:
            conn.close()

    return render_template('home.html')
@app.route('/start_meeting/<meeting_id>')
def start_meeting(meeting_id):
    meeting_link = url_for('meeting_room', meeting_id=meeting_id, _external=True)
    flash(f'Meeting started! Share this link: {meeting_link}', 'success')
    return redirect(url_for('meeting_room', meeting_id=meeting_id))
@app.route('/meeting_room/<meeting_id>')
def meeting_room(meeting_id):
    if 'user' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    email = session.get('user')  # Assuming the user's email is stored in the session
    conn, cursor = get_db_cursor()
    try:
        # Fetch the username from the database
        cursor.execute("SELECT name FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('login'))
        username = user['name']
    finally:
        conn.close()

    return render_template('meeting_room.html', meeting_id=meeting_id, username=username)
@socketio.on('chat_message')
def handle_chat(data):
    room = data.get('room')
    if room:
        print(f"Broadcasting message to room {room}: {data}")
        emit('chat_message', data, room=room)  # Broadcast to the correct room
    else:
        print("Error: No room specified. Message not broadcasted.")

@socketio.on('join_room')
def handle_join(data):
    room = data.get('room')
    username = data.get('username', 'Anonymous')
    if room:
        join_room(room)
        print(f"{username} joined room: {room}")


participants = {}  # Store participants for each room

@socketio.on('join')
def handle_join(data):
    room = data['room']
    username = data['username']
    role = data.get('role', 'user')  # Default to 'user' if role is not provided
    join_room(room)
    if room not in participants:
        participants[room] = []
    participants[room].append({'username': username, 'role': role})
    emit('participant_joined', {'username': username, 'role': role, 'participants': participants[room]}, room=room)
@socketio.on('leave')
def handle_leave(data):
    room = data['room']
    username = data['username']
    leave_room(room)
    if room in participants:
        participants[room] = [p for p in participants[room] if p['username'] != username]
    emit('participant_left', {'username': username, 'participants': participants[room]}, room=room)



@app.route('/admin_dashboard')
@role_required(['admin'])
def admin_dashboard():
    if 'user' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    conn, cursor = get_db_cursor()
    try:
        cursor.execute("SELECT * FROM meetings")
        meetings = cursor.fetchall()
    finally:
        conn.close()

    return render_template('admin_dashboard.html', meetings=meetings)

# -------------------- TRAINER DASHBOARD --------------------

@app.route('/trainer_dashboard')
@role_required(['admin', 'trainer'])
def trainer_dashboard():
    email = session.get('user')
    if not email:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    conn, cursor = get_db_cursor()
    try:
        cursor.execute("SELECT * FROM meetings WHERE email = ?", (email,))
        meetings = cursor.fetchall()
    finally:
        conn.close()

    return render_template('trainer_dashboard.html', meetings=meetings)
@app.route('/reset_password/<reset_token>', methods=['GET', 'POST'])
def reset_password(reset_token):
    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        print(f"New Password: {new_password}, Confirm Password: {confirm_password}")  # Debugging log

        if not new_password or not confirm_password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('reset_password', reset_token=reset_token))

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('reset_password', reset_token=reset_token))

        conn, cursor = get_db_cursor()
        try:
            # Verify the reset token
            cursor.execute(
                "SELECT * FROM password_resets WHERE reset_token = ? AND expires_at > ?",
                (reset_token, datetime.now())
            )
            reset_entry = cursor.fetchone()
            print(f"Reset Entry: {reset_entry}")  # Debugging log

            if not reset_entry:
                flash('Invalid or expired reset token.', 'danger')
                return redirect(url_for('reset_password_request'))

            # Update the password in the users table
            cursor.execute(
                "UPDATE users SET password = ? WHERE email = ?",
                (new_password, reset_entry['email'])
            )
            print(f"Password updated for email: {reset_entry['email']}")  # Debugging log

            # Delete the reset token
            cursor.execute("DELETE FROM password_resets WHERE reset_token = ?", (reset_token,))
            conn.commit()

            flash('Password reset successfully! You can now log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.Error as e:
            print(f"Database error: {e}")  # Debugging log
            flash('An error occurred while resetting your password.', 'danger')
        finally:
            conn.close()

    return render_template('reset_password.html', reset_token=reset_token)
@app.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()

        if not email:
            flash('Email is required.', 'danger')
            return redirect(url_for('reset_password_request'))

        conn, cursor = get_db_cursor()
        try:
            # Check if the email exists in the database
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()
            if not user:
                flash('Email not found.', 'danger')
                return redirect(url_for('reset_password_request'))

            # Generate a unique reset token
            reset_token = secrets.token_hex(16)
            expires_at = datetime.now() + timedelta(hours=1)  # Token expires in 1 hour

            # Save the token in the password_resets table
            cursor.execute(
                "INSERT INTO password_resets (email, reset_token, expires_at) VALUES (?, ?, ?)",
                (email, reset_token, expires_at)
            )
            conn.commit()

            # Send the reset link to the user's email
            reset_link = f"{request.url_root}reset_password/{reset_token}"
            subject = "Password Reset Request"
            body = f"""
            Hi {user['name']},

            You requested to reset your password. Click the link below to reset it:

            {reset_link}

            This link will expire in 1 hour.

            If you did not request this, please ignore this email.

            Thanks,
            VirtualMeet Team
            """

            # SMTP Configuration
            sender_email = "20211460@sbsstc.ac.in"
            sender_password = "afvg zbgz anhe zdaa"
            smtp_server = "smtp.gmail.com"
            smtp_port = 587

            # Create the email
            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            # Send the email
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, email, msg.as_string())

            flash('A reset link has been sent to your email.', 'success')
            return redirect(url_for('login'))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            flash('An error occurred while processing your request.', 'danger')
        except smtplib.SMTPException as e:
            print(f"SMTP error: {e}")
            flash('An error occurred while sending the email.', 'danger')
        finally:
            conn.close()

    return render_template('reset_password_req.html')# -------------------- LOGIN --------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash('Email and password are required.', 'danger')
            return redirect(url_for('login'))

        conn, cursor = get_db_cursor()
        try:
            cursor.execute("SELECT * FROM users WHERE email = ? AND password = ?", (email, password))
            user = cursor.fetchone()
            if user:
                session['user'] = user['email']
                session['user_name'] = user['name']
                session['role'] = user['role']

                if user['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                elif user['role'] == 'trainer':
                    return redirect(url_for('trainer_dashboard'))
                else:
                    return redirect(url_for('user_dashboard'))
            else:
                flash('Invalid email or password.', 'danger')
        finally:
            conn.close()

    return render_template('home.html')

# -------------------- LOGOUT --------------------

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

# -------------------- SOCKET.IO --------------------


# -------------------- RUN APP --------------------

if __name__ == '__main__':
    socketio.run(app, debug=True)





