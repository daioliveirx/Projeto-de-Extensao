import os, sqlite3
from flask import g, current_app

def get_db():
    if 'db' not in g:
        g.db=sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory=sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

def close_db(e=None):
    db=g.pop('db',None)
    if db is not None: db.close()

def init_db():
    db=get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS professores (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, email TEXT UNIQUE, ativo INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS turmas (id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS disciplinas (id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS ausencias (id INTEGER PRIMARY KEY, professor_id INTEGER NOT NULL REFERENCES professores(id), turma_id INTEGER NOT NULL REFERENCES turmas(id), disciplina_id INTEGER NOT NULL REFERENCES disciplinas(id), data TEXT NOT NULL, inicio TEXT NOT NULL, fim TEXT NOT NULL, motivo TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'VAGA', observacoes TEXT DEFAULT '', criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(inicio<fim));
    CREATE TABLE IF NOT EXISTS substituicoes (id INTEGER PRIMARY KEY, ausencia_id INTEGER NOT NULL UNIQUE REFERENCES ausencias(id), professor_id INTEGER NOT NULL REFERENCES professores(id), criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS documentos (id INTEGER PRIMARY KEY, ausencia_id INTEGER NOT NULL REFERENCES ausencias(id), tipo TEXT NOT NULL, nome_arquivo TEXT NOT NULL, caminho TEXT NOT NULL, criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS reposicoes (id INTEGER PRIMARY KEY, ausencia_id INTEGER NOT NULL REFERENCES ausencias(id), data TEXT NOT NULL, inicio TEXT NOT NULL, fim TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'AGENDADA', observacoes TEXT DEFAULT '', CHECK(inicio<fim));
    CREATE TABLE IF NOT EXISTS auditoria (id INTEGER PRIMARY KEY, evento TEXT NOT NULL, referencia TEXT, detalhe TEXT, criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    ''')
    if db.execute('SELECT COUNT(*) FROM professores').fetchone()[0]==0:
        db.executemany('INSERT INTO professores(nome,email) VALUES(?,?)', [('Ana Martins','ana@exemplo.edu.br'),('Bruno Lima','bruno@exemplo.edu.br'),('Carla Souza','carla@exemplo.edu.br'),('Daniel Rocha','daniel@exemplo.edu.br')])
        db.executemany('INSERT INTO turmas(nome) VALUES(?)',[('ADS 4A',),('ADS 3A',),('GTI 2A',)])
        db.executemany('INSERT INTO disciplinas(nome) VALUES(?)',[('Programação Web',),('Banco de Dados',),('Engenharia de Software',)])
    db.commit()
