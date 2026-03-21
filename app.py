from dotenv import load_dotenv
load_dotenv()  # Load .env before anything else

from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print("Starting Stock Sentiment Analysis App")
    print(f"Running on port: {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
