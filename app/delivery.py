import json
import os
import smtplib
import ssl
import subprocess
from email.message import EmailMessage
from pathlib import Path

from app.models import Digest, RenderedPart, stable_id


def validate_digest_for_delivery(digest):
    unassessed = sum(event.assessment is None for event in digest.decisions)
    excerpts = sum(story.status != "verified-analysis" for story in digest.stories)
    if unassessed or excerpts:
        raise ValueError(f"AI briefing incomplete: {unassessed} unassessed event(s), {excerpts} source excerpt(s). "
                         "Email withheld; inspect coverage.json and fix the AI connection or budget before retrying.")


def checkpoint(path):
    if os.environ.get("REQUIRE_REMOTE_CHECKPOINT", "").lower() == "true":
        from app.config import ROOT
        result = subprocess.run(["node", str(ROOT / "scripts/checkpoint/upload.cjs"), str(path.resolve())],
                                capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError("Durable delivery checkpoint failed; refusing to continue sending")


def state_path(settings, edition_date):
    recipient = settings.recipient_email or settings.gmail_address
    return settings.state_dir / (edition_date + "-" + stable_id(recipient.lower()) + ".json")


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    checkpoint(path)


def load_state(path):
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("version") != 1 or not state.get("parts"):
            raise ValueError("Invalid manifest version/parts")
        for item in state["parts"]:
            part = RenderedPart.model_validate(item["payload"])
            content_hash = stable_id(part.html + part.text)
            if item["hash"] != content_hash or item["status"] not in ("pending", "sending", "sent", "uncertain"):
                raise ValueError("Invalid delivery payload/state")
        return state
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Delivery state is corrupt; refusing an unprotected resend") from exc


def prepare_state(settings, digest, parts):
    path = state_path(settings, digest.edition_date)
    state = load_state(path)
    if state is None:
        state = {"version": 1, "edition_date": digest.edition_date, "digest": digest.model_dump(mode="json"),
                 "parts": [{"payload": p.model_dump(), "hash": stable_id(p.html + p.text), "status": "pending"} for p in parts]}
        save_state(path, state)
    return path, state


def send_state(settings, path, state, smtp_factory=smtplib.SMTP_SSL, retry_uncertain=False):
    if any(item["status"] != "sent" for item in state["parts"]):
        validate_digest_for_delivery(Digest.model_validate(state["digest"]))
    settings.validate_mail()
    sender = settings.gmail_address
    recipient = settings.recipient_email or sender
    if any(item["status"] in ("sending", "uncertain") for item in state["parts"]) and not retry_uncertain:
        raise ValueError("Delivery uncertain after an interrupted send; inspect mailbox, then explicitly use --retry-uncertain")
    for item in state["parts"]:
        if item["status"] == "sent":
            continue
        part = RenderedPart.model_validate(item["payload"])
        message = EmailMessage()
        suffix = f" — {part.index}/{part.total}" if part.total > 1 else ""
        message["Subject"] = f"Morning Briefing — {state['edition_date']}{suffix}"
        message["From"] = f"Morning Briefing <{sender}>"
        message["To"] = recipient
        # Stable Message-ID helps mailbox inspection; SMTP still cannot promise exactly-once delivery.
        message["Message-ID"] = f"<{stable_id(path.name + str(part.index))}@daily-briefing.local>"
        message.set_content(part.text)
        message.add_alternative(part.html, subtype="html")
        # TLS connection/login failures occur before handing the message to the server.
        with smtp_factory("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as server:
            server.login(sender, settings.gmail_app_password.get_secret_value().replace(" ", ""))
            item["status"] = "sending"
            save_state(path, state)
            try:
                refused = server.send_message(message, from_addr=sender, to_addrs=[recipient])
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
            except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
                item["status"] = "pending"  # Explicit negative SMTP response: no acceptance.
                save_state(path, state)
                raise RuntimeError("SMTP rejected the message; delivery remains pending") from None
            except Exception:
                item["status"] = "uncertain"
                save_state(path, state)
                raise RuntimeError("SMTP outcome uncertain; inspect mailbox before retrying") from None
            item["status"] = "sent"
            save_state(path, state)
