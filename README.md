Mood Journal: An AI-Powered Emotion Tracker
Welcome to Mood Journal, a full-stack web application designed to help users track their emotional well-being through daily journaling. This application uses an AI model to analyze journal entries and provide users with a deeper understanding of their mood patterns and emotional states over time.

Key Features
Secure Authentication: Users can securely register and log in to their personal accounts.

AI-Powered Emotion Analysis: Each journal entry is sent to a powerful AI model that analyzes the text to identify and score specific emotions.

Journaling Dashboard: A personalized dashboard displays key statistics and insights about a user's emotional journey.

Data Visualization: Interactive charts show mood trends, emotion distribution, and average sentiment scores over time.

Subscription Tiers: The application offers a tiered subscription model (Free, Premium, and Enterprise) with varying levels of access to features like unlimited entries, extended history, and advanced analytics.

Real-time Updates: Data is fetched and updated dynamically, providing a seamless user experience.

Technologies Used
Frontend
HTML5: For the structure and content of the web pages.

CSS3: For styling, including a dark theme and responsive design.

JavaScript: To handle client-side logic, API requests, and dynamic updates.

Chart.js: A flexible charting library used for data visualization.

Backend
Python (Flask): The micro-framework powering the backend API.

MySQL: The relational database used for persistent storage of user and journal entry data.

bcrypt: For secure password hashing.

PyJWT: For creating and verifying JSON Web Tokens to handle user authentication.

Requests: To make HTTP requests to the Hugging Face API.

python-dotenv: To manage environment variables.

AI Model
Hugging Face API: An external API used for the natural language processing (NLP) task of emotion analysis.

Setup and Installation
Follow these steps to get the project running on your local machine.

1. Clone the repository
git clone <repository_url>
cd mood-journal


2. Set up the Python backend
Navigate to the project root directory.
Create and activate a virtual environment:

python3 -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`


Install the required Python packages from the new requirements.txt file:

pip install -r requirements.txt


Create a .env file in the root directory with the following variables. Replace the placeholders with your actual credentials and API key.

HF_API_TOKEN=your_huggingface_api_token
JWT_SECRET=a_strong_random_secret_key
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=mood_journal_db


3. Database Setup
Ensure you have a MySQL server running. Log in to your MySQL shell and create the database:

CREATE DATABASE mood_journal_db;
USE mood_journal_db;


Create the users table:

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


Create the entries table:

CREATE TABLE entries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    content TEXT NOT NULL,
    emotion_label VARCHAR(50),
    emotion_score DECIMAL(5, 4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);


4. Run the Application
Start the Flask development server:

flask run


The application will be accessible at http://127.0.0.1:5000. You can now navigate to this URL in your web browser to use the Mood Journal app.

API Endpoints
The backend provides the following RESTful API endpoints:

POST /api/register: Registers a new user.

POST /api/login: Authenticates a user and returns a JWT.

POST /api/journal/entry: Creates a new journal entry for the authenticated user.

GET /api/journal/entries: Retrieves all journal entries for the authenticated user.

GET /api/journal/stats: Retrieves key statistics for the authenticated user's entries.

Contributing
We welcome contributions! Please feel free to open an issue or submit a pull request with improvements.

License
This project is licensed under the Free License
