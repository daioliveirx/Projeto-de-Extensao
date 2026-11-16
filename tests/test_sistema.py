import os,sys,tempfile,io
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import pytest
from app.web import create_app
from app.db import get_db
from app.rules import validar_aula,ha_conflito

@pytest.fixture
def client(tmp_path):
    app=create_app({'TESTING':True,'DATABASE':str(tmp_path/'teste.db'),'UPLOAD_FOLDER':str(tmp_path/'uploads')})
    return app.test_client()

def nova(client,data='2026-11-18',inicio='19:00',fim='20:40',professor='1',turma='1'):
    return client.post('/ausencias/nova',data={'professor_id':professor,'turma_id':turma,'disciplina_id':'1','data':data,'inicio':inicio,'fim':fim,'motivo':'Saúde'},follow_redirects=True)

def test_painel(client): assert client.get('/').status_code==200

def test_formulario(client): assert client.get('/ausencias/nova').status_code==200

def test_registro_e_vaga(client):
    r=nova(client);assert r.status_code==200
    with client.application.app_context():
        assert get_db().execute('SELECT status FROM ausencias').fetchone()[0]=='VAGA'

def test_horario_invalido(client):
    nova(client,inicio='21:00',fim='20:00')
    with client.application.app_context(): assert get_db().execute('SELECT COUNT(*) FROM ausencias').fetchone()[0]==0

def test_substituicao(client):
    nova(client)
    r=client.post('/ausencias/1',data={'acao':'substituir','professor_id':'2'},follow_redirects=True)
    assert b'SUBSTITUIDA' in r.data

def test_nao_substitui_a_si(client):
    nova(client);client.post('/ausencias/1',data={'acao':'substituir','professor_id':'1'})
    with client.application.app_context(): assert get_db().execute('SELECT COUNT(*) FROM substituicoes').fetchone()[0]==0

def test_conflito_de_substituicao(client):
    nova(client);nova(client,inicio='19:30',fim='21:00',professor='3',turma='2')
    client.post('/ausencias/1',data={'acao':'substituir','professor_id':'2'})
    client.post('/ausencias/2',data={'acao':'substituir','professor_id':'2'})
    with client.application.app_context(): assert get_db().execute('SELECT COUNT(*) FROM substituicoes').fetchone()[0]==1

def test_reposicao(client):
    nova(client);client.post('/ausencias/1',data={'acao':'reposicao','data':'2026-11-20','inicio':'18:00','fim':'19:00'})
    with client.application.app_context(): assert get_db().execute('SELECT status FROM ausencias').fetchone()[0]=='REPOSICAO_AGENDADA'

def test_upload_valido(client):
    nova(client);r=client.post('/ausencias/1',data={'acao':'documento','tipo':'ATESTADO','arquivo':(io.BytesIO(b'%PDF-1.4 exemplo'),'teste.pdf')},content_type='multipart/form-data',follow_redirects=True)
    assert r.status_code==200
    with client.application.app_context(): assert get_db().execute('SELECT COUNT(*) FROM documentos').fetchone()[0]==1

def test_upload_extensao_invalida(client):
    nova(client);client.post('/ausencias/1',data={'acao':'documento','tipo':'ATESTADO','arquivo':(io.BytesIO(b'texto'),'teste.exe')},content_type='multipart/form-data')
    with client.application.app_context(): assert get_db().execute('SELECT COUNT(*) FROM documentos').fetchone()[0]==0

def test_pdf(client):
    nova(client);r=client.get('/relatorio.pdf');assert r.status_code==200 and r.data[:4]==b'%PDF'

def test_filtro_turma(client):
    nova(client);assert client.get('/?turma=1').status_code==200


def test_registro_bloqueia_sobreposicao_professor(client):
    nova(client)
    r=nova(client,inicio='19:30',fim='20:00',turma='2')
    assert 'Conflito de horário'.encode() in r.data
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM ausencias').fetchone()[0]==1


def test_registro_bloqueia_sobreposicao_turma(client):
    nova(client)
    r=nova(client,inicio='19:30',fim='21:00',professor='3')
    assert 'Conflito de horário'.encode() in r.data
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM ausencias').fetchone()[0]==1


def test_registro_permite_horarios_consecutivos(client):
    nova(client)
    nova(client,inicio='20:40',fim='22:00')
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM ausencias').fetchone()[0]==2


def test_substituto_nao_pode_ter_aula_propria(client):
    nova(client)
    nova(client,professor='2',turma='2')
    r=client.post('/ausencias/1',data={'acao':'substituir','professor_id':'2'},follow_redirects=True)
    assert 'Professor indisponível'.encode() in r.data
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM substituicoes').fetchone()[0]==0


def test_nao_agenda_reposicao_apos_substituicao(client):
    nova(client)
    client.post('/ausencias/1',data={'acao':'substituir','professor_id':'2'})
    client.post('/ausencias/1',data={'acao':'reposicao','data':'2026-11-20','inicio':'18:00','fim':'19:00'})
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM reposicoes').fetchone()[0]==0


def test_nao_agenda_duas_reposicoes(client):
    nova(client)
    dados={'acao':'reposicao','data':'2026-11-20','inicio':'18:00','fim':'19:00'}
    client.post('/ausencias/1',data=dados)
    client.post('/ausencias/1',data=dados)
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM reposicoes').fetchone()[0]==1


def test_concluir_reposicao_atualiza_status_e_indicador(client):
    nova(client)
    client.post('/ausencias/1',data={'acao':'reposicao','data':'2026-11-20','inicio':'18:00','fim':'19:00'})
    with client.application.app_context():
        repo_id=get_db().execute('SELECT id FROM reposicoes').fetchone()[0]
    client.post('/ausencias/1',data={'acao':'concluir_reposicao','reposicao_id':str(repo_id)})
    with client.application.app_context():
        db=get_db()
        assert db.execute('SELECT status FROM ausencias').fetchone()[0]=='REPOSICAO_REALIZADA'
        assert db.execute('SELECT status FROM reposicoes').fetchone()[0]=='REALIZADA'


def test_filtro_exibe_apenas_turma_escolhida(client):
    nova(client)
    nova(client,professor='3',turma='2')
    r=client.get('/?turma=2')
    assert 'Carla Souza'.encode() in r.data
    assert 'Ana Martins'.encode() not in r.data
