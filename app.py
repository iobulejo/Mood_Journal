import os
import json
import decimal
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import psycopg2  # Changed from mysql.connector
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse  # To parse DATABASE_URL (optional)
import requests
import bcrypt
import jwt
import collections
from collections import defaultdict

load_dotenv()
 # Ensure DB is created when running locally
    init_db()
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
HF_HEADERS = {"Authorization": f"Bearer {HF_API_TOKEN}"} if HF_API_TOKEN else {}
EMOTION_MODEL = os.getenv("EMOTION_MODEL", "j-hartmann/emotion-english-distilroberta-base")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")

# New: Use a single DATABASE_URL for connection
DATABASE_URL = os.getenv("DATABASE_URL")

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
        "max_entries": 1000,
        "history_days": 30,
        "features": ["Detailed emotion analysis", "30-day history", "Advanced analytics", "Export to CSV"]
    },
    "enterprise": {
        "name": "Enterprise",
        "monthly_price": 29.99,
        "max_entries": 10000,
        "history_days": 365,
        "features": ["Team management", "Unlimited history", "API access", "Custom emotion models"]
    }
}

# New: Emojis for each emotion label
EMOTION_EMOJIS = {
    'joy': '😊',
    'sadness': '😢',
    'anger': '😠',
    'fear': '😨',
    'disgust': '🤢',
    'surprise': '😮',
    'neutral': '😐',
}

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret-key")
CORS(app)


