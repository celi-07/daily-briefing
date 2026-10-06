import json
from datetime import timedelta

import pandas as pd
import pytest

from app.config import Settings
from app.delivery import load_state, prepare_state, send_state
from app.market import quote_from_history
from app.models import Digest, RenderedPart, SourceHealth
from app.pipeline import build_digest, main
from app.testing import FixtureEngine
from conftest import NOW


def test_market_timestamp_currency_and_unknown_change():
    hist = pd.DataFrame({'Close':[100.]},index=pd.DatetimeIndex(['2026-10-05T00:00:00+00:00']))
    quote = quote_from_history('IDR=X','USD/IDR','IDR per USD',hist,NOW)
    assert quote.price == 100 and quote.change_pct is None and quote.unit == 'IDR per USD'
    assert quote.session_date == '2026-10-05'
    hist.index = pd.DatetimeIndex(['2026-10-01T00:00:00+00:00'])
    assert quote_from_history('x','x','USD',hist,NOW).stale
    hist.index = pd.DatetimeIndex(['2026-10-01'])
    assert quote_from_history('x','x','USD',hist,NOW).unavailable


def sample_parts():
    return [RenderedPart(index=i,total=2,html=f'<p>Story {i}</p>',text=f'Story {i}\nhttps://example.com/{i}',event_ids=[f'e{i}']) for i in (1,2)]


def settings_for(tmp_path):
    return Settings(gmail_address='sender@example.com',gmail_app_password='test-password',state_dir=tmp_path)


def digest():
    return Digest(edition_date='2026-10-06',window_start=NOW-timedelta(days=1),window_end=NOW,timezone='Asia/Jakarta')


class SMTP:
    sent = []
    fail = None
    def __init__(self,*args,**kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def login(self,*args):
        pass
    def send_message(self,message,**kwargs):
        self.sent.append(message)
        if self.fail and len(self.sent) == self.fail:
            raise TimeoutError()
        return {}


def test_partial_uncertain_send_and_restore_without_duplicate(tmp_path):
    settings = settings_for(tmp_path)
    path,state = prepare_state(settings,digest(),sample_parts())
    SMTP.sent,SMTP.fail = [],2
    with pytest.raises(RuntimeError,match='uncertain'):
        send_state(settings,path,state,SMTP)
    restored = load_state(path)
    assert [p['status'] for p in restored['parts']] == ['sent','uncertain']
    with pytest.raises(ValueError,match='uncertain'):
        send_state(settings,path,restored,SMTP)
    assert len(SMTP.sent) == 2
    SMTP.fail = None
    send_state(settings,path,restored,SMTP,retry_uncertain=True)
    assert len(SMTP.sent) == 3 and all(p['status'] == 'sent' for p in load_state(path)['parts'])
    assert SMTP.sent[-1].get_body(preferencelist=('plain',)).get_content().startswith('Story 2')
    assert '2/2' in str(SMTP.sent[-1]['Subject'])


def test_manifest_freezes_payload_and_corruption_refuses_resend(tmp_path):
    settings = settings_for(tmp_path)
    path,state = prepare_state(settings,digest(),sample_parts())
    modified = sample_parts()
    modified[0].html = 'different edition payload'
    _,same = prepare_state(settings,digest(),modified)
    assert same['parts'][0]['payload']['html'] == '<p>Story 1</p>'
    saved = json.loads(path.read_text())
    saved['parts'][0]['hash'] = 'corrupt'
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError,match='corrupt'):
        load_state(path)


def test_all_sources_unavailable_is_not_quiet_market():
    health = [SourceHealth(source_id='test',name='Test',topics=['tech'],status='failed')]
    result = build_digest(Settings(),{},health,NOW,engine=FixtureEngine({}))
    assert not result.stories and 'unavailable' in result.notices[0]


def test_dry_run_offline_fixture_never_collects_or_sends(tmp_path,monkeypatch,article_factory,event_factory):
    a = article_factory()
    assessment = event_factory(a).assessment.model_dump(mode='json')
    assessment.pop('event_id')
    fixture = tmp_path/'fixture.json'
    fixture.write_text(json.dumps({'cutoff':NOW.isoformat(),'articles':[a.model_dump(mode='json')],'assessments':{a.id:assessment}}))
    monkeypatch.setenv('OUTPUT_DIR',str(tmp_path/'preview'))
    monkeypatch.chdir(tmp_path)
    def forbidden(*args,**kwargs):
        raise AssertionError('Unexpected network/email call')
    monkeypatch.setattr('app.pipeline.collect',forbidden)
    monkeypatch.setattr('app.pipeline.fetch_market_snapshot',forbidden)
    monkeypatch.setattr('app.pipeline.send_state',forbidden)
    main(['--fixture',str(fixture),'--dry-run'])
    assert (tmp_path/'preview'/'digest.json').exists()
    assert (tmp_path/'preview'/'preview.txt').exists()


def test_mail_credentials_not_required_for_settings_and_model_is_configurable(monkeypatch):
    monkeypatch.setenv('GEMINI_MODEL','configured-model')
    monkeypatch.setenv('GMAIL_ADDRESS','')
    monkeypatch.setenv('GMAIL_APP_PASSWORD','')
    settings = Settings.from_env()
    assert settings.gemini_model == 'configured-model'
    with pytest.raises(ValueError,match='required'):
        settings.validate_mail()


def test_failed_remote_checkpoint_prevents_smtp_send(tmp_path,monkeypatch):
    from types import SimpleNamespace
    settings = settings_for(tmp_path)
    path,state = prepare_state(settings,digest(),sample_parts())
    monkeypatch.setenv('REQUIRE_REMOTE_CHECKPOINT','true')
    monkeypatch.setattr('app.delivery.subprocess.run',lambda *args,**kwargs:SimpleNamespace(returncode=1))
    SMTP.sent,SMTP.fail = [],None
    with pytest.raises(RuntimeError,match='checkpoint'):
        send_state(settings,path,state,SMTP)
    assert not SMTP.sent


def test_assessment_failure_is_labeled_unassessed_without_fake_score(article_factory):
    article = article_factory()
    result = build_digest(Settings(),{article.id:article},[],NOW,engine=FixtureEngine({}))
    assert result.stories[0].status == 'unassessed'
    assert result.stories[0].importance is None and not result.stories[0].why_it_matters
