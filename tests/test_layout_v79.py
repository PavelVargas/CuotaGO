"""Focused layout/asset contracts, independent of Flask and PostgreSQL."""
from pathlib import Path
from types import SimpleNamespace as NS
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def render_base(collect=True):
    env = Environment(loader=FileSystemLoader(ROOT / 'cuotago/templates'), autoescape=True)
    config = {'ASSET_VERSION': '1.26.8-ui-v78', 'APP_VERSION': '1.26.8'}
    env.globals.update(config=config, app_name='CuotaGo', csrf_token=lambda: 'test',
        can=lambda permission: collect, role_label=lambda _: 'Owner',
        get_flashed_messages=lambda **kw: [],
        url_for=lambda endpoint, **kw: '/static/'+kw['filename']+'?v='+str(kw.get('v','')) if endpoint=='static' else '/'+endpoint,
        request=NS(blueprint='main',endpoint='main.clients'),
        current_user=NS(id=17,is_authenticated=True,role='owner',name='Test',email='test@example.invalid',organization=NS(name='Test',currency='DOP')))
    return env.get_template('base.html').render(), config


def test_version_suffix_without_configuration_mutation():
    rendered, config = render_base()
    assert '1.26.8-ui-v78-layout79' in rendered
    assert config['ASSET_VERSION'] == '1.26.8-ui-v78'
    assert 'fonts.googleapis.com' not in rendered


def test_new_assets_and_load_order():
    rendered, _ = render_base()
    assert rendered.index('js/notification-audio.js') < rendered.index('js/app.js')
    worker = (ROOT/'cuotago/static/service-worker.js').read_text()
    for asset in ['css/layout-v79.css', 'js/notification-audio.js']:
        assert (ROOT/'cuotago/static'/asset).is_file()
        assert '/static/'+asset in rendered
        assert '/static/'+asset in worker


def test_native_dialog_and_existing_navigation_are_preserved():
    rendered, _ = render_base()
    assert rendered.count('id="profileMenuDialog"') == 1
    assert rendered.count('id="profileMenuTrigger"') == 1
    assert 'workspace-module-nav-v75' in rendered
    assert 'data-profile-menu-open' in rendered
    css=(ROOT/'cuotago/static/css/layout-v79.css').read_text()
    assert '.profile-dialog[open] { display: block !important; }' in css
    assert 'width: 90%' in css and '--cg-page-max: 1440px' in css
    assert 'margin: 0 auto' in css


def test_sound_controls_and_permission_boundary():
    template=(ROOT/'cuotago/templates/settings/index.html').read_text()
    start=template.index("{% if can('collections.view') %}")
    end=template.index('{% endif %}',start)
    for control in ['data-alert-tone','data-alert-volume','data-alert-intensity','data-alert-sound-preview']:
        assert control in template[start:end]
    assert 'app cerrada' in template
    assert 'type="button" data-alert-sound-preview' in template


def test_no_business_or_push_permission_requests_in_sound_engine():
    engine=(ROOT/'cuotago/static/js/notification-audio.js').read_text()
    assert 'fetch(' not in engine
    assert 'Notification.requestPermission' not in engine
    assert "cuotago-alert-audio-v1:${userScope}" in engine
    assert 'createDynamicsCompressor' in engine