def connect_db():
    """Connects to the PostgreSQL database using the DATABASE_URL."""
    if not DATABASE_URL:
        raise Exception("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = connect_db()
    try:
        cur = conn.cursor()
        # Create users table with PostgreSQL syntax
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                name VARCHAR(255),
                subscription_tier VARCHAR(20) DEFAULT 'free',
                subscription_start DATE,
                entries_this_month INT DEFAULT 0,
                last_reset_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create entries table with user_id foreign key
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                content TEXT NOT NULL,
                emotion_label VARCHAR(32) NOT NULL,
                emotion_score DECIMAL(5,2) NOT NULL,
                emotions_json JSONB NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Create payments table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                plan VARCHAR(20) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        conn.commit()
    finally:
        conn.close()


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def create_jwt_token(user_id):
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


def verify_jwt_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_user_from_request():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None

    token = auth_header[7:]
    payload = verify_jwt_token(token)
    if not payload:
        return None

    conn = connect_db()
    try:
        # Use RealDictCursor to get dictionary-like results
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, email, name, subscription_tier, entries_this_month FROM users WHERE id = %s", (payload['user_id'],))
        return cur.fetchone()
    finally:
        conn.close()


def get_user_entries_this_month(user_id):
    conn = connect_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT last_reset_date, entries_this_month FROM users WHERE id = %s", (user_id,))
        user_data = cur.fetchone()

        if user_data:
            last_reset, entries_count = user_data
            # handle None last_reset
            if last_reset is None:
                last_reset = datetime.utcnow()
            current_date = date.today()

            # if last_reset is a datetime, compare months/years
            if isinstance(last_reset, datetime):
                last_reset_month = last_reset.month
                last_reset_year = last_reset.year
            else:
                # fallback if date object
                last_reset_month = last_reset.month
                last_reset_year = last_reset.year

            if last_reset_month != current_date.month or last_reset_year != current_date.year:
                cur.execute("""
                    UPDATE users 
                    SET entries_this_month = 0, last_reset_date = %s 
                    WHERE id = %s
                """, (current_date, user_id))
                conn.commit()
                return 0
            return entries_count
        return 0
    finally:
        conn.close()


def increment_user_entries(user_id):
    conn = connect_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users 
            SET entries_this_month = entries_this_month + 1 
            WHERE id = %s
        """, (user_id,))
        conn.commit()
    finally:
        conn.close()


def analyze_emotion(text: str):
    url = f"https://api-inference.huggingface.co/models/{EMOTION_MODEL}"
    payload = {"inputs": text}
    r = requests.post(url, headers=HF_HEADERS, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    distribution = data[0] if isinstance(data, list) and isinstance(data[0], list) else data
    dist_norm = sorted(
        [{"label": d["label"], "score": round(float(d["score"]) * 100, 2)} for d in distribution],
        key=lambda x: x["score"], reverse=True
    )
    top = dist_norm[0] if dist_norm else {"label": "neutral", "score": 50.0}
    return top["label"], top["score"], dist_norm


def row_to_entry(row):
    # Now expects a dictionary-like object from RealDictCursor
    return {
        "id": row['id'],
        "content": row['content'],
        "emotion_label": row['emotion_label'],
        "emotion_emoji": EMOTION_EMOJIS.get(row['emotion_label'], '❓'),
        "emotion_score": float(row['emotion_score']),
        "emotions": row['emotions_json'] if row['emotions_json'] else [],
        "created_at": row['created_at'].isoformat(),
    }


@app.route("/")
def home():
    # If you want to serve templates.index.html, use render_template("index.html")
    # Keeping send_from_directory to match your previous behavior
    return send_from_directory("static", "index.html")


@app.route("/login.html")
def login_page():
    return render_template("login.html")


@app.route("/register.html")
def register_page():
    return render_template("register.html")


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    email, password, name = data.get("email", "").strip(), data.get("password", ""), data.get("name", "").strip()
    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
    conn = connect_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            return jsonify({"error": "User already exists"}), 409

        password_hash = hash_password(password)

        # Use RETURNING id to get the new user's ID
        sql = "INSERT INTO users (email, password_hash, name, subscription_tier, subscription_start) VALUES (%s, %s, %s, %s, %s) RETURNING id"
        values = (email, password_hash, name, 'free', date.today())
        cur.execute(sql, values)
        user_id = cur.fetchone()[0]  # Fetch the returned ID
        conn.commit()

        token = create_jwt_token(user_id)

        return jsonify({
            "message": "User registered successfully",
            "token": token,
            "user": {
                "id": user_id,
                "email": email,
                "name": name,
                "subscription_tier": "free"
            }
        }), 201
    except psycopg2.Error as err:  # Changed error type
        conn.rollback()
        return jsonify({"error": f"Database error: {err}"}), 500
    finally:
        conn.close()


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    email, password = data.get("email", "").strip(), data.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    conn = connect_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)  # Use RealDictCursor
        cur.execute("SELECT id, password_hash, name, subscription_tier FROM users WHERE email=%s", (email,))
        user = cur.fetchone()

        if user and check_password(password, user['password_hash']):
            token = create_jwt_token(user['id'])
            return jsonify({
                "message": "Login successful",
                "token": token,
                "user": {
                    "id": user['id'],
                    "email": email,
                    "name": user['name'],
                    "subscription_tier": user['subscription_tier']
                }
            })
        else:
            return jsonify({"error": "Invalid email or password"}), 401
    finally:
        conn.close()


@app.get("/api/profile")
def get_profile():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    entries_this_month = get_user_entries_this_month(user['id'])
    plan = SUBSCRIPTION_PLANS.get(user['subscription_tier'], SUBSCRIPTION_PLANS['free'])

    return jsonify({
        "user": user,
        "usage": {
            "entries_this_month": entries_this_month,
            "entries_remaining": plan['max_entries'] - entries_this_month,
            "max_entries": plan['max_entries']
        },
        "plan": plan
    })


@app.get("/api/entries")
def list_entries():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return jsonify({"error": "Invalid pagination params"}), 400

    plan = SUBSCRIPTION_PLANS.get(user['subscription_tier'], SUBSCRIPTION_PLANS['free'])
    history_days = plan['history_days']

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    # Use PostgreSQL interval syntax: we will use parameterized query with interval
    filters = ["user_id = %s", "created_at >= NOW() - INTERVAL '%s days'"]
    params = [user['id'], history_days]

    if start_date:
        filters.append("created_at >= %s")
        params.append(start_date)
    if end_date:
        filters.append("created_at <= %s")
        params.append(end_date)

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    conn = connect_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)  # Use RealDictCursor for row_to_entry
        # Note: the where_clause only contains safe pieces constructed above
        query = f"""
            SELECT id, content, emotion_label, emotion_score, emotions_json, created_at
            FROM entries
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, (*params, limit, offset))
        rows = cur.fetchall()

        count_query = f"SELECT COUNT(*) FROM entries {where_clause}"
        # For count, use same params but without limit/offset
        cur.execute(count_query, tuple(params))
        total_row = cur.fetchone()
        total = total_row['count'] if isinstance(total_row, dict) and 'count' in total_row else (total_row[0] if total_row else 0)

        entries = [row_to_entry(r) for r in rows]

        original_trend = [
            {"created_at": e["created_at"], "score": e["emotion_score"]}
            for e in entries
        ]

        multi_trend = [
            {"created_at": e["created_at"], "emotions": e["emotions"]}
            for e in entries
        ]

        return jsonify({
            "total": total,
            "limit": limit,
            "offset": offset,
            "entries": entries,
            "original_trend": original_trend,
            "multi_trend": multi_trend
        })
    finally:
        conn.close()


