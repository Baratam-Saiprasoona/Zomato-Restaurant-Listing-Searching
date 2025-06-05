from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from pymongo import MongoClient, GEOSPHERE
from bson import ObjectId
from werkzeug.utils import secure_filename
import os
import re
import io
import base64
from werkzeug.utils import secure_filename
from PIL import Image

# Import the Gemini API client (adjust if needed)
import google.generativeai as genai 

# Allowed file extensions for image uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Replace with a proper secret key
app.config['UPLOAD_FOLDER'] = 'uploads'

@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    """Upload image and search for restaurants offering detected cuisine with pagination."""
    if request.method == "POST":
        if "file" not in request.files:
            return "No file uploaded."
        file = request.files["file"]
        if file.filename == "" or not allowed_file(file.filename):
            return "Invalid file format. Please upload a valid image."
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        # Ensure upload folder exists
        if not os.path.exists(app.config["UPLOAD_FOLDER"]):
            os.makedirs(app.config["UPLOAD_FOLDER"])
        file.save(file_path)
        image = Image.open(file_path)
        detected_cuisine = detect_cuisine(image)
        # Save detected cuisine in session (so it can be used in GET requests)
        session["detected_cuisine"] = detected_cuisine
        # Optionally remove the file after processing
        os.remove(file_path)
        return redirect(url_for('search_by_detected_cuisine'))
    else:
        detected_cuisine = session.get("detected_cuisine", "")
        return render_template("upload.html", detected_cuisine=detected_cuisine)

def detect_cuisine(image):
    """Detect cuisine from an uploaded image using Gemini API."""
    model = genai.GenerativeModel("gemini-1.5-flash")
    # Convert image to base64
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format="JPEG")
    img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
    # Request Gemini API to detect cuisine
    response = model.generate_content([
        {
            "text": "Identify only the name of the cuisine in one or two words, e.g., 'Italian', 'Indian', 'Mexican'."
        },
        {
            "mime_type": "image/jpeg",
            "data": img_base64
        }
    ])
    if hasattr(response, "text"):
        cuisine_detected = response.text.strip()
        # Extract only the first cuisine word using regex
        match = re.search(r"\b([A-Za-z\s]+)\b", cuisine_detected)
        if match:
            cuisine_cleaned = match.group(1).strip()
            print(f"Extracted Cuisine: {cuisine_cleaned}")
            return cuisine_cleaned
    return ""

@app.route("/search_by_cuisine")
def search_by_detected_cuisine():
    detected_cuisine = session.get("detected_cuisine", "")
    # Here you would perform a database query to search for restaurants that match the detected cuisine.
    # For demonstration, we'll simply pass the detected cuisine to the results template.
    return render_template("search_results.html", cuisine=detected_cuisine)

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["zomato_db"]
restaurants_collection = db["restaurants"]

# Create a geospatial index (make sure your documents have a proper GeoJSON "location" field)
restaurants_collection.create_index([("location", GEOSPHERE)])

# Helper: Convert _id to string
def serialize_restaurant(restaurant):
    restaurant['_id'] = str(restaurant['_id'])
    return restaurant

# Get Restaurant by ID
@app.route('/api/restaurant/<restaurant_id>', methods=['GET'])
def get_restaurant(restaurant_id):
    restaurant = restaurants_collection.find_one({"_id": ObjectId(restaurant_id)})
    if restaurant:
        return jsonify(serialize_restaurant(restaurant))
    else:
        return jsonify({"error": "Restaurant not found"}), 404

# Paginated listing of restaurants
@app.route('/api/restaurants', methods=['GET'])
def get_restaurants():
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    skip = limit * (page - 1)
    total_count = restaurants_collection.count_documents({})
    cursor = restaurants_collection.find().skip(skip).limit(limit)
    restaurants = [serialize_restaurant(doc) for doc in cursor]
    return jsonify({
        "restaurants": restaurants,
        "total_count": total_count
    })

# Location Search endpoint
import re  # Make sure to import re at the top

@app.route('/api/restaurants/search', methods=['GET'])
def search_restaurants():
    # Use 'lat' for restaurant/cuisine query and 'lon' for city query
    query = request.args.get('lat', '')
    city = request.args.get('lon', '')
    
    # Build MongoDB query:
    # - Search for documents where restaurant name or cuisines match 'query'
    # - AND the restaurant's city matches 'city'
    mongo_query = {
        "$and": [
            {
                "$or": [
                    {"restaurant.name": {"$regex": re.escape(query), "$options": "i"}},
                    {"restaurant.cuisines": {"$regex": re.escape(query), "$options": "i"}}
                ]
            },
            {"restaurant.location.city": {"$regex": re.escape(city), "$options": "i"}}
        ]
    }
    
    cursor = restaurants_collection.find(mongo_query)
    restaurants = [serialize_restaurant(doc) for doc in cursor]
    return jsonify(restaurants)


# Image Search endpoint (dummy implementation)
@app.route('/api/restaurants/image_search', methods=['POST'])
def image_search():
    if 'image' not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    file = request.files['image']
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    
    file.save(filepath)
    
    # Dummy logic: extract keyword from file name (e.g., "pasta" from "pasta.jpg")
    cuisine_query = os.path.splitext(filename)[0].lower()
    cursor = restaurants_collection.find({
        "restaurant.cuisines": {"$regex": cuisine_query, "$options": "i"}
    })
    restaurants = [serialize_restaurant(r) for r in cursor]
    
    # Clean up: remove the uploaded file after processing.
    os.remove(filepath)
    
    return jsonify(restaurants)


# UI Routes
@app.route('/')
def index():
    return render_template('restaurant_list.html')

@app.route('/restaurant/<restaurant_id>')
def restaurant_detail(restaurant_id):
    return render_template('restaurant_detail.html', restaurant_id=restaurant_id)

if __name__ == '__main__':
    app.run(debug=True)
