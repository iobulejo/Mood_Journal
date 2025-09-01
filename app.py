import os, json, decimal
from datetime import datetime, date
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import psycopg2
import requests
import bcrypt
import jwt
from datetime import datetime, timedelta
from urllib.parse import urlparse

load_dotenv()

HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
HF_HEADERS = {"Authorization": f"Bearer {HF_API_TOKEN}"} if HF_API_TOKEN else {}
EMOTION_MODEL = os.getenv("EMOTION_MODEL", "j-hartmann/emotion-english-distilroberta-base")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")

# Define the database configuration from a single URL
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    url = urlparse(DATABASE_URL)
    DB_CFG = dict(
        host=url.hostname,
        user=url.username,
        password=url.password,
        database=url.path[1:],
        port=url.port,
    )
else:
    # Fallback for local development
    DB_CFG = dict(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "mood_journal_db"),
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
        "features": ["Unlimited entries", "30-day history", "Advanced analytics", "Export"],
        "limitations": []
    },
    "enterprise": {
        "name": "Enterprise",
        "monthly_price": 29.99,
        "max_entries": float('inf'),
        "history_days": float('inf'),
        "features": ["Unlimited everything", "1-year history", "Team features", "API access"],
        "limitations": []
    }
}

app = Flask(__name__, static_folder="static")
CORS(app)

# Helper function to connect to the database
def connect_db():
    try:
        return psycopg2.connect(**DB_CFG)
    except psycopg2.OperationalError as err:
        print(f"Database connection failed: {err}")
        return None

# Helper function to verify and decode JWT
def get_user_from_request():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None
    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload['user']
    except (jwt.InvalidTokenError, IndexError):
        return None

# Emotion analysis function
def analyze_emotion(text):
    if not HF_API_TOKEN:
        return "neutral", 0.5
    
    API_URL = f"https://api-inference.huggingface.co/models/{EMOTION_MODEL}"
    try:
        response = requests.post(API_URL, headers=HF_HEADERS, json={"inputs": text})
        response.raise_for_status()
        result = response.json()[0]
        
        # Find the highest scoring emotion
        max_score = 0
        best_emotion = "neutral"
        for item in result:
            if item['score'] > max_score:
                max_score = item['score']
                best_emotion = item['label']
                
        return best_emotion, float(max_score)
    except requests.exceptions.RequestException as e:
        print(f"Hugging Face API error: {e}")
        return "error", 0.0

@app.route("/")
def index():
    return send_from_directory('static', 'index.html')

@app.route("/login.html")
def login_page():
    return send_from_directory('static', 'login.html')

@app.route("/register.html")
def register_page():
    return send_from_directory('static', 'register.html')

@app.route("/dashboard")
def dashboard_page():
    return render_template('dashboard.html')

@app.route("/profile")
def profile_page():
    return render_template('profile.html')

