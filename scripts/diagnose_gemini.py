"""Small live API probes; never collect news or connect to email delivery."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google import genai
from google.genai import types
from app.config import Settings
from app.models import Assessments, Drafts, Verdicts, Synthesis


def main():
    settings = Settings.from_env()
    key = settings.gemini_api_key.get_secret_value()
    if not key:
        raise SystemExit('GEMINI_API_KEY missing')
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60_000))
    probes = [(name, 'Return an empty items array as JSON.', schema) for name, schema in
              [('assessment-schema', Assessments), ('summary-schema', Drafts),
               ('verification-schema', Verdicts), ('synthesis-schema', Synthesis)]]
    failed = False
    try:
        for label, prompt, schema in probes:
            try:
                config = types.GenerateContentConfig(max_output_tokens=8192, temperature=.2,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
                if schema:
                    config.response_mime_type = 'application/json'
                    config.response_json_schema = schema.model_json_schema()
                response = client.models.generate_content(model=settings.gemini_model, contents=prompt, config=config)
                print(json.dumps({'probe': label, 'model': settings.gemini_model, 'status': 'accepted',
                    'valid_output': schema.model_validate_json(response.text or '').items == []}), flush=True)
            except Exception as exc:
                failed = True
                # Print only the provider message, not exception repr/details/headers/prompt.
                message = str(getattr(exc, 'message', '') or type(exc).__name__)
                message = message.replace(key, '[REDACTED]')
                message = re.sub(r'(?i)(key=|Bearer\s+)[^\s&]+', r'\1[REDACTED]', message)
                message = re.sub(r'AIza[\w-]+', '[REDACTED]', message)
                print(json.dumps({'probe': label, 'model': settings.gemini_model, 'status': 'rejected',
                    'http_code': getattr(exc, 'code', None), 'message': message[:1500]}), flush=True)
        return 1 if failed else 0
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
