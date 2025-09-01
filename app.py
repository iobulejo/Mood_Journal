import os, json, decimal
from datetime import datetime, date
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2
import requests
import bcrypt
import jwt
from datetime import datetime, timedelta
import urllib.parse

load_dotenv()

HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
HF_HEADERS = {"Authorization": f"Bearer {HF_API_TOKEN}"} if HF_API_TOKEN else {}
EMOTION_MODEL = os.getenv("EMOTION_MODEL", "j-hartmann/emotion-english-distilroberta-base")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")

app = Flask(__name__, static_folder='static', template_folder='.')
CORS(app)

# Use a single DATABASE_URL variable for production environments
DATABASE_URL = os.getenv("DATABASE_URL")

DB_CFG = {}
if DATABASE_URL:
    url_parts = urllib.parse.urlparse(DATABASE_URL)
    DB_CFG = dict(
        host=url_parts.hostname,
        user=url_parts.username,
        password=url_parts.password,
        dbname=url_parts.path[1:],
        port=url_parts.port if url_parts.port else 5432
    )
else:
    DB_CFG = dict(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "mood_journal_db"),
    )

# Subscription plans configuration
SUBSCRIPTION_PLANS = {
    "free": {
        "name": "Free",
        "monthly_price": 0,
        "max_entries": 5,
        "history_days": 7,
        "features": ["Basic emotion analysis", "7-day history"],
        "limitations": ["No advanced analytics", "No export功能"]
    },
    "premium": {
        "name": "Premium",
        "monthly_price": 9.99,
        "max_entries": float('inf'),
        "history_days": 30,
        "features": ["Unlimited entries", "Advanced analytics", "30-day history"],
        "limitations": []
    },
    "enterprise": {
        "name": "Enterprise",
        "monthly_price": 29.99,
        "max_entries": float('inf'),
        "history_days": float('inf'),
        "features": ["Unlimited entries", "Full history", "Team features", "API access"],
        "limitations": []
    }
}

# Helper function to connect to the database
def connect_db():
    try:
        return psycopg2.connect(**DB_CFG)
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

# Helper function to get user from request token
def get_user_from_request():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None
    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get('user')
    except jwt.ExpiredSignatureError:
        return None
    except (jwt.InvalidTokenError, IndexError) as e:
        print(f"Token error: {e}")
        return None

# Helper function to get AI emotions
def get_ai_emotions(text):
    if not HF_API_TOKEN:
        return None, 0
    
    try:
        response = requests.post(
            f"https://api-inference.huggingface.co/models/{EMOTION_MODEL}",
            headers=HF_HEADERS,
            json={"inputs": text}
        )
        response.raise_for_status()
        result = response.json()
        
        if result and len(result) > 0 and isinstance(result[0], list) and len(result[0]) > 0:
            emotions = result[0]
            emotions.sort(key=lambda x: x['score'], reverse=True)
            top_emotion = emotions[0]
            
            # Simple score conversion (e.g., to a 1-10 scale)
            # score = round(top_emotion['score'] * 10, 2)
            score = top_emotion['score']
            return top_emotion['label'], score
    except requests.exceptions.RequestException as e:
        print(f"Hugging Face API error: {e}")
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Error processing AI response: {e}")
    
    return None, 0

# Helper function to get a user's subscription tier
def get_user_subscription(user_id, conn):
    cur = conn.cursor()
    cur.execute("SELECT subscription_tier FROM users WHERE id = %s", (user_id,))
    tier = cur.fetchone()
    return tier[0] if tier else "free"

# Helper function to check entry limit
def check_entry_limit(user_id, conn):
    tier = get_user_subscription(user_id, conn)
    max_entries = SUBSCRIPTION_PLANS[tier]['max_entries']
    
    if max_entries == float('inf'):
        return True, "No limit"
        
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM entries WHERE user_id = %s", (user_id,))
    current_entries = cur.fetchone()[0]
    
    if current_entries >= max_entries:
        return False, f"You have reached the limit of {max_entries} entries for your '{tier}' plan."
    
    return True, "Limit not reached"


# --- Routes for serving HTML files ---
@app.route("/")
def index():
    return send_from_directory(app.root_path, 'index.html')

@app.route("/login.html")
def login_page():
    return send_from_directory(app.root_path, 'login.html')

@app.route("/register.html")
def register_page():
    return send_from_directory(app.root_path, 'register.html')

