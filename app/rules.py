from datetime import date, datetime

def validar_aula(data,inicio,fim):
    date.fromisoformat(data)
    datetime.strptime(inicio,'%H:%M'); datetime.strptime(fim,'%H:%M')
    if inicio>=fim: raise ValueError('O horário inicial deve ser anterior ao final.')

def ha_conflito(db, professor_id, data, inicio, fim, ausencia_id):
    # Substituto não pode ser o professor ausente, nem cobrir duas aulas simultâneas.
    original=db.execute('SELECT professor_id FROM ausencias WHERE id=?',(ausencia_id,)).fetchone()
    if original is None: raise ValueError('Ausência não encontrada.')
    if int(original['professor_id'])==int(professor_id): return True
    if professor_tem_aula(db, professor_id, data, inicio, fim, ausencia_id):
        return True
    conflito=db.execute('''SELECT 1 FROM substituicoes s JOIN ausencias a ON a.id=s.ausencia_id
        WHERE s.professor_id=? AND a.data=? AND a.inicio<? AND a.fim>? AND a.id<>? LIMIT 1''',
        (professor_id,data,fim,inicio,ausencia_id)).fetchone()
    return conflito is not None


def conflito_no_registro(db, professor_id, turma_id, data, inicio, fim):
    """Impede duas aulas simultâneas do mesmo professor OU da mesma turma.

    Os intervalos se sobrepõem somente quando inicio < fim_existente
    e fim > inicio_existente; horários consecutivos são permitidos.
    """
    return db.execute("""SELECT a.id, a.professor_id, a.turma_id
        FROM ausencias a WHERE a.data=? AND a.inicio<? AND a.fim>?
        AND (a.professor_id=? OR a.turma_id=?) LIMIT 1""",
        (data, fim, inicio, professor_id, turma_id)).fetchone()


def professor_tem_aula(db, professor_id, data, inicio, fim, ausencia_id):
    """Evita alocar como substituto um docente que já tem aula no período."""
    return db.execute("""SELECT 1 FROM ausencias
        WHERE professor_id=? AND data=? AND inicio<? AND fim>? AND id<>? LIMIT 1""",
        (professor_id, data, fim, inicio, ausencia_id)).fetchone() is not None