@app.post("/api/entries")
def create_entry():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400

    entries_this_month = get_user_entries_this_month(user['id'])
    plan = SUBSCRIPTION_PLANS.get(user['subscription_tier'], SUBSCRIPTION_PLANS['free'])

    if entries_this_month >= plan['max_entries']:
        return jsonify({
            "error": "Monthly entry limit exceeded",
            "limit": plan['max_entries'],
            "current": entries_this_month
        }), 429

    label, score_pct, dist = analyze_emotion(content)
    conn = connect_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)  # Use RealDictCursor for row_to_entry
        cur.execute("""
            INSERT INTO entries (user_id, content, emotion_label, emotion_score, emotions_json)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (user['id'], content, label, score_pct, json.dumps(dist)))

        entry_row = cur.fetchone()
        entry_id = entry_row['id'] if isinstance(entry_row, dict) and 'id' in entry_row else (entry_row[0] if entry_row else None)
        conn.commit()

        increment_user_entries(user['id'])

        cur.execute("""
            SELECT id, content, emotion_label, emotion_score, emotions_json, created_at
            FROM entries WHERE id=%s
        """, (entry_id,))
        row = cur.fetchone()
        return jsonify(row_to_entry(row)), 201
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
    try:
        cur = conn.cursor()
        # Use CURRENT_DATE for PostgreSQL
        cur.execute("""
            UPDATE users 
            SET subscription_tier = %s, subscription_start = CURRENT_DATE
            WHERE id = %s
        """, (plan_tier, user['id']))

        cur.execute("""
            INSERT INTO payments (user_id, amount, plan, status)
            VALUES (%s, %s, %s, %s)
        """, (user['id'], SUBSCRIPTION_PLANS[plan_tier]['monthly_price'], plan_tier, 'completed'))
        conn.commit()

        return jsonify({
            "message": f"Subscription upgraded to {plan_tier}",
            "plan": SUBSCRIPTION_PLANS[plan_tier]
        })
    finally:
        conn.close()


@app.get("/api/stats")
def get_stats():
    user = get_user_from_request()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    conn = connect_db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM entries WHERE user_id = %s", (user['id'],))
        total_entries_row = cur.fetchone()
        total_entries = total_entries_row[0] if total_entries_row else 0

        # Use EXTRACT for PostgreSQL date functions
        cur.execute("""
            SELECT COUNT(*) FROM entries 
            WHERE user_id = %s AND EXTRACT(MONTH FROM created_at) = EXTRACT(MONTH FROM CURRENT_DATE) 
            AND EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM CURRENT_DATE)
        """, (user['id'],))
        monthly_entries_row = cur.fetchone()
        monthly_entries = monthly_entries_row[0] if monthly_entries_row else 0

        cur.execute("""
            SELECT emotion_label, COUNT(*) as count 
            FROM entries 
            WHERE user_id = %s 
            GROUP BY emotion_label 
            ORDER BY count DESC 
            LIMIT 1
        """, (user['id'],))
        most_common = cur.fetchone()

        top_emotion = f"{most_common[0]} {EMOTION_EMOJIS.get(most_common[0], '❓')}" if most_common else "None"

        cur.execute("SELECT AVG(emotion_score) FROM entries WHERE user_id = %s", (user['id'],))
        avg_score_row = cur.fetchone()
        avg_score = avg_score_row[0] if avg_score_row and avg_score_row[0] is not None else 0

        # Emotion Distribution Data
        cur.execute("""
            SELECT emotion_label, COUNT(*) FROM entries
            WHERE user_id = %s
            GROUP BY emotion_label
        """, (user['id'],))
        emotion_counts = cur.fetchall()

        emotion_distribution_data = [
            {"label": label, "count": count, "emoji": EMOTION_EMOJIS.get(label, '❓')}
            for label, count in emotion_counts
        ]

        # Mood Trend Data (last 30 days)
        trend_data = defaultdict(lambda: {'count': 0, 'total_score': 0})
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=30)

        cur.execute("""
            SELECT created_at, emotion_score FROM entries
            WHERE user_id = %s AND created_at BETWEEN %s AND %s
            ORDER BY created_at
        """, (user['id'], start_date, end_date))
        daily_scores = cur.fetchall()

        for timestamp, score in daily_scores:
            date_str = timestamp.strftime('%Y-%m-%d')
            trend_data[date_str]['count'] += 1
            trend_data[date_str]['total_score'] += float(score)

        mood_trend_data = []
        for i in range(31):
            day = start_date + timedelta(days=i)
            day_str = day.strftime('%Y-%m-%d')
            entry = trend_data.get(day_str)
            avg_score = round(entry['total_score'] / entry['count'], 2) if entry and entry['count'] > 0 else 0
            mood_trend_data.append({'date': day_str, 'average_score': avg_score})

        # New: Weekly Mood Pattern
        weekly_mood = collections.OrderedDict({
            'Monday': {'total_score': 0, 'count': 0}, 'Tuesday': {'total_score': 0, 'count': 0},
            'Wednesday': {'total_score': 0, 'count': 0}, 'Thursday': {'total_score': 0, 'count': 0},
            'Friday': {'total_score': 0, 'count': 0}, 'Saturday': {'total_score': 0, 'count': 0},
            'Sunday': {'total_score': 0, 'count': 0}
        })

        cur.execute("SELECT created_at, emotion_score FROM entries WHERE user_id = %s", (user['id'],))
        weekly_data = cur.fetchall()
        for timestamp, score in weekly_data:
            day_name = timestamp.strftime('%A')
            weekly_mood[day_name]['total_score'] += float(score)
            weekly_mood[day_name]['count'] += 1

        weekly_pattern = [{'day': day, 'average_score': round(data['total_score'] / data['count'], 2) if data['count'] > 0 else 0} for day, data in weekly_mood.items()]

        # New: Emotion Correlation
        cur.execute("SELECT emotions_json FROM entries WHERE user_id = %s", (user['id'],))
        all_emotions_json = [row[0] for row in cur.fetchall() if row[0]]

        emotion_pairs = defaultdict(int)
        for emotions in all_emotions_json:
            # emotions might already be parsed or stored as JSON string
            if isinstance(emotions, str):
                try:
                    emotions = json.loads(emotions)
                except Exception:
                    emotions = emotions  # leave as-is if parsing fails
            labels = sorted([e['label'] for e in emotions])
            for i in range(len(labels)):
                for j in range(i + 1, len(labels)):
                    pair = tuple(sorted((labels[i], labels[j])))
                    emotion_pairs[pair] += 1

        emotion_correlation_data = [
            {'pair': f'{p[0]} & {p[1]}', 'count': c} for p, c in emotion_pairs.items()
        ]

        return jsonify({
            "total_entries": total_entries,
            "monthly_entries": monthly_entries,
            "top_emotion": top_emotion,
            "avg_score": float(avg_score) if avg_score else 0,
            "emotion_distribution": emotion_distribution_data,
            "mood_trend": mood_trend_data,
            "weekly_mood_pattern": weekly_pattern,
            "emotion_correlation": emotion_correlation_data
        })
    finally:
        conn.close()


if __name__ == "__main__":
   
    app.run(debug=False)