@app.route("/dashboard")
def dashboard_page():
    return send_from_directory(app.root_path, 'dashboard.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# --- API Endpoints ---
@app.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not all([name, email, password]):
        return jsonify({"error": "Missing name, email, or password"}), 400

    conn = connect_db()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor()
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # PostgreSQL's INSERT syntax with RETURNING
        cur.execute("INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
                    (name, email, password_hash))
        user_id = cur.fetchone()[0]
        conn.commit()
        
        token = jwt.encode({"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=1)},
                           JWT_SECRET, algorithm="HS256")
        
        return jsonify({"message": "User registered successfully", "token": token, "user_id": user_id})
    except psycopg2.Error as err:
        if 'duplicate key value' in str(err):
            return jsonify({"error": "Email already registered"}), 409
        print(f"Database error: {err}")
        return jsonify({"error": "Registration failed"}), 500
    finally:
        conn.close()

@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not all([email, password]):
        return jsonify({"error": "Missing email or password"}), 400

    conn = connect_db()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, name, email, password_hash, subscription_tier FROM users WHERE email = %s", (email,))
        user_record = cur.fetchone()

        if user_record and bcrypt.checkpw(password.encode('utf-8'), user_record['password_hash'].encode('utf-8')):
            token_payload = {
                "user_id": user_record['id'],
                "exp": datetime.utcnow() + timedelta(days=7),
                "iat": datetime.utcnow()
            }
            token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")

            user_data = {
                "id": user_record['id'],
                "name": user_record['name'],
                "email": user_record['email'],
                "subscription_tier": user_record['subscription_tier']
            }

            return jsonify({"token": token, "user": user_data})
        else:
            return jsonify({"error": "Invalid email or password"}), 401
    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({"error": "Login failed"}), 500
    finally:
        conn.close()

@app.post("/api/journal/entry")
def api_add_entry():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401
    
    data = request.get_json(silent=True) or {}
    content = data.get("content")
    
    if not content:
        return jsonify({"error": "Entry content cannot be empty"}), 400
    
    conn = connect_db()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        can_add, reason = check_entry_limit(user['id'], conn)
        if not can_add:
            return jsonify({"error": reason}), 403
            
        emotion_label, emotion_score = get_ai_emotions(content)
        
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO entries (user_id, content, emotion_label, emotion_score)
            VALUES (%s, %s, %s, %s)
        """, (user['id'], content, emotion_label, emotion_score))
        conn.commit()
        
        return jsonify({
            "message": "Entry added successfully",
            "emotion": {"label": emotion_label, "score": float(emotion_score)}
        }), 201
    except Exception as e:
        print(f"Journal entry error: {e}")
        return jsonify({"error": "Failed to add entry"}), 500
    finally:
        conn.close()

@app.get("/api/journal/entries")
def api_get_entries():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    conn = connect_db()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    try:
        cur = conn.cursor(dictionary=True)
        tier = get_user_subscription(user['id'], conn)
        history_days = SUBSCRIPTION_PLANS[tier].get('history_days', float('inf'))
        
        query = "SELECT id, content, emotion_label, emotion_score, created_at FROM entries WHERE user_id = %s"
        params = [user['id']]
        
        if history_days != float('inf'):
            query += " AND created_at >= NOW() - INTERVAL '%s days'"
            params.append(str(history_days))
        
        query += " ORDER BY created_at DESC"
        
        cur.execute(query, tuple(params))
        entries = cur.fetchall()
        
        # Convert Decimal objects to floats and datetime objects to strings
        for entry in entries:
            if isinstance(entry['emotion_score'], decimal.Decimal):
                entry['emotion_score'] = float(entry['emotion_score'])
            if isinstance(entry['created_at'], datetime):
                entry['created_at'] = entry['created_at'].isoformat()

        return jsonify(entries)
    except Exception as e:
        print(f"Error fetching entries: {e}")
        return jsonify({"error": "Failed to fetch entries"}), 500
    finally:
        conn.close()
        
@app.get("/api/journal/stats")
def api_get_stats():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401
        
    conn = connect_db()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor()
        
        # Get total entries
        cur.execute("SELECT COUNT(*) FROM entries WHERE user_id = %s", (user['id'],))
        total_entries = cur.fetchone()[0]
        
        # Get entries this month (PostgreSQL compatible)
        cur.execute("""
          SELECT COUNT(*) FROM entries 
          WHERE user_id = %s AND EXTRACT(MONTH FROM created_at) = EXTRACT(MONTH FROM NOW()) AND EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM NOW())
        """, (user['id'],))
        monthly_entries = cur.fetchone()[0]
        
        # Get most common emotion
        cur.execute("""
          SELECT emotion_label, COUNT(*) as count 
          FROM entries 
          WHERE user_id = %s 
          GROUP BY emotion_label 
          ORDER BY count DESC 
          LIMIT 1
        """, (user['id'],))
        most_common = cur.fetchone()
        top_emotion = most_common[0] if most_common else "None"
        
        # Get average emotion score
        cur.execute("SELECT AVG(emotion_score) FROM entries WHERE user_id = %s", (user['id'],))
        avg_score = cur.fetchone()[0] or 0
        
        return jsonify({
            "total_entries": total_entries,
            "monthly_entries": monthly_entries,
            "top_emotion": top_emotion,
            "avg_score": float(avg_score)
        })
    except Exception as e:
        print(f"Stats error: {e}")
        return jsonify({"error": "Failed to fetch stats"}), 500
    finally:
        conn.close()

@app.post("/api/subscription/upgrade")
def upgrade_subscription():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401
        
    data = request.get_json(silent=True) or {}
    plan_tier = data.get("plan")
    
    if not plan_tier or plan_tier not in SUBSCRIPTION_PLANS:
        return jsonify({"error": "Invalid plan specified"}), 400
        
    conn = connect_db()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users 
            SET subscription_tier = %s, subscription_start = %s 
            WHERE id = %s
        """, (plan_tier, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user['id']))
        conn.commit()
        
        cur.execute("""
            INSERT INTO payments (user_id, amount, plan, status)
            VALUES (%s, %s, %s, %s)
        """, (user['id'], SUBSCRIPTION_PLANS[plan_tier]['monthly_price'], plan_tier, 'completed'))
        conn.commit()
        
        return jsonify({
            "message": f"Subscription upgraded to {plan_tier}",
            "plan": SUBSCRIPTION_PLANS[plan_tier],
            "payment_link": "/dashboard?status=success"
        })
    except Exception as e:
        print(f"Upgrade subscription error: {e}")
        return jsonify({"error": "Failed to upgrade subscription"}), 500
    finally:
        conn.close()