@app.post("/api/register")
def api_register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    if not all([name, email, password]):
        return jsonify({"error": "Missing required fields"}), 400

    conn = connect_db()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor()
        
        # Check if user already exists
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return jsonify({"error": "User with this email already exists"}), 409
        
        # Hash password and insert user
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute("INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) RETURNING id", (name, email, hashed_password))
        user_id = cur.fetchone()[0]
        conn.commit()
        
        # Generate JWT
        payload = {'user': {'id': user_id, 'name': name, 'email': email, 'subscription_tier': 'free'}, 'exp': datetime.utcnow() + timedelta(days=7)}
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        
        return jsonify({
            "message": "User registered successfully",
            "token": token,
            "user": {'id': user_id, 'name': name, 'email': email, 'subscription_tier': 'free'}
        }), 201
    except psycopg2.Error as err:
        print(f"PostgreSQL error: {err}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn:
            conn.close()

@app.post("/api/login")
def api_login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not all([email, password]):
        return jsonify({"error": "Missing email or password"}), 400
    
    conn = connect_db()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()

        if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            # Get user's subscription tier
            tier = user.get('subscription_tier', 'free')

            # Generate JWT
            payload = {'user': {'id': user['id'], 'name': user['name'], 'email': user['email'], 'subscription_tier': tier}, 'exp': datetime.utcnow() + timedelta(days=7)}
            token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
            
            return jsonify({
                "message": "Login successful",
                "token": token,
                "user": {'id': user['id'], 'name': user['name'], 'email': user['email'], 'subscription_tier': tier}
            })
        else:
            return jsonify({"error": "Invalid email or password"}), 401
    except psycopg2.Error as err:
        print(f"PostgreSQL error: {err}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn:
            conn.close()

@app.post("/api/journal/entry")
def api_add_entry():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    conn = connect_db()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor()
        
        # Check entry limits for 'free' tier
        if user['subscription_tier'] == 'free':
            cur.execute("SELECT COUNT(*) FROM entries WHERE user_id = %s AND created_at >= CURRENT_DATE - INTERVAL '%s days'", (user['id'], SUBSCRIPTION_PLANS['free']['history_days']))
            entry_count = cur.fetchone()[0]
            if entry_count >= SUBSCRIPTION_PLANS['free']['max_entries']:
                return jsonify({"error": f"Free plan is limited to {SUBSCRIPTION_PLANS['free']['max_entries']} entries per month."}), 403

        data = request.get_json(silent=True) or {}
        content = data.get('content')
        if not content:
            return jsonify({"error": "Journal entry cannot be empty"}), 400
        
        # Analyze the emotion
        emotion_label, emotion_score = analyze_emotion(content)

        cur.execute("INSERT INTO entries (user_id, content, emotion_label, emotion_score) VALUES (%s, %s, %s, %s)", (user['id'], content, emotion_label, decimal.Decimal(emotion_score)))
        conn.commit()

        return jsonify({
            "message": "Entry saved successfully",
            "entry": {
                "content": content,
                "emotion_label": emotion_label,
                "emotion_score": str(emotion_score)
            }
        }), 201

    except psycopg2.Error as err:
        print(f"PostgreSQL error: {err}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn:
            conn.close()

@app.get("/api/journal/entries")
def api_get_entries():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401
    
    conn = connect_db()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        limit_days = SUBSCRIPTION_PLANS.get(user['subscription_tier'], SUBSCRIPTION_PLANS['free'])['history_days']
        
        # Query entries based on the user's subscription tier
        if limit_days == float('inf'):
            cur.execute("SELECT id, content, emotion_label, emotion_score, created_at FROM entries WHERE user_id = %s ORDER BY created_at DESC", (user['id'],))
        else:
            cur.execute("SELECT id, content, emotion_label, emotion_score, created_at FROM entries WHERE user_id = %s AND created_at >= CURRENT_DATE - INTERVAL '%s days' ORDER BY created_at DESC", (user['id'], limit_days))

        entries = cur.fetchall()
        
        # Format the date and score for JSON
        for entry in entries:
            entry['created_at'] = entry['created_at'].isoformat()
            entry['emotion_score'] = str(entry['emotion_score'])
        
        return jsonify({"entries": entries})
    except psycopg2.Error as err:
        print(f"PostgreSQL error: {err}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn:
            conn.close()

@app.get("/api/journal/stats")
def api_get_stats():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401
        
    conn = connect_db()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    try:
        cur = conn.cursor()
        
        # Get total entries
        cur.execute("SELECT COUNT(*) FROM entries WHERE user_id = %s", (user['id'],))
        total_entries = cur.fetchone()[0]
        
        # Get entries this month
        cur.execute("""
          SELECT COUNT(*) FROM entries 
          WHERE user_id = %s AND EXTRACT(MONTH FROM created_at) = EXTRACT(MONTH FROM CURRENT_DATE) AND EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM CURRENT_DATE)
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
            "avg_score": str(avg_score)
        })
    finally:
        if conn:
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
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users 
            SET subscription_tier = %s
            WHERE id = %s
        """, (plan_tier, user['id']))
        conn.commit()
        
        return jsonify({
            "message": f"Subscription upgraded to {plan_tier}",
            "plan": SUBSCRIPTION_PLANS[plan_tier]
        })
    finally:
        if conn:
            conn.close()

@app.get("/api/profile/info")
def get_profile_info():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401
    
    conn = connect_db()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT name, email, subscription_tier, created_at FROM users WHERE id = %s", (user['id'],))
        profile_info = cur.fetchone()

        if not profile_info:
            return jsonify({"error": "User not found"}), 404
        
        profile_info['created_at'] = profile_info['created_at'].isoformat()
        
        return jsonify(profile_info)
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
