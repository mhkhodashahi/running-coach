import os

import google.generativeai as genai
import requests
from dotenv import load_dotenv
from google.api_core.exceptions import GoogleAPIError

load_dotenv()

class ChatClient:
    def __init__(self, model='qwen3:14b'):
        self.model = model

class OllamaClient:
    def __init__(self, model='qwen3:14b', ):
        self.model = model

        self.base_url = 'http://localhost:11434'

    def ask_question(self, prompt, model='qwen3:14b'):
        url = f"{self.base_url}/api/generate"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=180)
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except requests.RequestException as e:
            if e.response is not None:
                print("Ollama error response:", e.response.text)
            print(f"Error communicating with Ollama API: {e}")

            return ""


class GeminiClient:
    def __init__(self, model='gemini-2.5-flash'):
        self.model_name = model
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY must be set in the environment or passed explicitly.")
        genai.configure(api_key=self.api_key)

    def ask_question(self, prompt, model=None):
        model_name = self.model_name
        try:
            model_instance = genai.GenerativeModel(model_name)
            response = model_instance.generate_content(prompt)
            return response.text.strip() if hasattr(response, 'text') else str(response)
        except GoogleAPIError as e:
            print("Gemini API error:", str(e))
            return ""
        except Exception as e:
            print("Unexpected error:", str(e))
            return ""
