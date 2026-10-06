"""Small live API probes; never collect news or connect to email delivery."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google import genai
from google.genai import types
from app.config import Settings
from app.models import Assessments


def main():
    settings = Settings.from_env()
    key = settings.gemini_api_key.get_secret_value()
    if not key:
        raise SystemExit('GEMINI_API_KEY missing')
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30_000))
    probes = [('plain', 'Reply with OK.', None),
              ('assessment-schema', 'Return an empty items array as JSON.', Assessments)]
    try:
        for label, prompt, schema in probes:
            try:
                config = types.GenerateContentConfig(max_output_tokens=256, temperature=.2,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
                if schema:
                    config.response_mime_type = 'application/json'
                    config.response_schema = schema
                response = client.models.generate_content(model=settings.gemini_model, contents=prompt, config=config)
                print(json.dumps({'probe': label, 'model': settings.gemini_model, 'status': 'accepted',
                    'has_text': bool(response.text)}), flush=True)
            except Exception as exc:
                # Print only the provider message, not exception repr/details/headers/prompt.
                message = str(getattr(exc, 'message', '') or type(exc).__name__)
                message = message.replace(key, '[REDACTED]')
                message = re.sub(r'(?i)(key=|Bearer\s+)[^\s&]+', r'\1[REDACTED]', message)
                message = re.sub(r'AIza[\w-]+', '[REDACTED]', message)
                print(json.dumps({'probe': label, 'model': settings.gemini_model, 'status': 'rejected',
                    'http_code': getattr(exc, 'code', None), 'message': message[:1500]}), flush=True)
                if label == 'plain':
                    return 1
        return 0
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
