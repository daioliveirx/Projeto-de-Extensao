import os, io, uuid
from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_file, send_from_directory
from werkzeug.utils import secure_filename
from .db import get_db, close_db, init_db
from .rules import validar_aula, ha_conflito, conflito_no_registro

ALLOWED={'pdf','png','jpg','jpeg'}


def create_app(test_config=None):
    app = Flask(__name__)

    ambiente_publicacao = os.environ.get("APP_ENV") == "production"
    chave = os.environ.get("SECRET_KEY")

    if ambiente_publicacao and not chave:
        raise RuntimeError(
            "Configure SECRET_KEY antes de publicar o sistema."
        )

    app.config.update(
        SECRET_KEY=chave or "demo-local-nao-producao",
        DATABASE=os.environ.get(
            "DATABASE",
            os.path.join(app.instance_path, "gestao.db")
        ),
        UPLOAD_FOLDER=os.path.join(app.instance_path, "uploads"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024
    )

    if test_config:
        app.config.update(test_config)

    os.makedirs(
        os.path.dirname(app.config["DATABASE"]),
        exist_ok=True
    )
    os.makedirs(
        app.config["UPLOAD_FOLDER"],
        exist_ok=True
    )

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    from flask import session, redirect, url_for
    import hmac

    @app.before_request
    def proteger_acesso():
        # Os testes automatizados continuam isolados.
        if app.config.get('TESTING'):
            return None

        # A proteção será exigida quando ativada na hospedagem.
        if os.environ.get('DEMO_REQUIRE_LOGIN') != '1':
            return None

        if request.endpoint in ('login_demo', 'static'):
            return None

        if session.get('demo_autenticado'):
            return None

        return redirect(url_for('login_demo'))

    @app.route('/acesso', methods=['GET', 'POST'])
    def login_demo():
        if request.method == 'POST':
            senha = request.form.get('senha', '')
            senha_correta = os.environ.get('DEMO_ACCESS_PASSWORD', '')

            if senha_correta and hmac.compare_digest(senha, senha_correta):
                session.clear()
                session['demo_autenticado'] = True
                return redirect(url_for('index'))

            return '''
                <h2>Acesso não autorizado</h2>
                <p>Senha incorreta.</p>
                <a href="/acesso">Tentar novamente</a>
            ''', 401

        return '''
            <!doctype html>
            <html lang="pt-BR">
            <head>
                <meta charset="utf-8">
                <title>Acesso ao protótipo</title>
            </head>
            <body style="font-family:Arial;max-width:400px;margin:80px auto">
                <h2>Gestão Docente</h2>
                <p>Protótipo acadêmico — acesso restrito</p>
                <form method="post">
                    <label>Senha de acesso</label>
                    <input type="password" name="senha" required
                           style="display:block;width:100%;padding:10px;margin:12px 0">
                    <button type="submit">Entrar</button>
                </form>
            </body>
            </html>
        '''

    @app.route('/')
    def index():
        db=get_db()
        filtro=request.args.get('turma','')
        q='''SELECT a.*,p.nome professor,t.nome turma,d.nome disciplina,s.professor_id substituto_id,ps.nome substituto
          FROM ausencias a JOIN professores p ON p.id=a.professor_id JOIN turmas t ON t.id=a.turma_id JOIN disciplinas d ON d.id=a.disciplina_id
          LEFT JOIN substituicoes s ON s.ausencia_id=a.id LEFT JOIN professores ps ON ps.id=s.professor_id'''
        params=[]
        if filtro.isdigit(): q+=' WHERE a.turma_id=?';params=[int(filtro)]
        q+=' ORDER BY a.data DESC,a.inicio DESC'
        rows=db.execute(q,params).fetchall()
        stats={k:db.execute('SELECT COUNT(*) FROM ausencias WHERE status=?',(k,)).fetchone()[0] for k in ('VAGA','SUBSTITUIDA','REPOSICAO_AGENDADA')}
        stats['TOTAL']=db.execute('SELECT COUNT(*) FROM ausencias').fetchone()[0]
        stats['SEM_COBERTURA']=db.execute("SELECT COUNT(*) FROM ausencias WHERE status IN ('VAGA','REPOSICAO_AGENDADA','REPOSICAO_REALIZADA')").fetchone()[0]
        stats['REPOSICOES_PENDENTES']=db.execute("SELECT COUNT(*) FROM reposicoes WHERE status='AGENDADA'").fetchone()[0]
        return render_template('index.html',rows=rows,stats=stats,turmas=db.execute('SELECT * FROM turmas').fetchall(),filtro=filtro)

    @app.route('/ausencias/nova',methods=['GET','POST'])
    def nova():
        db=get_db()
        if request.method=='POST':
            try:
                professor=int(request.form['professor_id']);turma=int(request.form['turma_id']);disciplina=int(request.form['disciplina_id'])
                data=request.form['data'];inicio=request.form['inicio'];fim=request.form['fim'];motivo=request.form['motivo'].strip()
                validar_aula(data,inicio,fim)
                if not motivo: raise ValueError('Informe o motivo.')
                for tabela,id_ in [('professores',professor),('turmas',turma),('disciplinas',disciplina)]:
                    if not db.execute(f'SELECT 1 FROM {tabela} WHERE id=?',(id_,)).fetchone(): raise ValueError('Cadastro de referência inválido.')
                conflito=conflito_no_registro(db,professor,turma,data,inicio,fim)
                if conflito:
                    motivo_conflito = 'professor' if conflito['professor_id']==professor else 'turma'
                    raise ValueError(f'Conflito de horário: {motivo_conflito} já possui aula nesse período (ausência #{conflito["id"]}).')
                cur=db.execute('INSERT INTO ausencias(professor_id,turma_id,disciplina_id,data,inicio,fim,motivo,observacoes) VALUES(?,?,?,?,?,?,?,?)',(professor,turma,disciplina,data,inicio,fim,motivo,request.form.get('observacoes','')))
                db.execute('INSERT INTO auditoria(evento,referencia,detalhe) VALUES(?,?,?)',('AUSENCIA_CRIADA',str(cur.lastrowid),motivo));db.commit()
                flash('Ausência registrada. Aula classificada automaticamente como VAGA.','ok')
                return redirect(url_for('detalhe',id=cur.lastrowid))
            except (ValueError,KeyError) as e: flash('Não foi possível registrar: '+str(e),'erro')
        return render_template('nova.html',professores=db.execute('SELECT * FROM professores WHERE ativo=1').fetchall(),turmas=db.execute('SELECT * FROM turmas').fetchall(),disciplinas=db.execute('SELECT * FROM disciplinas').fetchall(),hoje=date.today().isoformat())

    @app.route('/ausencias/<int:id>',methods=['GET','POST'])
    def detalhe(id):
        db=get_db();a=db.execute('''SELECT a.*,p.nome professor,t.nome turma,d.nome disciplina FROM ausencias a JOIN professores p ON p.id=a.professor_id JOIN turmas t ON t.id=a.turma_id JOIN disciplinas d ON d.id=a.disciplina_id WHERE a.id=?''',(id,)).fetchone()
        if not a: abort(404)
        if request.method=='POST':
            acao=request.form.get('acao')
            try:
                if acao=='substituir':
                    professor=int(request.form['professor_id'])
                    if not db.execute('SELECT 1 FROM professores WHERE id=? AND ativo=1',(professor,)).fetchone(): raise ValueError('Substituto inválido.')
                    if a['status'] in ('REPOSICAO_AGENDADA','REPOSICAO_REALIZADA'):
                        raise ValueError('Esta ausência já possui reposição; não é possível adicionar substituição.')
                    if ha_conflito(db,professor,a['data'],a['inicio'],a['fim'],id): raise ValueError('Professor indisponível: ausente, com aula própria ou com substituição conflitante.')
                    db.execute('INSERT INTO substituicoes(ausencia_id,professor_id) VALUES(?,?) ON CONFLICT(ausencia_id) DO UPDATE SET professor_id=excluded.professor_id',(id,professor))
                    db.execute('UPDATE ausencias SET status=? WHERE id=?',('SUBSTITUIDA',id))
                elif acao=='reposicao':
                    data=request.form['data'];inicio=request.form['inicio'];fim=request.form['fim'];validar_aula(data,inicio,fim)
                    if a['status']=='SUBSTITUIDA':
                        raise ValueError('A aula já foi coberta por substituto; reposição não necessária.')
                    if a['status'] in ('REPOSICAO_AGENDADA','REPOSICAO_REALIZADA'):
                        raise ValueError('Já existe reposição vinculada a esta ausência.')
                    if data<a['data']:
                        raise ValueError('A reposição não pode anteceder a data da ausência.')
                    db.execute('INSERT INTO reposicoes(ausencia_id,data,inicio,fim,observacoes) VALUES(?,?,?,?,?)',(id,data,inicio,fim,request.form.get('observacoes','')))
                    db.execute('UPDATE ausencias SET status=? WHERE id=?',('REPOSICAO_AGENDADA',id))
                elif acao=='documento':
                    f=request.files.get('arquivo');tipo=request.form.get('tipo','COMPROVACAO')
                    if tipo not in ('ATESTADO','COMPROVACAO'): raise ValueError('Tipo de documento inválido.')
                    if not f or not f.filename or '.' not in f.filename or f.filename.rsplit('.',1)[1].lower() not in ALLOWED: raise ValueError('Envie PDF, PNG ou JPG.')
                    nome=secure_filename(f.filename)
                    caminho=str(uuid.uuid4())+'_'+nome
                    f.save(os.path.join(app.config['UPLOAD_FOLDER'],caminho))
                    db.execute('INSERT INTO documentos(ausencia_id,tipo,nome_arquivo,caminho) VALUES(?,?,?,?)',(id,tipo,nome,caminho))
                elif acao=='concluir_reposicao':
                    repo=int(request.form['reposicao_id'])
                    resultado=db.execute('UPDATE reposicoes SET status=? WHERE id=? AND ausencia_id=? AND status=?',('REALIZADA',repo,id,'AGENDADA'))
                    if resultado.rowcount!=1: raise ValueError('Reposição pendente não encontrada.')
                    db.execute('UPDATE ausencias SET status=? WHERE id=?',('REPOSICAO_REALIZADA',id))
                else: raise ValueError('Ação desconhecida.')
                db.execute('INSERT INTO auditoria(evento,referencia,detalhe) VALUES(?,?,?)',(acao.upper(),str(id),'Ação registrada no protótipo'))
                db.commit();flash('Operação registrada com sucesso.','ok');return redirect(url_for('detalhe',id=id))
            except (ValueError,KeyError, __import__('sqlite3').IntegrityError) as e: db.rollback();flash('Operação recusada: '+str(e),'erro')
        return render_template('detalhe.html',a=a,professores=db.execute('SELECT * FROM professores WHERE ativo=1 AND id<>?',(a['professor_id'],)).fetchall(),substituicao=db.execute('SELECT p.nome FROM substituicoes s JOIN professores p ON p.id=s.professor_id WHERE s.ausencia_id=?',(id,)).fetchone(),reposicoes=db.execute('SELECT * FROM reposicoes WHERE ausencia_id=? ORDER BY data',(id,)).fetchall(),documentos=db.execute('SELECT * FROM documentos WHERE ausencia_id=?',(id,)).fetchall())

    @app.route('/documentos/<int:id>')
    def documento(id):
        db=get_db();d=db.execute('SELECT * FROM documentos WHERE id=?',(id,)).fetchone()
        if not d: abort(404)
        return send_from_directory(app.config['UPLOAD_FOLDER'],d['caminho'],as_attachment=True,download_name=d['nome_arquivo'])

    @app.route('/relatorio.pdf')
    def relatorio():
        """Relatório gerencial consolidado, restrito a dados fictícios do protótipo."""
        from html import escape
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import landscape, A4

        db=get_db()
        rows=db.execute("""SELECT a.*,p.nome professor,t.nome turma,d.nome disciplina,
            ps.nome substituto
            FROM ausencias a JOIN professores p ON p.id=a.professor_id
            JOIN turmas t ON t.id=a.turma_id JOIN disciplinas d ON d.id=a.disciplina_id
            LEFT JOIN substituicoes s ON s.ausencia_id=a.id
            LEFT JOIN professores ps ON ps.id=s.professor_id
            ORDER BY a.data DESC,a.inicio DESC,a.id DESC""").fetchall()
        total=len(rows)
        sem_cobertura=sum(r['status']!='SUBSTITUIDA' for r in rows)
        substituidas=sum(r['status']=='SUBSTITUIDA' for r in rows)
        pendentes=db.execute("SELECT COUNT(*) FROM reposicoes WHERE status='AGENDADA'").fetchone()[0]
        buff=io.BytesIO()
        doc=SimpleDocTemplate(buff,pagesize=landscape(A4),leftMargin=35,rightMargin=35,topMargin=38,bottomMargin=40)
        navy=colors.HexColor('#132E45');green=colors.HexColor('#087F72')
        slate=colors.HexColor('#536779');light=colors.HexColor('#F4F7FB');line=colors.HexColor('#DDE6EE')
        title=ParagraphStyle('Tit',fontName='Helvetica-Bold',fontSize=17,leading=21,textColor=navy,spaceAfter=8)
        subt=ParagraphStyle('Sub',fontName='Helvetica',fontSize=9,leading=12,textColor=slate)
        heading=ParagraphStyle('Section',fontName='Helvetica-Bold',fontSize=11,leading=14,textColor=navy)
        txt=ParagraphStyle('Cell',fontName='Helvetica',fontSize=8,leading=10.5,textColor=navy)
        head=ParagraphStyle('Head',fontName='Helvetica-Bold',fontSize=8,leading=10,textColor=colors.white)
        metriclabel=ParagraphStyle('MetricLab',fontName='Helvetica',fontSize=8.5,leading=11,textColor=slate,alignment=TA_CENTER)
        metricnum=ParagraphStyle('MetricNum',fontName='Helvetica-Bold',fontSize=19,leading=23,textColor=green,alignment=TA_CENTER)
        def clean(x): return escape(str(x or '—'))
        def fmt_date(value):
            try: return date.fromisoformat(value).strftime('%d/%m/%Y')
            except (ValueError,TypeError): return str(value)
        story=[Paragraph('Gestão de Ausências Docentes',title),
            Paragraph('RELATÓRIO GERENCIAL  |  Protótipo acadêmico com dados fictícios • Não integrado ao sistema institucional',subt),
            Paragraph('Emitido em '+datetime.now().strftime('%d/%m/%Y às %H:%M'),subt),Spacer(1,16)]
        labels=['Ausências registradas','Sem substituição','Substituídas','Reposições pendentes']
        values=[total,sem_cobertura,substituidas,pendentes]
        grid=[[Paragraph(str(n),metricnum) for n in values],[Paragraph(l,metriclabel) for l in labels]]
        cards=Table(grid,colWidths=[191]*4,rowHeights=[30,24])
        cards.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),light),('BOX',(0,0),(-1,-1),.6,line),('INNERGRID',(0,0),(-1,-1),.5,line),('TOPPADDING',(0,0),(-1,0),4),('BOTTOMPADDING',(0,1),(-1,1),7)]))
        story.extend([cards,Spacer(1,19),Paragraph('Histórico de ausências e encaminhamentos',heading),Spacer(1,7)])
        cols=['Data','Horário','Professor','Turma','Disciplina','Status','Encaminhamento']
        data=[[Paragraph(c,head) for c in cols]]
        for row in rows:
            reposicao=db.execute('SELECT * FROM reposicoes WHERE ausencia_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
            detalhe=('Substituto: '+str(row['substituto'])) if row['substituto'] else (
                ('Reposição: '+fmt_date(reposicao['data'])+' '+reposicao['inicio']+'–'+reposicao['fim']) if reposicao else 'Aguardando encaminhamento')
            vals=[fmt_date(row['data']),row['inicio']+'–'+row['fim'],row['professor'],row['turma'],row['disciplina'],row['status'].replace('_',' '),detalhe]
            data.append([Paragraph(clean(v),txt) for v in vals])
        if len(data)==1:
            data.append([Paragraph('Nenhum registro disponível.',txt)]+['']*6)
        table=Table(data,repeatRows=1,colWidths=[72,82,107,62,131,143,167],hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,light]),('LINEBELOW',(0,0),(-1,0),1,navy),('LINEBELOW',(0,1),(-1,-1),.35,line),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story.append(table)
        story.extend([Spacer(1,14),Paragraph('Nota: "Sem substituição" inclui aulas vagas ou destinadas à reposição. Reposições agendadas não significam cobertura imediata da aula original.',subt)])
        def footer(canvas, pdfdoc):
            canvas.saveState();w,h=landscape(A4)
            canvas.setStrokeColor(line);canvas.line(35,29,w-35,29)
            canvas.setFont('Helvetica',8);canvas.setFillColor(slate)
            canvas.drawString(35,17,'Projeto de Extensão • Equipe ADS 4A • Ambiente demonstrativo')
            canvas.drawRightString(w-35,17,f'Página {pdfdoc.page}')
            canvas.restoreState()
        doc.build(story,onFirstPage=footer,onLaterPages=footer);buff.seek(0)
        return send_file(buff,mimetype='application/pdf',as_attachment=True,download_name='relatorio_gerencial_ausencias.pdf')
    return app
